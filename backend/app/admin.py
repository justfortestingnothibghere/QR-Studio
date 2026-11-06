"""Admin API: overview, orders (mark paid / unpaid), payments, users, QRs, payment test, backup + restore, audit log, settings."""
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route

from . import config, db, security
from .payments import fam, orders
from .security import ApiError, require_user
from .util import body, ok

STARTED = time.time()
PER = 25
ORDER_STATES = ("pending", "paid", "unpaid", "expired")
REQUIRED_TABLES = {"users", "orders", "payments", "qrs"}


def _admin(request: Request, csrf: bool = True):
    return require_user(request, csrf=csrf, admin=True)


def _who(u) -> str:
    return "admin:" + u["email"]


def _page(request: Request):
    try:
        p = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        p = 1
    return p, (p - 1) * PER


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _log(u, kind, ref="", detail="", request=None):
    db.log_event(_who(u), kind, ref, security.client_ip(request) if request else "", detail)


# ---------------------------------------------------------------- overview
async def stats(request: Request):
    _admin(request, csrf=False)
    t = time.time()
    off = 19800  # IST day buckets
    today = int((t + off) // 86400)

    def series(sql, args=()):
        got = {int(r["d"]): r["v"] for r in db.many(sql, args)}
        return [{"day": time.strftime("%d %b", time.gmtime((d * 86400))), "v": got.get(d, 0)} for d in range(today - 13, today + 1)]
    since = (today - 13) * 86400 - off
    rev = series("SELECT CAST((paid_at+19800)/86400 AS INT) d, SUM(rupees) v FROM orders WHERE status='paid' AND kind!='test' AND paid_at>? GROUP BY d", (since,))
    sign = series("SELECT CAST((created+19800)/86400 AS INT) d, COUNT(*) v FROM users WHERE created>? GROUP BY d", (since,))
    one = lambda sql, a=(): db.one(sql, a)["n"]  # noqa: E731
    s = {
        "users": one("SELECT COUNT(*) n FROM users"),
        "new_today": one("SELECT COUNT(*) n FROM users WHERE created>?", (today * 86400 - off,)),
        "qrs": one("SELECT COUNT(*) n FROM qrs"),
        "scans": one("SELECT COALESCE(SUM(scans),0) n FROM qrs"),
        "paid_orders": one("SELECT COUNT(*) n FROM orders WHERE status='paid' AND rupees>0 AND kind!='test'"),
        "revenue": one("SELECT COALESCE(SUM(rupees),0) n FROM orders WHERE status='paid' AND kind!='test'"),
        "revenue_today": one("SELECT COALESCE(SUM(rupees),0) n FROM orders WHERE status='paid' AND kind!='test' AND paid_at>?", (today * 86400 - off,)),
        "revenue_7d": one("SELECT COALESCE(SUM(rupees),0) n FROM orders WHERE status='paid' AND kind!='test' AND paid_at>?", (t - 7 * 86400,)),
        "revenue_30d": one("SELECT COALESCE(SUM(rupees),0) n FROM orders WHERE status='paid' AND kind!='test' AND paid_at>?", (t - 30 * 86400,)),
        "pending": one("SELECT COUNT(*) n FROM orders WHERE status='pending' AND expires>? AND kind!='test'", (t,)),
        "active_pass": one("SELECT COUNT(*) n FROM users WHERE pass_until>?", (t,)),
        "unclaimed_payments": one("SELECT COUNT(*) n FROM payments WHERE claimed_by IS NULL"),
        "downloads": one("SELECT COUNT(*) n FROM downloads"),
        "failed_verifies_24h": one("SELECT COUNT(*) n FROM events WHERE kind='verify_fail' AND ts>?", (t - 86400,)),
        "imap": fam.status(), "mode": config.get("payments.mode"),
        "warnings": list(config.WARNINGS),
    }
    top = db.many("SELECT theme_id, COUNT(*) n FROM qrs GROUP BY theme_id ORDER BY n DESC LIMIT 6")
    by_status = db.many("SELECT status, COUNT(*) n FROM orders WHERE kind!='test' GROUP BY status")
    return ok({"stats": s, "revenue_series": rev, "signup_series": sign, "top_themes": top, "order_status": by_status})


# ---------------------------------------------------------------- orders
async def orders_list(request: Request):
    _admin(request, csrf=False)
    q = (request.query_params.get("q") or "").strip()[:60]
    st = request.query_params.get("status", "")
    kind = request.query_params.get("kind", "")
    where, args = ["1=1"], []
    if st in ORDER_STATES:
        where.append("o.status=?"); args.append(st)
    if kind in ("export", "pass", "test"):
        where.append("o.kind=?"); args.append(kind)
    if q:
        where.append("(o.id LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\' OR o.utr LIKE ? ESCAPE '\\' OR CAST(o.amount_paise AS TEXT) LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 4
    p, off = _page(request)
    base = "FROM orders o JOIN users u ON u.id=o.user_id WHERE " + " AND ".join(where)
    total = db.one("SELECT COUNT(*) n " + base, args)["n"]
    rows = db.many("SELECT o.id,o.kind,o.status,o.rupees,o.amount_paise,o.created,o.expires,o.paid_at,o.utr,o.label,u.email,u.id uid " + base +
                   " ORDER BY o.created DESC LIMIT ? OFFSET ?", args + [PER, off])
    return ok({"orders": rows, "total": total, "page": p, "per": PER})


async def order_detail(request: Request):
    _admin(request, csrf=False)
    oid = request.path_params["oid"]
    o = db.one("SELECT o.*,u.email FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=?", (oid,))
    if not o:
        raise ApiError(404, "Order not found")
    o["snapshot"] = None
    pay = db.one("SELECT utr,txn_id,amount_paise,received_at,payer,source FROM payments WHERE claimed_by=?", (oid,))
    ev = db.many("SELECT ts,actor,kind,ip,detail FROM events WHERE ref=? ORDER BY ts", (oid,))
    dl = db.many("SELECT fmt,ts FROM downloads WHERE order_id=? ORDER BY ts DESC LIMIT 20", (oid,))
    return ok({"order": o, "payment": pay, "events": ev, "downloads": dl})


async def order_status(request: Request):
    """Mark an order paid or unpaid by hand. paid applies what was bought; unpaid takes it back."""
    u = _admin(request)
    oid = request.path_params["oid"]
    d = await body(request, 2000)
    want = str(d.get("status", ""))
    note = str(d.get("note", ""))[:200]
    ref = re.sub(r"\s", "", str(d.get("utr", "")))[:40].upper()
    if want not in ("paid", "unpaid"):
        raise ApiError(400, "Status must be paid or unpaid")
    with db.tx() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            raise ApiError(404, "Order not found")
        snap = json.loads(o["snapshot"] or "{}")
        if want == "paid":
            if o["status"] == "paid":
                raise ApiError(409, "Already paid")
            used = "ADMIN"
            if ref:
                p = c.execute("SELECT * FROM payments WHERE utr=? OR (txn_id<>'' AND txn_id=?)", (ref, ref)).fetchone()
                if p:
                    if p["claimed_by"] and p["claimed_by"] != oid:
                        raise ApiError(409, "That payment is already used by order %s" % p["claimed_by"])
                    c.execute("UPDATE payments SET claimed_by=? WHERE utr=?", (oid, p["utr"]))
                    used = p["utr"]
                else:
                    used = ref
            c.execute("UPDATE orders SET status='paid', paid_at=?, utr=? WHERE id=?", (time.time(), used, oid))
            if o["kind"] == "pass":
                days = int(config.get("pricing.pass_days", 30))
                us = c.execute("SELECT pass_until FROM users WHERE id=?", (o["user_id"],)).fetchone()
                c.execute("UPDATE users SET pass_until=? WHERE id=?", (max(time.time(), us["pass_until"] or 0) + days * 86400, o["user_id"]))
            elif snap.get("dynamic") and o["qr_id"]:
                c.execute("UPDATE qrs SET dyn_active=1 WHERE id=?", (o["qr_id"],))
        else:
            if o["status"] == "unpaid":
                raise ApiError(409, "Already unpaid")
            was_paid = o["status"] == "paid"
            c.execute("UPDATE orders SET status='unpaid', paid_at=NULL WHERE id=?", (oid,))
            c.execute("UPDATE payments SET claimed_by=NULL WHERE claimed_by=?", (oid,))   # the payment can be matched again
            if was_paid and o["kind"] == "pass":
                days = int(config.get("pricing.pass_days", 30))
                us = c.execute("SELECT pass_until FROM users WHERE id=?", (o["user_id"],)).fetchone()
                c.execute("UPDATE users SET pass_until=? WHERE id=?", (max(0, (us["pass_until"] or 0) - days * 86400), o["user_id"]))
            elif was_paid and snap.get("dynamic") and o["qr_id"]:
                if not c.execute("SELECT 1 FROM orders WHERE qr_id=? AND status='paid' AND id!=?", (o["qr_id"], oid)).fetchone():
                    c.execute("UPDATE qrs SET dyn_active=0 WHERE id=?", (o["qr_id"],))
        c.execute("INSERT INTO events(ts,actor,kind,ref,ip,detail) VALUES(?,?,?,?,?,?)",
                  (time.time(), _who(u), "order_" + want, oid, security.client_ip(request), ("was %s. %s" % (o["status"], note)).strip()))
    return ok()


async def test_order(request: Request):
    """Payment flow check: a real order row with any amount, paid and verified through the exact same UTR path as customers."""
    u = _admin(request)
    d = await body(request, 500)
    try:
        paise = int(round(float(d.get("amount", 0)) * 100))
    except (TypeError, ValueError):
        raise ApiError(400, "Amount must be a number")
    o = orders.create_test_order(u["id"], paise)
    _log(u, "test_order", o["id"], "%.2f INR" % (paise / 100), request)
    row = db.one("SELECT * FROM orders WHERE id=?", (o["id"],))
    from .main import order_public
    out = order_public(row)
    out["upi_link"] = orders.upi_link(row)
    out["payee"] = config.get("payments.upi_id")
    return ok({"order": out})


async def mailbox_poll(request: Request):
    u = _admin(request)
    cfg = config.get("payments.imap", {})
    if not (cfg.get("enabled") and cfg.get("app_password")):
        raise ApiError(400, "The mailbox reader is off. Set GMAIL_USER and GMAIL_APP_PASSWORD in Railway Variables.")
    try:
        n = await run_in_threadpool(fam.poll_once)
    except Exception as e:
        fam._status["last_error"] = str(e)[:200]
        fam._save_status()
        raise ApiError(502, "Mailbox check failed: %s" % str(e)[:160])
    _log(u, "mailbox_poll", "", "%d new" % n, request)
    return ok({"new": n, "imap": fam.status()})


# ---------------------------------------------------------------- payments
async def payments_list(request: Request):
    _admin(request, csrf=False)
    q = (request.query_params.get("q") or "").strip()[:60]
    only = request.query_params.get("only", "")
    where, args = ["1=1"], []
    if only == "unclaimed":
        where.append("claimed_by IS NULL")
    if q:
        where.append("(utr LIKE ? ESCAPE '\\' OR txn_id LIKE ? ESCAPE '\\' OR payer LIKE ? ESCAPE '\\' OR CAST(amount_paise AS TEXT) LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 4
    p, off = _page(request)
    w = " AND ".join(where)
    total = db.one("SELECT COUNT(*) n FROM payments WHERE " + w, args)["n"]
    rows = db.many("SELECT utr,txn_id,amount_paise,received_at,payer,source,claimed_by FROM payments WHERE " + w + " ORDER BY received_at DESC LIMIT ? OFFSET ?", args + [PER, off])
    return ok({"payments": rows, "total": total, "page": p, "per": PER})


async def payment_add(request: Request):
    u = _admin(request)
    d = await body(request, 2000)
    ref = re.sub(r"\s", "", str(d.get("utr", ""))).upper()
    try:
        paise = int(round(float(d.get("amount", 0)) * 100))
    except (TypeError, ValueError):
        raise ApiError(400, "Amount must be a number")
    if not re.fullmatch(r"[A-Z0-9]{8,40}", ref) or paise <= 0:
        raise ApiError(400, "Need the UTR or Transaction ID (8 to 40 letters/digits) and a positive amount")
    info = {"utr": ref, "real_utr": ref if ref.isdigit() else "", "txn_id": "" if ref.isdigit() else ref, "amount_paise": paise, "received_at": time.time(), "payer": "manual"}
    if not fam.store_payment(info, "admin"):
        raise ApiError(409, "This reference is already recorded")
    _log(u, "payment_add", ref, "%.2f INR" % (paise / 100), request)
    return ok()


async def payment_delete(request: Request):
    u = _admin(request)
    ref = request.path_params["ref"]
    _, n = db.run("DELETE FROM payments WHERE utr=? AND claimed_by IS NULL", (ref,))
    if not n:
        raise ApiError(409, "Only unclaimed payments can be deleted")
    _log(u, "payment_delete", ref, "", request)
    return ok()


# ---------------------------------------------------------------- users
async def users_list(request: Request):
    _admin(request, csrf=False)
    q = (request.query_params.get("q") or "").strip()[:60]
    where, args = ["1=1"], []
    if q:
        where.append("(email LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 2
    p, off = _page(request)
    w = " AND ".join(where)
    total = db.one("SELECT COUNT(*) n FROM users WHERE " + w, args)["n"]
    rows = db.many("SELECT u.id,u.email,u.name,u.created,u.banned,u.pass_until,u.is_admin,"
                   "(SELECT COUNT(*) FROM qrs WHERE user_id=u.id) qrs,"
                   "(SELECT COUNT(*) FROM orders WHERE user_id=u.id AND status='paid' AND kind!='test' AND rupees>0) paid_orders,"
                   "(SELECT COALESCE(SUM(rupees),0) FROM orders WHERE user_id=u.id AND status='paid' AND kind!='test') spent "
                   "FROM users u WHERE " + w + " ORDER BY u.created DESC LIMIT ? OFFSET ?", args + [PER, off])
    return ok({"users": rows, "total": total, "page": p, "per": PER})


async def user_ban(request: Request):
    me = _admin(request)
    uid = int(request.path_params["uid"])
    if uid == me["id"]:
        raise ApiError(400, "You cannot ban yourself")
    d = await body(request, 500)
    ban = 1 if d.get("banned") else 0
    db.run("UPDATE users SET banned=? WHERE id=?", (ban, uid))
    if ban:
        db.run("DELETE FROM sessions WHERE user_id=?", (uid,))
    _log(me, "user_ban" if ban else "user_unban", str(uid), "", request)
    return ok()


async def user_pass(request: Request):
    me = _admin(request)
    uid = int(request.path_params["uid"])
    d = await body(request, 500)
    u = db.one("SELECT pass_until FROM users WHERE id=?", (uid,))
    if not u:
        raise ApiError(404, "User not found")
    if d.get("revoke"):
        new = 0
    else:
        try:
            days = int(d.get("days", 0))
        except (TypeError, ValueError):
            raise ApiError(400, "Days must be a number")
        if not -3650 <= days <= 3650 or days == 0:
            raise ApiError(400, "Days must be between -3650 and 3650, not zero")
        new = max(time.time(), u["pass_until"] or 0) + days * 86400 if days > 0 else max(0, (u["pass_until"] or 0) + days * 86400)
        if new < time.time():
            new = 0
    db.run("UPDATE users SET pass_until=? WHERE id=?", (new, uid))
    _log(me, "user_pass", str(uid), "revoke" if d.get("revoke") else "%+d days" % int(d.get("days", 0)), request)
    return ok({"pass_until": new})


async def user_password(request: Request):
    me = _admin(request)
    uid = int(request.path_params["uid"])
    d = await body(request, 500)
    pw = str(d.get("password", ""))
    if len(pw) < int(config.get("security.password_min_length", 8)) or len(pw) > 200:
        raise ApiError(400, "Password needs at least %d characters" % config.get("security.password_min_length", 8))
    if not db.one("SELECT 1 FROM users WHERE id=?", (uid,)):
        raise ApiError(404, "User not found")
    db.run("UPDATE users SET pw_hash=? WHERE id=?", (security.hash_password(pw), uid))
    db.run("DELETE FROM sessions WHERE user_id=?", (uid,))
    _log(me, "user_password", str(uid), "", request)
    return ok()


# ---------------------------------------------------------------- QRs
async def qrs_list(request: Request):
    _admin(request, csrf=False)
    q = (request.query_params.get("q") or "").strip()[:60]
    where, args = ["1=1"], []
    if q:
        where.append("(r.title LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\' OR r.slug LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 3
    p, off = _page(request)
    base = "FROM qrs r JOIN users u ON u.id=r.user_id WHERE " + " AND ".join(where)
    total = db.one("SELECT COUNT(*) n " + base, args)["n"]
    rows = db.many("SELECT r.id,r.title,r.theme_id,r.created,r.updated,r.slug,r.dyn_active,r.scans,u.email,json_extract(r.design,'$.kind') kind " + base + " ORDER BY r.updated DESC LIMIT ? OFFSET ?", args + [PER, off])
    return ok({"qrs": rows, "total": total, "page": p, "per": PER})


async def qr_delete(request: Request):
    me = _admin(request)
    qid = int(request.path_params["qid"])
    _, n = db.run("DELETE FROM qrs WHERE id=?", (qid,))
    if not n:
        raise ApiError(404, "QR not found")
    _log(me, "qr_delete", str(qid), "", request)
    return ok()


# ---------------------------------------------------------------- audit log + settings + system
async def events_list(request: Request):
    _admin(request, csrf=False)
    kind = (request.query_params.get("kind") or "")[:40]
    q = (request.query_params.get("q") or "").strip()[:60]
    where, args = ["1=1"], []
    if kind == "security":
        where.append("kind IN ('verify_fail','auto_ambiguous','login_fail','order_denied')")
    elif kind == "admin":
        where.append("actor LIKE 'admin:%'")
    elif kind == "payment":
        where.append("kind IN ('payment_in','order_paid','auto_ambiguous')")
    if q:
        where.append("(ref LIKE ? ESCAPE '\\' OR actor LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\' OR ip LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 4
    p, off = _page(request)
    w = " AND ".join(where)
    total = db.one("SELECT COUNT(*) n FROM events WHERE " + w, args)["n"]
    rows = db.many("SELECT ts,actor,kind,ref,ip,detail FROM events WHERE " + w + " ORDER BY id DESC LIMIT ? OFFSET ?", args + [PER, off])
    return ok({"events": rows, "total": total, "page": p, "per": PER})


def meta_get(k, default=""):
    r = db.one("SELECT v FROM meta WHERE k=?", (k,))
    return r["v"] if r else default


def meta_set(k, v):
    db.run("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


async def settings_get(request: Request):
    _admin(request, csrf=False)
    return ok({"announcement": meta_get("announcement"), "announcement_kind": meta_get("announcement_kind", "info"),
               "signups_open": meta_get("signups_closed", "0") != "1"})


async def settings_set(request: Request):
    u = _admin(request)
    d = await body(request, 2000)
    ann = str(d.get("announcement", "")).strip()[:200]
    kind = d.get("announcement_kind") if d.get("announcement_kind") in ("info", "warn") else "info"
    meta_set("announcement", ann)
    meta_set("announcement_kind", kind)
    meta_set("signups_closed", "0" if d.get("signups_open", True) else "1")
    _log(u, "settings", "", "announcement=%r signups_open=%s" % (ann[:60], bool(d.get("signups_open", True))), request)
    return ok()


def _dir_size(p: Path) -> int:
    t = 0
    if p.exists():
        for root, _, files in os.walk(p):
            for f in files:
                try:
                    t += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return t


async def system_info(request: Request):
    _admin(request, csrf=False)
    dd = config.data_dir()
    dbf = dd / config.get("storage.database", "qrstudio.db")
    pay = config.get("payments", {})
    up = pay.get("upi_id", "")
    snaps = sorted((x.name, x.stat().st_size) for x in (dd / "backups").glob("*.db")) if (dd / "backups").exists() else []
    info = {
        "python": sys.version.split()[0], "platform": platform.platform(), "uptime": time.time() - STARTED,
        "public_url": config.get("server.public_url"), "data_dir": str(dd), "volume": bool(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or os.environ.get("DATA_DIR")),
        "db_bytes": dbf.stat().st_size if dbf.exists() else 0,
        "logos_bytes": _dir_size(dd / "logos"), "themes_bytes": _dir_size(dd / "user_themes"), "exports_bytes": _dir_size(dd / "exports"), "cache_bytes": _dir_size(dd / "cache"),
        "mode": pay.get("mode"), "upi_id": (up[:2] + "…" + up[up.find("@"):]) if "@" in up else up, "payee": pay.get("payee_name"), "upi_ready": bool(up) and not up.startswith("yourupi") and "@" in up,
        "gmail_user": pay.get("imap", {}).get("user"), "gmail_enabled": bool(pay.get("imap", {}).get("enabled")),
        "sender_domains": pay.get("imap", {}).get("allowed_senders"), "require_dkim": pay.get("imap", {}).get("require_dkim"),
        "order_expiry_minutes": pay.get("order_expiry_minutes"), "pricing": config.get("pricing"), "admin_emails": config.get("admin.emails"),
        "workers": os.environ.get("WEB_CONCURRENCY", "1"), "snapshots": [{"name": n, "bytes": b} for n, b in snaps[-10:]],
    }
    return ok({"system": info})


async def clear_cache(request: Request):
    u = _admin(request)
    dd = config.data_dir()
    for k in ("exports", "cache"):
        shutil.rmtree(dd / k, ignore_errors=True)
    _log(u, "clear_cache", "", "exports + thumbnails (rebuilt on demand)", request)
    return ok()


# ---------------------------------------------------------------- backup + restore
def _snapshot_db(dest: Path, strip_sessions: bool = True):
    src = db.connect()
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        if strip_sessions:
            dst.execute("DELETE FROM sessions")
            dst.execute("DELETE FROM rl")
            dst.commit()
            dst.execute("VACUUM")
    finally:
        dst.close()
        src.close()


def build_backup(tmpdir: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M")
    out = tmpdir / ("qrstudio-backup-%s.zip" % stamp)
    snap = tmpdir / "qrstudio.db"
    _snapshot_db(snap)
    dd = config.data_dir()
    counts = {t: db.one("SELECT COUNT(*) n FROM %s" % t)["n"] for t in ("users", "qrs", "orders", "payments")}
    files = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(snap, "db/qrstudio.db")
        for sub in ("logos", "user_themes"):
            for root, _, names in os.walk(dd / sub):
                for n in names:
                    full = Path(root) / n
                    rel = full.relative_to(dd).as_posix()
                    if re.fullmatch(r"(logos|user_themes)/\d+/[A-Za-z0-9._-]+", rel):
                        z.write(full, rel, compress_type=zipfile.ZIP_STORED)
                        files += 1
        z.writestr("manifest.json", json.dumps({"app": "qrstudio", "format": 2, "created": time.time(), "counts": counts, "files": files}))
    snap.unlink(missing_ok=True)
    return out


async def backup(request: Request):
    u = _admin(request, csrf=False)
    tmp = Path(tempfile.mkdtemp(prefix="qsbk-"))
    path = await run_in_threadpool(build_backup, tmp)
    _log(u, "backup", "", "%d bytes" % path.stat().st_size, request)
    return FileResponse(path, media_type="application/zip", filename=path.name, headers={"Cache-Control": "no-store"},
                        background=BackgroundTask(shutil.rmtree, tmp, True))


def _safe_extract(zpath: Path, dest: Path):
    with zipfile.ZipFile(zpath) as z:
        infos = z.infolist()
        if len(infos) > 50000 or sum(i.file_size for i in infos) > 2 * 1024 ** 3:
            raise ApiError(400, "Backup is too large")
        names = {i.filename for i in infos}
        if "db/qrstudio.db" not in names:
            raise ApiError(400, "This zip is not a QR Studio backup (db/qrstudio.db missing)")
        for i in infos:
            n = i.filename
            if i.is_dir():
                continue
            if not (n == "manifest.json" or n == "db/qrstudio.db" or re.fullmatch(r"(logos|user_themes)/\d+/[A-Za-z0-9._-]+", n)):
                raise ApiError(400, "Unexpected file in backup: %s" % n[:60])
            target = (dest / n).resolve()
            if dest.resolve() not in target.parents:
                raise ApiError(400, "Unsafe path in backup")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def _validate_db(path: Path):
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ApiError(400, "The database inside the backup is damaged")
            have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            c.close()
    except sqlite3.DatabaseError:
        raise ApiError(400, "This file is not a valid QR Studio database")
    if not REQUIRED_TABLES <= have:
        raise ApiError(400, "This database is missing tables: %s" % ", ".join(sorted(REQUIRED_TABLES - have)))


def do_restore(upload: Path) -> dict:
    dd = config.data_dir()
    work = Path(tempfile.mkdtemp(prefix="qsrs-", dir=dd))
    try:
        with open(upload, "rb") as f:
            head = f.read(16)
        new_files = work / "new"
        new_files.mkdir()
        if head.startswith(b"SQLite format 3"):
            dbfile, has_files = upload, False
        elif zipfile.is_zipfile(upload):
            _safe_extract(upload, new_files)
            dbfile, has_files = new_files / "db" / "qrstudio.db", True
        else:
            raise ApiError(400, "Upload the .zip backup (or a .db file)")
        _validate_db(dbfile)
        # safety copy of what is live right now, so a wrong restore can be undone
        bk = dd / "backups"
        bk.mkdir(exist_ok=True)
        keep = bk / ("pre-restore-%s.db" % time.strftime("%Y%m%d-%H%M%S"))
        _snapshot_db(keep, strip_sessions=False)
        for old in sorted(bk.glob("pre-restore-*.db"))[:-3]:
            old.unlink(missing_ok=True)
        # replace the live database through SQLite's own backup API (safe while other workers are reading)
        src = sqlite3.connect("file:%s?mode=ro" % dbfile, uri=True)
        dst = db.connect()
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        db.init()                                    # adds tables/columns that an older backup does not have
        db.run("DELETE FROM sessions")               # sessions belong to the old data: everybody logs in again
        db.run("DELETE FROM rl")
        if has_files:
            for sub in ("logos", "user_themes"):
                live = dd / sub
                if live.exists():
                    shutil.move(str(live), str(work / ("old_" + sub)))
                if (new_files / sub).exists():
                    shutil.move(str(new_files / sub), str(live))
                else:
                    live.mkdir(exist_ok=True)
        shutil.rmtree(dd / "cache", ignore_errors=True)
        shutil.rmtree(dd / "exports", ignore_errors=True)
        counts = {t: db.one("SELECT COUNT(*) n FROM %s" % t)["n"] for t in ("users", "qrs", "orders", "payments")}
        return {"counts": counts, "files_restored": has_files, "safety_copy": keep.name}
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def restore(request: Request):
    u = _admin(request)
    form = await request.form(max_files=1, max_fields=5)
    pw = str(form.get("password") or "")
    if str(form.get("confirm") or "").strip() != "RESTORE":
        raise ApiError(400, 'Type RESTORE in the confirm box')
    if not security.check_password(pw, u["pw_hash"]):
        _log(u, "restore_denied", "", "wrong password", request)
        raise ApiError(403, "Wrong password")
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        raise ApiError(400, "Choose a backup file")
    tmp = Path(tempfile.mkdtemp(prefix="qsup-"))
    try:
        path = tmp / "upload.bin"
        size = 0
        with open(path, "wb") as out:
            while True:
                chunk = await f.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > 1024 ** 3:
                    raise ApiError(413, "Backup is larger than 1 GB")
                out.write(chunk)
        res = await run_in_threadpool(do_restore, path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _log(u, "restore", "", json.dumps(res["counts"]), request)
    return ok(res)


def auto_snapshot():
    """One database copy per day inside the data folder (last 7 kept). Protects against mistakes, not against losing the Volume."""
    dd = config.data_dir()
    bk = dd / "backups"
    bk.mkdir(exist_ok=True)
    f = bk / ("auto-%s.db" % time.strftime("%Y%m%d"))
    if not f.exists():
        tmp = f.with_suffix(".tmp")
        _snapshot_db(tmp)
        tmp.rename(f)
    for old in sorted(bk.glob("auto-*.db"))[:-7]:
        old.unlink(missing_ok=True)


def routes():
    P = "/api/admin"
    return [
        Route(P + "/stats", stats),
        Route(P + "/orders", orders_list), Route(P + "/orders/{oid}", order_detail), Route(P + "/orders/{oid}/status", order_status, methods=["POST"]),
        Route(P + "/test-order", test_order, methods=["POST"]), Route(P + "/mailbox/poll", mailbox_poll, methods=["POST"]),
        Route(P + "/payments", payments_list), Route(P + "/payments", payment_add, methods=["POST"]), Route(P + "/payments/{ref}", payment_delete, methods=["DELETE"]),
        Route(P + "/users", users_list), Route(P + "/users/{uid:int}/ban", user_ban, methods=["POST"]),
        Route(P + "/users/{uid:int}/pass", user_pass, methods=["POST"]), Route(P + "/users/{uid:int}/password", user_password, methods=["POST"]),
        Route(P + "/qrs", qrs_list), Route(P + "/qrs/{qid:int}", qr_delete, methods=["DELETE"]),
        Route(P + "/events", events_list), Route(P + "/settings", settings_get), Route(P + "/settings", settings_set, methods=["POST"]),
        Route(P + "/system", system_info), Route(P + "/system/clear-cache", clear_cache, methods=["POST"]),
        Route(P + "/backup", backup), Route(P + "/restore", restore, methods=["POST"]),
    ]
