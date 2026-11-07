"""QR Studio API + static site. Starlette app; run with: uvicorn app.main:app"""
import asyncio
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

from PIL import Image
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from . import config, db, payload as pl, pricing, security, uploads
from .payments import fam, orders
from .render import engine, qrdraw
from .security import ApiError, rate_limit, require_user
from .util import body, ok
from . import admin, growth, notify, referrals, seo

RATE = lambda k, d: int(config.get("limits.rate." + k, d))  # noqa: E731
SAMPLE = {"kind": "upi", "fields": {"upi_id": "yourname@upi"}, "name": "Arman Khan", "title": "Your Pocket UPI QR",
          "tag": "SCAN · PAY · DONE", "dynamic": False, "style": {"dot": "dot", "ink": "#0b0b10", "logo": "letter", "logo_id": ""}}


def public_user(u):
    if not u:
        return None
    adm = bool(u["is_admin"] or u["email"].lower() in [e.lower() for e in config.get("admin.emails", [])])
    return {"id": u["id"], "email": u["email"], "name": u["name"], "admin": adm, "pass_until": u["pass_until"], "pass_active": u["pass_until"] > time.time()}


def frozen_design(raw: dict, user):
    d = pl.clean_design(raw)
    if d["style"]["logo"] == "image":
        if not user or not db.one("SELECT 1 FROM logos WHERE id=? AND owner_id=?", (d["style"]["logo_id"], user["id"])):
            d["style"]["logo"], d["style"]["logo_id"] = "letter", ""
    return d


# ---------------- auth ----------------
async def signup(request: Request):
    ip = security.client_ip(request)
    rate_limit("auth", ip, RATE("auth_per_10min", 12), 600)
    if not config.get("security.signup_open", True) or admin.meta_get("signups_closed", "0") == "1":
        raise ApiError(403, "Sign ups are closed right now")
    d = await body(request, 5000)
    email, name, pw = str(d.get("email", "")).strip().lower(), str(d.get("name", "")).strip()[:40], str(d.get("password", ""))
    if not security.valid_email(email):
        raise ApiError(400, "Enter a valid email address")
    if len(name) < 2:
        raise ApiError(400, "Enter your name")
    if len(pw) < int(config.get("security.password_min_length", 8)) or len(pw) > 200:
        raise ApiError(400, "Password needs at least %d characters" % config.get("security.password_min_length", 8))
    if not d.get("accept_terms"):
        raise ApiError(400, "Accept the Terms and Privacy Policy to continue")
    if db.one("SELECT 1 FROM users WHERE email=?", (email,)):
        security.burn_time()
        raise ApiError(409, "An account with this email already exists. Log in instead.")
    is_admin = 1 if email in [e.lower() for e in config.get("admin.emails", [])] else 0
    ref_by = referrals.find_referrer(str(d.get("ref", "")))
    src = re.sub(r"[^a-z0-9._:-]", "", str(d.get("src", "")).lower())[:40]
    uid, _ = db.run("INSERT INTO users(email,name,pw_hash,created,is_admin,referred_by,signup_src) VALUES(?,?,?,?,?,?,?)",
                    (email, name, await run_in_threadpool(security.hash_password, pw), time.time(), is_admin, ref_by, ("invite" if ref_by else src)))
    notify.send("New signup: %s%s" % (name, " (invited)" if ref_by else (" via " + src if src else "")), key="signup", every=0)
    resp = ok({"user": public_user(db.one("SELECT * FROM users WHERE id=?", (uid,)))})
    security.set_cookie(resp, security.create_session(request, uid))
    return resp


async def login(request: Request):
    ip = security.client_ip(request)
    rate_limit("auth", ip, RATE("auth_per_10min", 12), 600)
    d = await body(request, 5000)
    email, pw = str(d.get("email", "")).strip().lower(), str(d.get("password", ""))[:200]
    rate_limit("login-acct", email, 8, 600)
    u = db.one("SELECT * FROM users WHERE email=?", (email,))
    good = await run_in_threadpool(security.check_password, pw, u["pw_hash"]) if u else (await run_in_threadpool(security.burn_time) or False)
    if not (u and good) or u["banned"]:
        db.log_event("anon", "login_fail", email[:60], ip, "banned" if (u and good) else "bad credentials")
        raise ApiError(401, "Email or password is wrong")
    resp = ok({"user": public_user(u)})
    security.set_cookie(resp, security.create_session(request, u["id"]))
    return resp


async def logout(request: Request):
    security.destroy_session(request)
    resp = ok()
    security.clear_cookie(resp)
    return resp


async def me(request: Request):
    u, s = security.current(request)
    pu = public_user(u)
    if pu:
        try:
            pu["credits"] = referrals.stats(u["id"])["available"]
        except Exception:
            pu["credits"] = 0
    return ok({"user": pu, "csrf": s["csrf"] if s else None,
               "pricing": config.get("pricing"), "payments_mode": config.get("payments.mode"), "upi_id": config.get("payments.upi_id")})


async def change_password(request: Request):
    u = require_user(request)
    d = await body(request, 5000)
    if not await run_in_threadpool(security.check_password, str(d.get("old", "")), u["pw_hash"]):
        raise ApiError(403, "Current password is wrong")
    new = str(d.get("new", ""))
    if len(new) < int(config.get("security.password_min_length", 8)) or len(new) > 200:
        raise ApiError(400, "New password needs at least %d characters" % config.get("security.password_min_length", 8))
    db.run("UPDATE users SET pw_hash=? WHERE id=?", (await run_in_threadpool(security.hash_password, new), u["id"]))
    tok = request.cookies.get(config.get("security.cookie_name", "qs_session"), "")
    db.run("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (u["id"], security._th(tok)))
    return ok()


async def delete_account(request: Request):
    u = require_user(request)
    d = await body(request, 2000)
    if not await run_in_threadpool(security.check_password, str(d.get("password", "")), u["pw_hash"]):
        raise ApiError(403, "Password is wrong")
    for t in ("sessions", "qrs", "user_themes", "logos", "downloads"):
        db.run("DELETE FROM %s WHERE %s=?" % (t, "owner_id" if t in ("user_themes", "logos") else "user_id"), (u["id"],))
    db.run("DELETE FROM users WHERE id=?", (u["id"],))
    import shutil
    for k in ("logos", "user_themes"):
        shutil.rmtree(config.data_dir() / k / str(u["id"]), ignore_errors=True)
    resp = ok()
    security.clear_cookie(resp)
    return resp


# ---------------- themes ----------------
def theme_card(t, mine=False):
    return {"id": t["id"], "name": t["name"], "category": t.get("category", ""), "accent": t.get("accent"), "layout": t.get("layout"), "mine": mine}


async def list_themes(request: Request):
    u, _ = security.current(request)
    out = [theme_card(t) for t in engine.builtin_themes().values()]
    if u:
        for r in db.many("SELECT manifest FROM user_themes WHERE owner_id=? ORDER BY created DESC", (u["id"],)):
            out.append(theme_card(json.loads(r["manifest"]), True))
    return ok({"themes": out})


async def theme_thumb(request: Request):
    tid = request.path_params["tid"]
    u, _ = security.current(request)
    t = uploads.get_theme(tid, u)
    if not t:
        raise ApiError(404, "Theme not found")
    cache = config.data_dir() / "cache"
    cache.mkdir(exist_ok=True)
    f = cache / (tid + ("-u%d" % u["id"] if not t.get("builtin") else "") + ".jpg")
    if not f.exists():
        def make():
            d = dict(SAMPLE)
            img = engine.render_poster(t, d, pl.build_payload(d), 0.36, True)
            buf = BytesIO()
            img.save(buf, "JPEG", quality=70)
            f.write_bytes(buf.getvalue())
        await run_in_threadpool(make)
    return Response(f.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


async def theme_upload(request: Request):
    u = require_user(request, csrf=False)  # multipart: csrf via header too
    sent = request.headers.get("x-csrf-token", "")
    _, s = security.current(request)
    if not sent or sent != s["csrf"]:
        raise ApiError(403, "Session check failed. Refresh the page and try again.")
    rate_limit("upload", str(u["id"]), RATE("upload_per_10min", 20), 600)
    form = await request.form(max_files=1, max_fields=12)
    f = form.get("image")
    if f is None or not hasattr(f, "read"):
        raise ApiError(400, "Choose an image")
    data = await f.read()
    qr_box = None
    if form.get("tpl") == "D":
        try:
            qr_box = {"x": int(form.get("qx", 262)), "y": int(form.get("qy", 430)), "size": int(form.get("qs", 500))}
        except ValueError:
            raise ApiError(400, "QR position must be numbers")
    m = await run_in_threadpool(uploads.save_theme, u["id"], data, str(form.get("name", "")), str(form.get("tpl", "A")), str(form.get("accent", "#4da3ff")), str(form.get("ink", "#ffffff")), str(form.get("soft", "#e6f0ff")), qr_box)
    return ok({"theme": theme_card(m, True)})


async def theme_delete(request: Request):
    u = require_user(request)
    if not uploads.delete_theme(u["id"], request.path_params["tid"]):
        raise ApiError(404, "Theme not found")
    return ok()


async def logo_upload(request: Request):
    u = require_user(request, csrf=False)
    _, s = security.current(request)
    if request.headers.get("x-csrf-token", "") != s["csrf"]:
        raise ApiError(403, "Session check failed. Refresh the page and try again.")
    rate_limit("upload", str(u["id"]), RATE("upload_per_10min", 20), 600)
    form = await request.form(max_files=1, max_fields=4)
    f = form.get("image")
    if f is None or not hasattr(f, "read"):
        raise ApiError(400, "Choose an image")
    lid = await run_in_threadpool(uploads.save_logo, u["id"], await f.read())
    return ok({"logo_id": lid})


async def logo_get(request: Request):
    u = require_user(request, csrf=False)
    lid = request.path_params["lid"]
    if not lid.isalnum():
        raise ApiError(404, "Not found")
    p = config.data_dir() / "logos" / str(u["id"]) / (lid + ".png")
    if not p.exists():
        raise ApiError(404, "Not found")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


async def logo_list(request: Request):
    u = require_user(request, csrf=False)
    return ok({"logos": [r["id"] for r in db.many("SELECT id FROM logos WHERE owner_id=? ORDER BY created DESC", (u["id"],))]})


# ---------------- preview ----------------
async def preview(request: Request):
    """Watermarked JPEG at preview scale. Clean artwork is never returned from this endpoint."""
    u, _ = security.current(request)
    rate_limit("preview", str(u["id"]) if u else security.client_ip(request), RATE("preview_per_min", 90), 60)
    d = await body(request)
    theme = uploads.get_theme(str(d.get("theme_id", "")), u)
    if not theme:
        raise ApiError(404, "Theme not found")
    design = frozen_design(d.get("design"), u)
    logo = uploads.load_logo(u["id"], design["style"]["logo_id"]) if (u and design["style"]["logo"] == "image") else None
    slug = "preview" if design["dynamic"] else ""
    payload = pl.build_payload(design, config.get("server.public_url", ""), slug)
    scale = float(config.get("render.preview_scale", 0.625))
    q = int(config.get("render.preview_jpeg_quality", 70))
    tag = ("user %d" % u["id"]) if u else "guest"

    def work():
        img = engine.render_poster(theme, design, payload, scale, True, logo, tag)
        scan = engine.scan_check(theme, design, payload, logo)
        buf = BytesIO()
        img.save(buf, "JPEG", quality=q)
        return buf.getvalue(), scan

    try:
        data, scan = await run_in_threadpool(work)
    except ValueError:
        raise ApiError(422, "Too much data for one QR code. Shorten it.")
    items, rupees, raw = pricing.breakdown(design, theme)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Scan-OK": "1" if scan else "0", "X-Price": str(rupees),
                                                            "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline; filename=preview.jpg"})


async def price_quote(request: Request):
    u, _ = security.current(request)
    d = await body(request)
    theme = uploads.get_theme(str(d.get("theme_id", "")), u)
    if not theme:
        raise ApiError(404, "Theme not found")
    design = frozen_design(d.get("design"), u)
    items, rupees, raw = pricing.breakdown(design, theme, bool(d.get("print")))
    return ok({"items": [{"label": a, "rupees": b} for a, b in items], "rupees": rupees, "raw": raw, "pass_active": bool(u and u["pass_until"] > time.time()),
               "pass_price": config.get("pricing.pass_price", 99), "pass_days": config.get("pricing.pass_days", 30)})


# ---------------- saved QRs ----------------
def qr_row(r):
    d = json.loads(r["design"])
    return {"id": r["id"], "title": r["title"], "theme_id": r["theme_id"], "design": d, "created": r["created"], "updated": r["updated"], "slug": r["slug"],
            "dyn_active": bool(r["dyn_active"]), "scans": r["scans"]}


async def qr_list(request: Request):
    u = require_user(request, csrf=False)
    rows = db.many("SELECT * FROM qrs WHERE user_id=? ORDER BY updated DESC", (u["id"],))
    paid = {r["qr_id"] for r in db.many("SELECT DISTINCT qr_id FROM orders WHERE user_id=? AND status='paid' AND kind='export'", (u["id"],))}
    out = []
    for r in rows:
        x = qr_row(r)
        x["paid"] = r["id"] in paid
        out.append(x)
    return ok({"qrs": out})


async def qr_save(request: Request):
    u = require_user(request)
    d = await body(request)
    theme = uploads.get_theme(str(d.get("theme_id", "")), u)
    if not theme:
        raise ApiError(404, "Theme not found")
    design = frozen_design(d.get("design"), u)
    title = str(d.get("title") or design["name"] or "Untitled QR").strip()[:60]
    qid = d.get("id")
    t = time.time()
    if qid:
        r = db.one("SELECT * FROM qrs WHERE id=? AND user_id=?", (qid, u["id"]))
        if not r:
            raise ApiError(404, "QR not found")
        slug = r["slug"] or (secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")[:8] if design["dynamic"] else None)
        db.run("UPDATE qrs SET title=?, design=?, theme_id=?, updated=?, slug=? WHERE id=?", (title, json.dumps(design), theme["id"], t, slug, qid))
    else:
        n = db.one("SELECT COUNT(*) n FROM qrs WHERE user_id=?", (u["id"],))["n"]
        if n >= int(config.get("limits.max_saved_qrs_per_user", 200)):
            raise ApiError(409, "Saved QR limit reached. Delete some first.")
        slug = secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")[:8] if design["dynamic"] else None
        qid, _ = db.run("INSERT INTO qrs(user_id,title,design,theme_id,created,updated,slug) VALUES(?,?,?,?,?,?,?)", (u["id"], title, json.dumps(design), theme["id"], t, t, slug))
    return ok({"id": qid, "slug": slug})


async def qr_delete(request: Request):
    u = require_user(request)
    _, n = db.run("DELETE FROM qrs WHERE id=? AND user_id=?", (request.path_params["qid"], u["id"]))
    if not n:
        raise ApiError(404, "QR not found")
    return ok()


async def qr_retarget(request: Request):
    """Dynamic QR: change where the printed code points, without changing the code."""
    u = require_user(request)
    r = db.one("SELECT * FROM qrs WHERE id=? AND user_id=?", (request.path_params["qid"], u["id"]))
    if not r or not r["slug"]:
        raise ApiError(404, "Dynamic QR not found")
    d = await body(request, 3000)
    url = str(d.get("url", "")).strip()
    if not pl.URL_RE.match(url):
        raise ApiError(400, "Link must start with http:// or https://")
    design = json.loads(r["design"])
    design["fields"]["url"] = url
    db.run("UPDATE qrs SET design=?, updated=? WHERE id=?", (json.dumps(design), time.time(), r["id"]))
    return ok()


async def redirect_slug(request: Request):
    r = db.one("SELECT * FROM qrs WHERE slug=?", (request.path_params["slug"],))
    if not r or not r["dyn_active"]:
        return HTMLResponse("<h1>This QR is not active</h1>", status_code=404)
    db.run("UPDATE qrs SET scans=scans+1 WHERE id=?", (r["id"],))
    url = json.loads(r["design"])["fields"].get("url", "")
    if not pl.URL_RE.match(url):
        return HTMLResponse("<h1>Invalid link</h1>", status_code=404)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})


# ---------------- orders / payments ----------------
def order_public(o):
    return {"id": o["id"], "kind": o["kind"], "qr_id": o["qr_id"], "status": o["status"], "rupees": o["rupees"], "amount_paise": o["amount_paise"], "created": o["created"],
            "expires": o["expires"], "paid_at": o["paid_at"], "utr": o["utr"], "label": o["label"]}


def payments_ready():
    up = config.get("payments.upi_id", "")
    if config.get("payments.mode") == "live" and (not up or up.startswith("yourupi") or not pl.UPI_RE.match(up)):
        raise ApiError(503, "Payments are not set up yet. Please try again later.")


async def order_create(request: Request):
    u = require_user(request)
    rate_limit("order", str(u["id"]), RATE("order_per_10min", 20), 600)
    d = await body(request)
    kind = d.get("kind", "export")
    if kind == "pass":
        payments_ready()
        rupees = int(config.get("pricing.pass_price", 99))
        o = orders.create_order(u["id"], "pass", rupees, None, {"pass": True}, "%d-day unlimited pass" % config.get("pricing.pass_days", 30))
    else:
        r = db.one("SELECT * FROM qrs WHERE id=? AND user_id=?", (d.get("qr_id"), u["id"]))
        if not r:
            raise ApiError(404, "Save the QR first")
        theme = uploads.get_theme(r["theme_id"], u)
        if not theme:
            raise ApiError(404, "The theme for this QR was removed. Pick another theme and save.")
        design = json.loads(r["design"])
        print_pack = bool(d.get("print"))
        items, rupees, _ = pricing.breakdown(design, theme, print_pack)
        active_pass = u["pass_until"] > time.time()
        if active_pass:
            rupees = 0
        snap = {"design": design, "theme_id": theme["id"], "slug": r["slug"], "dynamic": design.get("dynamic", False), "print": print_pack}
        use_credit = bool(d.get("use_credit")) and rupees > 0
        if use_credit:
            if rupees > referrals.credit_max():
                raise ApiError(422, "A free credit covers designs up to ₹%d. Remove an extra (print pack, dynamic link or logo) or pay." % referrals.credit_max())
            referrals.consume(u["id"])
            try:
                o = orders.create_order(u["id"], "export", 0, r["id"], snap, r["title"] + " (invite credit)", free_ref="INVITE-CREDIT")
            except Exception:
                referrals.refund(u["id"])
                raise
        else:
            if rupees > 0:
                payments_ready()
            o = orders.create_order(u["id"], "export", rupees, r["id"], snap, r["title"])
        if active_pass and snap["dynamic"]:
            db.run("UPDATE qrs SET dyn_active=1 WHERE id=?", (r["id"],))
    row = db.one("SELECT * FROM orders WHERE id=?", (o["id"],))
    db.log_event("user:%d" % u["id"], "order_created", o["id"], security.client_ip(request), "%.2f INR %s" % (row["amount_paise"] / 100, kind))
    out = order_public(row)
    out["upi_link"] = orders.upi_link(row) if row["status"] == "pending" else None
    out["payee"] = config.get("payments.upi_id")
    return ok({"order": out})


async def order_get(request: Request):
    u = require_user(request, csrf=False)
    o = db.one("SELECT * FROM orders WHERE id=? AND user_id=?", (request.path_params["oid"], u["id"]))
    if not o:
        raise ApiError(404, "Order not found")
    if o["status"] == "pending" and o["expires"] < time.time():
        db.run("UPDATE orders SET status='expired' WHERE id=?", (o["id"],))
        o["status"] = "expired"
    out = order_public(o)
    out["upi_link"] = orders.upi_link(o) if o["status"] == "pending" else None
    out["payee"] = config.get("payments.upi_id")
    out["print"] = bool(json.loads(o["snapshot"] or "{}").get("print"))
    return ok({"order": out})


async def order_list(request: Request):
    u = require_user(request, csrf=False)
    rows = db.many("SELECT * FROM orders WHERE user_id=? AND kind!='test' ORDER BY created DESC LIMIT 100", (u["id"],))
    return ok({"orders": [order_public(o) for o in rows]})


REF_RE = re.compile(r"^[A-Za-z0-9]{8,40}$")


async def order_verify(request: Request):
    """Customer confirms payment. Three ways: UTR, Fam Transaction ID, or 'my payment has no UTR' (Fam to Fam). All go through one atomic claim."""
    u = require_user(request)
    ip = security.client_ip(request)
    oid = request.path_params["oid"]
    rate_limit("verify", str(u["id"]), RATE("verify_per_min", 8), 60)
    # hard lock after repeated wrong guesses on one order (a UTR cannot be brute forced)
    if security.penalty_count("vfail", oid, 1800) >= 10 or security.penalty_count("vfail-u", str(u["id"]), 3600) >= 25:
        db.log_event("user:%d" % u["id"], "verify_locked", oid, ip, "too many wrong attempts")
        raise ApiError(429, "Too many wrong attempts. Wait 30 minutes or contact support with your order number.")
    d = await body(request, 2000)
    try:
        if d.get("mode") == "amount":
            res = await run_in_threadpool(orders.claim_by_amount, oid, u["id"], ip)
        else:
            ref = re.sub(r"\s", "", str(d.get("utr", "")))
            if not REF_RE.match(ref):
                raise ApiError(400, "Enter the 12-digit UTR or the Transaction ID from the Fam email.")
            res = await run_in_threadpool(orders.claim, oid, u["id"], ref, ip)
    except ApiError as e:
        if e.status in (404, 409, 422) and d.get("mode") != "amount":     # only guessable inputs count towards the lock
            security.penalty_add("vfail", oid)
            security.penalty_add("vfail-u", str(u["id"]))
            db.log_event("user:%d" % u["id"], "verify_fail", oid, ip, e.message[:200])
        raise
    return ok(res)


async def order_payqr(request: Request):
    """PNG of the UPI QR for this order (the customer scans it with any UPI app)."""
    u = require_user(request, csrf=False)
    o = db.one("SELECT * FROM orders WHERE id=? AND user_id=? AND status='pending'", (request.path_params["oid"], u["id"]))
    if not o:
        raise ApiError(404, "Pending order not found")
    link = orders.upi_link(o)

    def make():
        panel = qrdraw.draw_panel(520, 520, qrdraw.qr_matrix(link), {"dot": "square", "ink": "#0b0b10", "logo": "none"}, radius=24)
        buf = BytesIO()
        panel.save(buf, "PNG")
        return buf.getvalue()
    return Response(await run_in_threadpool(make), media_type="image/png", headers={"Cache-Control": "private, no-store"})


async def dev_simulate(request: Request):
    """Mock mode only: pretends the Fam email arrived. Disabled when payments.mode is not 'mock'."""
    if config.get("payments.mode") != "mock":
        raise ApiError(404, "Not found")
    u = require_user(request)
    o = db.one("SELECT * FROM orders WHERE id=? AND user_id=? AND status='pending'", (request.path_params["oid"], u["id"]))
    if not o:
        raise ApiError(404, "Pending order not found")
    utr = "".join(secrets.choice("0123456789") for _ in range(12))
    fam.store_payment({"utr": utr, "amount_paise": o["amount_paise"], "received_at": time.time(), "payer": u["name"]}, "mock")
    return ok({"utr": utr})


# ---------------- downloads ----------------
FORMATS = {"png": ("image/png", "png"), "jpg": ("image/jpeg", "jpg"), "pdf": ("application/pdf", "pdf"), "svg": ("image/svg+xml", "svg"), "qrpng": ("image/png", "png")}


async def download(request: Request):
    u = require_user(request, csrf=False)
    oid, fmt = request.path_params["oid"], request.path_params["fmt"]
    if fmt not in FORMATS:
        raise ApiError(404, "Unknown format")
    o = db.one("SELECT * FROM orders WHERE id=? AND user_id=? AND status='paid' AND kind='export'", (oid, u["id"]))
    if not o:
        raise ApiError(402, "Payment required")
    snap = json.loads(o["snapshot"])
    if fmt in ("svg", "qrpng") and not (snap.get("print") or u["pass_until"] > time.time()):
        raise ApiError(402, "Add the print pack to get the QR-only files")
    f = config.data_dir() / "exports" / oid / ("poster." + fmt if fmt not in ("svg", "qrpng") else ("qr.svg" if fmt == "svg" else "qr.png"))

    if not f.exists():
        theme = uploads.get_theme(snap["theme_id"], u)
        if not theme:
            raise ApiError(410, "The theme for this order was deleted")
        design = snap["design"]
        logo = uploads.load_logo(u["id"], design["style"]["logo_id"]) if design["style"]["logo"] == "image" else None
        payload = pl.build_payload(design, config.get("server.public_url", ""), snap.get("slug") or "")

        def make():
            f.parent.mkdir(parents=True, exist_ok=True)
            if fmt in ("png", "jpg", "pdf"):
                img = engine.render_poster(theme, design, payload, float(config.get("render.export_scale", 2.0)), False, logo)
                f.write_bytes(engine.to_bytes(img, fmt))
            elif fmt == "svg":
                f.write_text(qrdraw.svg_qr(qrdraw.qr_matrix(payload), design["style"]), encoding="utf-8")
            else:
                st = dict(design["style"])
                st["letter"] = ((design.get("name") or "Q").strip() or "Q")[0]
                f.write_bytes(qrdraw.transparent_png(qrdraw.qr_matrix(payload), st, logo))
        await run_in_threadpool(make)
    db.run("INSERT INTO downloads(order_id,user_id,fmt,ts) VALUES(?,?,?,?)", (oid, u["id"], fmt, time.time()))
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", o["label"] or "qr")[:40] or "qr"
    mt, ext = FORMATS[fmt]
    return FileResponse(f, media_type=mt, headers={"Content-Disposition": 'attachment; filename="%s-%s.%s"' % (safe, oid, ext), "Cache-Control": "private, no-store"})


async def health(request: Request):
    db.one("SELECT 1")
    return JSONResponse({"ok": True, "time": time.time()})


# ---------------- pages / static ----------------
PAGES = {"/": "index.html", "/studio": "studio.html", "/themes": "themes.html", "/pricing": "pricing.html", "/login": "login.html", "/signup": "signup.html",
         "/dashboard": "dashboard.html", "/theme-maker": "theme-maker.html", "/admin": "admin.html", "/terms": "terms.html", "/privacy": "privacy.html",
         "/faq": "faq.html", "/contact": "contact.html", "/refund": "refund.html", "/receipt": "receipt.html", "/how-it-works": "how-it-works.html", "/about": "about.html"}


async def robots(request: Request):
    return Response(seo.robots_txt(), media_type="text/plain")


async def sitemap(request: Request):
    return Response(await run_in_threadpool(seo.sitemap_xml), media_type="application/xml")


async def manifest(request: Request):
    return JSONResponse(seo.manifest(), media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=86400"})


def html_page(p, status=200, path=None):
    text = p.read_text(encoding="utf-8")
    if path:
        text = seo.inject_static(text, path)
    return HTMLResponse(seo.finalize(text), status_code=status, headers={"Cache-Control": "no-cache, must-revalidate"})


def page_route(path, fname):
    async def h(request: Request):
        p = config.frontend_dir() / fname
        if not p.exists():
            return HTMLResponse("Frontend not found", status_code=500)
        growth.hit(request, path)
        return html_page(p, path=path)
    return Route(path, h, methods=["GET", "HEAD"])


async def site_config(request: Request):
    p = config.frontend_dir() / "config.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    for env, key in (("SITE_NAME", "site_name"), ("OWNER", "owner"), ("SUPPORT_EMAIL", "support_email"), ("SUPPORT_TELEGRAM", "support_telegram"), ("SUPPORT_INSTAGRAM", "support_instagram")):
        if os.environ.get(env):
            data[key] = os.environ[env]
    data["site_url"] = config.site_url()
    try:
        data["announcement"] = admin.meta_get("announcement")
        data["announcement_kind"] = admin.meta_get("announcement_kind", "info")
    except Exception:
        pass
    return JSONResponse(data, headers={"Cache-Control": "no-cache"})


def _seo_route(path, fn, arg=None):
    async def h(request: Request):
        html = fn(request.path_params[arg]) if arg else fn()
        if html is not None:
            growth.hit(request, request.url.path)
        if html is None:
            return HTMLResponse(seo.not_found_html(), status_code=404, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})
    return Route(path, h, methods=["GET", "HEAD"])


SEO_ROUTES = [_seo_route("/qr", seo.qr_index_html), _seo_route("/qr/{slug}", seo.type_html, "slug"), _seo_route("/guides", seo.guides_index_html),
              _seo_route("/guides/{slug}", seo.guide_html, "slug"), _seo_route("/themes/{tid}", seo.theme_html, "tid")]


async def not_found_page(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return HTMLResponse(seo.not_found_html(), status_code=404, headers={"Cache-Control": "no-cache"})


async def api_error(request: Request, exc: ApiError):
    return security.json_error(exc)


async def design_error(request: Request, exc: pl.DesignError):
    return JSONResponse({"error": str(exc)}, status_code=400)


async def server_error(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse({"error": "Something went wrong on our side. Try again."}, status_code=500)


class Guard:
    """Origin check for unsafe methods + security headers on every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        if request.url.path.startswith("/api/") and not security.origin_ok(request):
            resp = JSONResponse({"error": "Blocked cross-site request"}, status_code=403)
            return await resp(scope, receive, send)

        async def send2(msg):
            if msg["type"] == "http.response.start":
                h = dict(msg.get("headers") or [])
                extra = {
                    b"x-content-type-options": b"nosniff", b"x-frame-options": b"DENY", b"referrer-policy": b"same-origin",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                    b"content-security-policy": b"default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
                }
                if config.get("security.cookie_secure"):
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                path = scope.get("path", "")
                if path.startswith("/assets/") and b"cache-control" not in h:
                    if path.endswith((".js", ".css")) and b"v=" in scope.get("query_string", b""):
                        extra[b"cache-control"] = b"public, max-age=31536000, immutable"   # URL changes with every release
                    elif path.endswith((".js", ".css")):
                        extra[b"cache-control"] = b"no-cache"                          # revalidate (304) so a new deploy shows at once
                    else:
                        extra[b"cache-control"] = b"public, max-age=604800, stale-while-revalidate=86400"
                if path.startswith("/api/") and b"cache-control" not in h:
                    extra[b"cache-control"] = b"no-store"
                msg["headers"] = list(msg.get("headers") or []) + [(k, v) for k, v in extra.items() if k not in h]
            await send(msg)
        return await self.app(scope, receive, send2)


_lock_files = []


def single_instance(name: str) -> bool:
    """True for exactly one worker process: used so only one worker runs the Gmail poller."""
    try:
        import fcntl
    except ImportError:  # Windows dev machine
        return True
    f = open(config.data_dir() / name, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_files.append(f)
    return True


@asynccontextmanager
async def lifespan(app):
    engine.builtin_themes()
    if single_instance(".poller.lock"):
        for w in config.WARNINGS:
            print("[qrstudio] WARNING:", w, flush=True)
        print("[qrstudio] payments mode: %s | gmail reader: %s | public url: %s" % (config.get("payments.mode"), "on" if config.get("payments.imap.enabled") else "off", config.get("server.public_url")), flush=True)
        if config.get("payments.imap.enabled"):
            fam.start_poller()

    async def janitor():
        while True:
            db.run("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.run("DELETE FROM rl WHERE ts<?", (time.time() - 7200,))
            try:
                await run_in_threadpool(admin.auto_snapshot)
            except Exception as e:
                print("[qrstudio] snapshot failed:", e, flush=True)
            await asyncio.sleep(3600)
    task = asyncio.create_task(janitor())
    yield
    task.cancel()


def build_app():
    db.init()
    routes = [
        Route("/api/health", health), Route("/config.json", site_config), Route("/robots.txt", robots), Route("/sitemap.xml", sitemap), Route("/manifest.webmanifest", manifest),
        Route("/api/signup", signup, methods=["POST"]), Route("/api/login", login, methods=["POST"]), Route("/api/logout", logout, methods=["POST"]),
        Route("/api/me", me), Route("/api/password", change_password, methods=["POST"]), Route("/api/account/delete", delete_account, methods=["POST"]),
        Route("/api/themes", list_themes), Route("/api/themes/{tid}/thumb", theme_thumb), Route("/api/themes/upload", theme_upload, methods=["POST"]),
        Route("/api/themes/{tid}", theme_delete, methods=["DELETE"]),
        Route("/api/logos", logo_list), Route("/api/logos/upload", logo_upload, methods=["POST"]), Route("/api/logos/{lid}", logo_get),
        Route("/api/preview", preview, methods=["POST"]), Route("/api/quote", price_quote, methods=["POST"]),
        Route("/api/qrs", qr_list), Route("/api/qrs", qr_save, methods=["POST"]), Route("/api/qrs/{qid:int}", qr_delete, methods=["DELETE"]),
        Route("/api/qrs/{qid:int}/target", qr_retarget, methods=["POST"]),
        Route("/api/orders", order_create, methods=["POST"]), Route("/api/orders", order_list),
        Route("/api/orders/{oid}", order_get), Route("/api/orders/{oid}/verify", order_verify, methods=["POST"]),
        Route("/api/orders/{oid}/simulate", dev_simulate, methods=["POST"]), Route("/api/orders/{oid}/payqr", order_payqr),
        Route("/api/orders/{oid}/download/{fmt}", download),
        *admin.routes(), *growth.routes(), *SEO_ROUTES,
        Route("/r/{slug}", redirect_slug),
    ]
    routes += [page_route(p, f) for p, f in PAGES.items()]
    fe = config.frontend_dir()
    if (fe / "assets").exists():
        from starlette.routing import Mount
        routes.append(Mount("/assets", StaticFiles(directory=fe / "assets"), name="assets"))
    from starlette.middleware.gzip import GZipMiddleware
    app = Starlette(routes=routes, middleware=[Middleware(Guard), Middleware(GZipMiddleware, minimum_size=700, compresslevel=5)], lifespan=lifespan,
                    exception_handlers={404: not_found_page, ApiError: api_error, pl.DesignError: design_error, 500: server_error, 405: not_found_page})
    return app


app = build_app()
