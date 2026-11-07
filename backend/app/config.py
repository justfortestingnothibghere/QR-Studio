"""Settings = backend/config.json, overridden by environment variables (so secrets never live in the repo).

Friendly variable names (set these in Railway -> Variables):
  PUBLIC_URL            https://qr.yourdomain.com   (falls back to Railway's generated domain)
  UPI_ID                the UPI ID that receives the money
  PAYEE_NAME            name shown in the UPI app
  PAYMENT_MODE          live (default on a public site) | mock (local testing only)
  GMAIL_USER            Gmail that receives the Fam emails
  GMAIL_APP_PASSWORD    Gmail App Password (16 letters)  -> turns the mailbox reader on
  FAM_SENDER_DOMAINS    famapp.in                         (comma separated)
  ADMIN_EMAILS          you@example.com                   (comma separated)
  DATA_DIR              /data                              (the Railway Volume mount path)
  SECRET_KEY            optional; if missing one is created once and kept in DATA_DIR
  SITE_NAME, OWNER, SUPPORT_EMAIL, SUPPORT_TELEGRAM        shown on the website
Any other setting: QS__section__key=value   e.g. QS__pricing__base=39 or QS__limits__rate__preview_per_min=60
"""
import json
import os
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # backend/
ROOT = BASE.parent                                      # project root
CONFIG_PATH = Path(os.environ.get("QS_CONFIG", BASE / "config.json"))

_cfg: dict = {}
WARNINGS: list = []


def _put(path: str, value):
    cur = _cfg
    parts = path.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _csv(v: str):
    return [x.strip() for x in v.split(",") if x.strip()]


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _apply_env():
    e = os.environ
    on_platform = any(k.startswith("RAILWAY_") for k in e) or bool(e.get("PORT"))
    if e.get("PORT"):
        _put("server.port", int(e["PORT"]))
        _put("server.host", "0.0.0.0")
    pub = (e.get("PUBLIC_URL") or "").strip().rstrip("/")
    if not pub and e.get("RAILWAY_PUBLIC_DOMAIN"):
        pub = "https://" + e["RAILWAY_PUBLIC_DOMAIN"].strip()
    if pub:
        if not pub.startswith("http"):
            pub = "https://" + pub
        _put("server.public_url", pub)
        _put("security.allowed_origins", [pub])
        if pub.startswith("https://"):
            _put("security.cookie_secure", True)
    if e.get("DATA_DIR"):
        _put("storage.data_dir", e["DATA_DIR"])
    elif e.get("RAILWAY_VOLUME_MOUNT_PATH"):
        _put("storage.data_dir", e["RAILWAY_VOLUME_MOUNT_PATH"])  # set by Railway when a Volume is attached
    if e.get("SECRET_KEY"):
        _put("security.secret_key", e["SECRET_KEY"])
    if e.get("UPI_ID"):
        _put("payments.upi_id", e["UPI_ID"].strip())
    if e.get("PAYEE_NAME"):
        _put("payments.payee_name", e["PAYEE_NAME"].strip())
    if e.get("PAYMENT_MODE"):
        _put("payments.mode", e["PAYMENT_MODE"].strip().lower())
    if e.get("GMAIL_USER"):
        _put("payments.imap.user", e["GMAIL_USER"].strip())
    if e.get("GMAIL_APP_PASSWORD"):
        _put("payments.imap.app_password", e["GMAIL_APP_PASSWORD"].strip())
        if e.get("IMAP_ENABLED", "1") != "0":
            _put("payments.imap.enabled", True)
    if e.get("FAM_SENDER_DOMAINS"):
        _put("payments.imap.allowed_senders", _csv(e["FAM_SENDER_DOMAINS"]))
    if e.get("REQUIRE_DKIM"):
        _put("payments.imap.require_dkim", _truthy(e["REQUIRE_DKIM"]))
    if e.get("SITE_URL"):
        _put("server.site_url", e["SITE_URL"].strip().rstrip("/"))
    if e.get("TELEGRAM_BOT_TOKEN"):
        _put("notify.telegram_token", e["TELEGRAM_BOT_TOKEN"].strip())
    if e.get("TELEGRAM_CHAT_ID"):
        _put("notify.telegram_chat_id", e["TELEGRAM_CHAT_ID"].strip())
    if e.get("GOOGLE_SITE_VERIFICATION"):
        _put("seo.google_verification", e["GOOGLE_SITE_VERIFICATION"].strip())
    if e.get("BING_SITE_VERIFICATION"):
        _put("seo.bing_verification", e["BING_SITE_VERIFICATION"].strip())
    if e.get("ADMIN_EMAILS"):
        _put("admin.emails", _csv(e["ADMIN_EMAILS"]))
    if e.get("SIGNUP_OPEN"):
        _put("security.signup_open", _truthy(e["SIGNUP_OPEN"]))
    # behind Railway's proxy the client IP is in X-Forwarded-For
    if e.get("TRUST_PROXY") is not None:
        _put("server.trust_proxy_headers", _truthy(e["TRUST_PROXY"]))
    elif on_platform:
        _put("server.trust_proxy_headers", True)
    if e.get("PROXY_HOPS"):
        _put("server.proxy_hops", int(e["PROXY_HOPS"]))
    for k, v in e.items():  # generic QS__a__b__c=value
        if k.startswith("QS__"):
            try:
                val = json.loads(v)
            except ValueError:
                val = v
            _put(".".join(k[4:].lower().split("__")), val)
    return on_platform


def _safety(on_platform: bool):
    """Mock mode lets anyone unlock downloads for free. Never allow it on a public site."""
    pub = _cfg.get("server", {}).get("public_url", "")
    local = pub.startswith("http://localhost") or pub.startswith("http://127.0.0.1")
    if _cfg.get("payments", {}).get("mode") == "mock" and (on_platform or not local) and not _truthy(os.environ.get("ALLOW_MOCK", "0")):
        _put("payments.mode", "live")
        WARNINGS.append("PAYMENT_MODE=mock is not allowed on a public site, switched to live.")
    p = _cfg.get("payments", {})
    if p.get("mode") == "live":
        up = p.get("upi_id", "")
        if not up or up.startswith("yourupi"):
            WARNINGS.append("UPI_ID is not set: paid orders are disabled until you set it.")
        imap = p.get("imap", {})
        if not (imap.get("enabled") and imap.get("app_password")):
            WARNINGS.append("Gmail reader is off (set GMAIL_USER and GMAIL_APP_PASSWORD). Payments will only match what you add by hand in /admin.")
    if on_platform and not os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") and not os.environ.get("DATA_DIR"):
        WARNINGS.append("No Volume attached: your database and uploads are lost on every redeploy. Attach a Volume to this service.")
    if not _cfg.get("admin", {}).get("emails"):
        WARNINGS.append("ADMIN_EMAILS is empty: nobody can open /admin.")


def load() -> dict:
    global _cfg
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _cfg = json.load(f)
    _safety(_apply_env())
    sec = _cfg.setdefault("security", {})
    if not sec.get("secret_key") or str(sec["secret_key"]).startswith("CHANGE_ME"):
        keyfile = data_dir() / ".secret_key"           # lives in the data volume, so it survives redeploys
        if keyfile.exists() and keyfile.read_text().strip():
            sec["secret_key"] = keyfile.read_text().strip()
        else:
            sec["secret_key"] = secrets.token_hex(32)
            keyfile.write_text(sec["secret_key"])
            try:
                keyfile.chmod(0o600)
            except OSError:
                pass
    return _cfg


def get(path: str, default=None):
    cur = _cfg
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def data_dir() -> Path:
    p = Path(get("storage.data_dir", "data"))
    p = p if p.is_absolute() else BASE / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def site_url() -> str:
    """Public address used in canonical links, sitemap and share cards. SITE_URL, else PUBLIC_URL when it is a real domain, else qr.teamdev.sbs."""
    explicit = (get("server.site_url") or "").rstrip("/")
    if explicit:
        return explicit
    pub = (get("server.public_url") or "").rstrip("/")
    if pub.startswith("https://") and "railway.app" not in pub and "localhost" not in pub:
        return pub
    return "https://qr.teamdev.sbs"


def frontend_dir() -> Path:
    p = Path(get("server.frontend_dir", "../frontend"))
    return p if p.is_absolute() else (BASE / p).resolve()


def themes_dir() -> Path:
    """Built-in theme art ships with the code (backend/assets/themes), NOT in the data volume."""
    return BASE / "assets" / "themes"


load()
