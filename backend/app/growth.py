"""Referrals, real reviews, shareable previews, public counters and privacy-friendly page-view analytics."""
import json
import re
import secrets
import time
from io import BytesIO
from urllib.parse import urlparse

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from . import config, db, notify, referrals, security, uploads
from . import payload as pl
from .render import engine
from .security import ApiError, rate_limit, require_user
from .util import body, ok

BOT_RE = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|curl|wget|python|headless|lighthouse|monitor|uptime", re.I)


# ---------------------------------------------------------------- analytics (no cookies, no IPs, no user ids)
def classify_source(request: Request) -> str:
    q = request.query_params
    if q.get("ref"):
        return "invite"
    if q.get("utm_source"):
        return re.sub(r"[^a-z0-9._-]", "", q["utm_source"].lower())[:24] or "campaign"
    ref = request.headers.get("referer", "")
    if not ref:
        return "direct"
    host = (urlparse(ref).hostname or "").lower()
    own = (request.headers.get("host") or "").split(":")[0].lower()
    if host == own or not host:
        return "internal"
    for key, name in (("google.", "google"), ("bing.", "bing"), ("duckduckgo.", "duckduckgo"), ("yahoo.", "yahoo"), ("instagram.", "instagram"), ("facebook.", "facebook"), ("fb.", "facebook"),
                      ("t.co", "x"), ("twitter.", "x"), ("x.com", "x"), ("t.me", "telegram"), ("telegram.", "telegram"), ("whatsapp.", "whatsapp"), ("youtube.", "youtube"),
                      ("reddit.", "reddit"), ("linkedin.", "linkedin"), ("pinterest.", "pinterest")):
        if key in host:
            return name
    return ("site:" + host)[:40]


def hit(request: Request, path: str = ""):
    try:
        if BOT_RE.search(request.headers.get("user-agent", "")) or request.method != "GET":
            return
        p = path or request.url.path
        if p.startswith("/p/"):
            p = "/p/*"
        day = int((time.time() + 19800) // 86400)
        db.run("INSERT INTO hits(day,path,src,n) VALUES(?,?,?,1) ON CONFLICT(day,path,src) DO UPDATE SET n=n+1", (day, p[:120], classify_source(request)))
    except Exception:
        pass


# ---------------------------------------------------------------- referral API
async def referral_info(request: Request):
    u = require_user(request, csrf=False)
    code = referrals.ensure_code(u["id"])
    base = config.site_url()
    return ok({"code": code, "link": "%s/?ref=%s" % (base, code), "stats": referrals.stats(u["id"]),
               "rule": "Invite %d friends. When any one of them pays for a download, you get 1 free download (up to ₹%d). It repeats for every %d friends." % (referrals.per_group(), referrals.credit_max(), referrals.per_group())})


# ---------------------------------------------------------------- reviews (real users only)
def _display_name(name: str) -> str:
    parts = (name or "Customer").split()
    return parts[0] + (" " + parts[-1][0] + "." if len(parts) > 1 else "")


async def review_submit(request: Request):
    u = require_user(request)
    rate_limit("review", str(u["id"]), 5, 3600)
    d = await body(request, 3000)
    try:
        stars = int(d.get("stars", 0))
    except (TypeError, ValueError):
        stars = 0
    text = str(d.get("text", "")).replace("\x00", "").strip()[:300]
    if not 1 <= stars <= 5:
        raise ApiError(400, "Choose 1 to 5 stars")
    if len(text) < 5:
        raise ApiError(400, "Write a few words about your experience")
    if not db.one("SELECT 1 FROM orders WHERE user_id=? AND status='paid' AND kind IN ('export','pass')", (u["id"],)):
        raise ApiError(403, "Reviews are for people who downloaded a poster")
    db.run("INSERT INTO reviews(user_id,name,stars,text,created,status) VALUES(?,?,?,?,?,'pending') "
           "ON CONFLICT(user_id) DO UPDATE SET stars=excluded.stars,text=excluded.text,created=excluded.created,status='pending',name=excluded.name",
           (u["id"], _display_name(u["name"]), stars, text, time.time()))
    notify.send("New review (%d stars) waiting for approval:\n%s" % (stars, text[:200]))
    return ok()


def review_summary():
    rows = db.many("SELECT name,stars,text,created FROM reviews WHERE status='approved' ORDER BY created DESC LIMIT 30")
    n = len(rows)
    total = db.one("SELECT COUNT(*) n, AVG(stars) a FROM reviews WHERE status='approved'")
    return rows[:12], int(total["n"]), round(total["a"] or 0, 1)


async def reviews_public(request: Request):
    rows, n, avg = review_summary()
    return ok({"reviews": rows, "count": n, "average": avg})


async def my_review(request: Request):
    u = require_user(request, csrf=False)
    r = db.one("SELECT stars,text,status FROM reviews WHERE user_id=?", (u["id"],))
    paid = bool(db.one("SELECT 1 FROM orders WHERE user_id=? AND status='paid' AND kind IN ('export','pass')", (u["id"],)))
    return ok({"review": r, "can_review": paid})


async def public_stats(request: Request):
    q = db.one("SELECT COUNT(*) n FROM qrs")["n"]
    mn = int(config.get("seo.min_public_count", 50))
    return ok({"qrs": q, "show": q >= mn}, **{})


# ---------------------------------------------------------------- shareable preview pages
def _share_png_path(token: str, updated: float):
    d = config.data_dir() / "cache" / "share"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(token + "-*.jpg"):
        if old.name != "%s-%d.jpg" % (token, int(updated)):
            old.unlink(missing_ok=True)
    return d / ("%s-%d.jpg" % (token, int(updated)))


async def share_create(request: Request):
    u = require_user(request)
    qid = int(request.path_params["qid"])
    r = db.one("SELECT id,share_token FROM qrs WHERE id=? AND user_id=?", (qid, u["id"]))
    if not r:
        raise ApiError(404, "Save the QR first")
    tok = r["share_token"]
    if not tok:
        tok = secrets.token_urlsafe(9)
        db.run("UPDATE qrs SET share_token=? WHERE id=?", (tok, qid))
    return ok({"url": "%s/p/%s" % (config.site_url(), tok)})


async def share_delete(request: Request):
    u = require_user(request)
    db.run("UPDATE qrs SET share_token=NULL WHERE id=? AND user_id=?", (int(request.path_params["qid"]), u["id"]))
    return ok()


def _shared(token: str):
    r = db.one("SELECT * FROM qrs WHERE share_token=?", (token,))
    if not r:
        return None, None
    return r, db.one("SELECT * FROM users WHERE id=?", (r["user_id"],))


async def share_image(request: Request):
    token = request.path_params["token"]
    r, owner = _shared(token)
    if not r or owner["banned"]:
        raise ApiError(404, "Not found")
    rate_limit("shareimg", security.client_ip(request), 120, 60)
    path = _share_png_path(token, r["updated"])
    if not path.exists():
        theme = uploads.get_theme(r["theme_id"], owner)
        if not theme:
            raise ApiError(404, "Not found")
        design = json.loads(r["design"])
        logo = uploads.load_logo(owner["id"], design["style"]["logo_id"]) if design["style"]["logo"] == "image" else None
        payload = pl.build_payload(design, config.get("server.public_url", ""), "preview" if design.get("dynamic") else "")

        def work():
            img = engine.render_poster(theme, design, payload, 0.8, True, logo, "share")
            buf = BytesIO()
            img.save(buf, "JPEG", quality=78)
            path.write_bytes(buf.getvalue())
        await run_in_threadpool(work)
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"})


async def share_page(request: Request):
    from . import seo
    token = request.path_params["token"]
    r, owner = _shared(token)
    if not r or owner["banned"]:
        return HTMLResponse(seo.not_found_html(), status_code=404)
    hit(request)
    return HTMLResponse(seo.share_html(r, token), headers={"Cache-Control": "no-cache"})


def routes():
    return [
        Route("/api/referral", referral_info),
        Route("/api/reviews", reviews_public), Route("/api/reviews", review_submit, methods=["POST"]), Route("/api/reviews/mine", my_review),
        Route("/api/public-stats", public_stats),
        Route("/api/qrs/{qid:int}/share", share_create, methods=["POST"]), Route("/api/qrs/{qid:int}/share", share_delete, methods=["DELETE"]),
        Route("/api/p/{token}.jpg", share_image), Route("/p/{token}", share_page),
    ]
