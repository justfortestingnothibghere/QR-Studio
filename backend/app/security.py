"""Passwords (scrypt), sessions, CSRF, origin checks, rate limiting. Standard library only."""
import hashlib
import hmac
import re
import secrets
import time

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import config, db

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        self.status, self.message, self.extra = status, message, extra


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return "s1$" + salt.hex() + "$" + h.hex()


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


_DUMMY = None


def burn_time():
    """Spend roughly the same time as a real check so unknown emails cannot be told apart by timing."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("dummy-password")
    check_password("x", _DUMMY)


def _th(token: str) -> str:
    return hashlib.sha256((config.get("security.secret_key") + token).encode()).hexdigest()


def client_ip(request: Request) -> str:
    if config.get("server.trust_proxy_headers"):
        h = request.headers.get(config.get("server.client_ip_header", "X-Forwarded-For"), "")
        parts = [x.strip() for x in h.split(",") if x.strip()]
        if parts:
            # the left side of X-Forwarded-For can be forged by the visitor; trust only what our own proxy(s) appended
            hops = max(1, int(config.get("server.proxy_hops", 1)))
            return parts[-hops if len(parts) >= hops else 0][:64]
    return (request.client.host if request.client else "0.0.0.0")[:64]


# ---------- rate limiting (SQLite, so every worker process shares the same counters) ----------
def rate_limit(bucket: str, key: str, limit: int, window: int):
    k = bucket + "|" + key
    now = time.time()
    with db.tx() as c:
        c.execute("DELETE FROM rl WHERE k=? AND ts<?", (k, now - window))
        rows = c.execute("SELECT ts FROM rl WHERE k=? ORDER BY ts", (k,)).fetchall()
        if len(rows) >= limit:
            retry = int(window - (now - rows[0]["ts"])) + 1
            raise ApiError(429, "Too many attempts. Try again in %d s." % retry, retry_after=retry)
        c.execute("INSERT INTO rl(k,ts) VALUES(?,?)", (k, now))


# ---------- sessions ----------
def create_session(request: Request, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    days = int(config.get("security.session_days", 30))
    t = time.time()
    db.run("INSERT INTO sessions(token_hash,user_id,csrf,created,expires,ip,ua) VALUES(?,?,?,?,?,?,?)",
           (_th(token), user_id, secrets.token_urlsafe(24), t, t + days * 86400, client_ip(request),
            (request.headers.get("user-agent") or "")[:200]))
    return token


def set_cookie(resp: Response, token: str):
    days = int(config.get("security.session_days", 30))
    resp.set_cookie(config.get("security.cookie_name", "qs_session"), token, max_age=days * 86400, httponly=True,
                    samesite="lax", secure=bool(config.get("security.cookie_secure")), path="/")


def clear_cookie(resp: Response):
    resp.delete_cookie(config.get("security.cookie_name", "qs_session"), path="/")


def current(request: Request):
    """Returns (user, session) or (None, None). Cached on the request."""
    if hasattr(request.state, "auth"):
        return request.state.auth
    res = (None, None)
    tok = request.cookies.get(config.get("security.cookie_name", "qs_session"))
    if tok:
        s = db.one("SELECT * FROM sessions WHERE token_hash=? AND expires>?", (_th(tok), time.time()))
        if s:
            u = db.one("SELECT * FROM users WHERE id=?", (s["user_id"],))
            if u and not u["banned"]:
                res = (u, s)
    request.state.auth = res
    return res


def destroy_session(request: Request):
    tok = request.cookies.get(config.get("security.cookie_name", "qs_session"))
    if tok:
        db.run("DELETE FROM sessions WHERE token_hash=?", (_th(tok),))


def require_user(request: Request, csrf: bool = True, admin: bool = False):
    u, s = current(request)
    if not u:
        raise ApiError(401, "Please log in")
    if csrf and request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not hmac.compare_digest(sent, s["csrf"]):
            raise ApiError(403, "Session check failed. Refresh the page and try again.")
    if admin and not (u["is_admin"] or u["email"].lower() in [e.lower() for e in config.get("admin.emails", [])]):
        raise ApiError(403, "Admins only")
    return u


def origin_ok(request: Request) -> bool:
    """Blocks cross-site POST/PUT/DELETE. Same-origin requests carry an Origin (or Referer) matching our Host."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    org = request.headers.get("origin") or request.headers.get("referer")
    if not org:
        return False
    m = re.match(r"^(https?://[^/]+)", org)
    if not m:
        return False
    o = m.group(1).lower()
    host = (request.headers.get("host") or "").lower()
    allowed = [a.lower().rstrip("/") for a in config.get("security.allowed_origins", [])]
    pub = (config.get("server.public_url") or "").lower().rstrip("/")
    return o.split("://", 1)[1] == host or o in allowed or o == pub


def valid_email(e: str) -> bool:
    return bool(EMAIL_RE.match(e))


def json_error(e: ApiError) -> JSONResponse:
    h = {"Retry-After": str(e.extra["retry_after"])} if "retry_after" in e.extra else {}
    return JSONResponse({"error": e.message, **{k: v for k, v in e.extra.items() if k != "retry_after"}}, status_code=e.status, headers=h)
