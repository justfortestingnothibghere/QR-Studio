"""Parses Fampay "You have successfully received" emails and verifies they really came from Fam.

Layout of the real email (from the owner's screenshot):
  Hey <name>, You have successfully received ₹1.0 from <payer>
  Transaction ID: FMPIB...   Date: 01:17 AM IST, 04 November 2026   Updated Balance: ₹87.64   UTR: 845304841118
"""
import html
import imaplib
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime

from .. import config, db

IST = timezone(timedelta(hours=5, minutes=30))
AMT_RE = re.compile(r"received\s*(?:₹|rs\.?|inr|\ufffd+|\?)?\s*([\d,]+(?:\.\d{1,2})?)", re.I)
UTR_RE = re.compile(r"\bUTR\s*[:#\-]?\s*(\d{12})\b", re.I)
DATE_RE = re.compile(r"Date\s*[:\-]?\s*(\d{1,2}:\d{2}\s*[AP]M)\s*IST\s*,?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
FROM_RE = re.compile(r"received\s*(?:₹|rs\.?|inr|\ufffd+|\?)?\s*[\d,.]+\s*from\s+(.{1,60}?)\s*(?:Transaction|$)", re.I | re.S)


def _text_of(msg) -> str:
    parts = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct in ("text/plain", "text/html"):
            try:
                body = part.get_content()
            except Exception:
                continue
            if ct == "text/html":
                body = re.sub(r"(?is)<(script|style).*?</\1>", " ", body)
                body = re.sub(r"(?s)<[^>]+>", " ", body)
                body = html.unescape(body)
            parts.append(body)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def parse_text(text: str):
    """Returns dict(amount_paise, utr, received_at, payer) or None."""
    a, u = AMT_RE.search(text), UTR_RE.search(text)
    if not (a and u):
        return None
    try:
        paise = int((Decimal(a.group(1).replace(",", "")) * 100).to_integral_value())
    except InvalidOperation:
        return None
    ts = None
    d = DATE_RE.search(text)
    if d:
        try:
            ts = datetime.strptime(d.group(1).upper().replace(" ", "") + " " + " ".join(d.group(2).split()), "%I:%M%p %d %B %Y").replace(tzinfo=IST).timestamp()
        except ValueError:
            ts = None
    f = FROM_RE.search(text)
    return {"amount_paise": paise, "utr": u.group(1), "received_at": ts, "payer": (f.group(1).strip() if f else "")[:60]}


def _in(dom: str, allowed: str) -> bool:
    return dom == allowed or dom.endswith("." + allowed)


def sender_trusted(msg, cfg: dict) -> bool:
    """From domain must be on the allow list (exact or subdomain) and Gmail's OWN Authentication-Results header
    (authserv-id mx.google.com) must show DKIM pass for that same domain, or DMARC pass for the From domain.
    Authentication-Results headers written by the sender are ignored."""
    allowed = [s.lower().lstrip("@") for s in cfg.get("allowed_senders", []) if s]
    m = re.search(r"@([a-z0-9.\-]+)", (msg.get("From") or "").lower())
    dom = m.group(1) if m else ""
    match = next((a for a in allowed if _in(dom, a)), None)
    if not match:
        return False
    if not cfg.get("require_dkim", True):
        return True
    serv = (cfg.get("authserv_id") or "mx.google.com").lower()
    for ar in msg.get_all("Authentication-Results") or []:
        low = " ".join(str(ar).lower().split())
        if not (low.startswith(serv + ";") or low.startswith(serv + " ")):
            continue
        for d in re.findall(r"dkim=pass[^;]*?header\.(?:d|i)=@?([a-z0-9.\-]+)", low):
            if _in(d.lstrip("@"), match):
                return True
        mm = re.search(r"dmarc=pass[^;]*?header\.from=([a-z0-9.\-]+)", low)
        if mm and _in(mm.group(1), match):
            return True
    return False


def parse_message(raw: bytes, cfg: dict):
    msg = message_from_bytes(raw, policy=policy.default)
    if not sender_trusted(msg, cfg):
        return None, "untrusted sender or failed DKIM"
    info = parse_text(_text_of(msg))
    if not info:
        return None, "no payment found in email"
    if info["received_at"] is None:
        try:
            info["received_at"] = parsedate_to_datetime(msg["Date"]).timestamp()
        except Exception:
            info["received_at"] = time.time()
    return info, ""


def store_payment(info: dict, source: str) -> bool:
    """INSERT OR IGNORE keeps a replayed email from creating a second payment."""
    _, n = db.run("INSERT OR IGNORE INTO payments(utr,amount_paise,received_at,payer,source,claimed_by,created) VALUES(?,?,?,?,?,NULL,?)",
                  (info["utr"], info["amount_paise"], info["received_at"], info.get("payer", ""), source, time.time()))
    return n == 1


# ---------- IMAP poller ----------
_status = {"enabled": False, "last_ok": 0, "last_error": "", "seen": 0, "stored": 0, "rejected": 0}


def status():
    return dict(_status)


def poll_once() -> int:
    cfg = config.get("payments.imap", {})
    pw = (cfg.get("app_password") or "").replace(" ", "")
    if not (cfg.get("enabled") and pw):
        return 0
    stored = 0
    M = imaplib.IMAP4_SSL(cfg.get("host", "imap.gmail.com"), int(cfg.get("port", 993)), timeout=30)
    try:
        M.login(cfg["user"], pw)
        M.select(cfg.get("folder", "INBOX"), readonly=True)
        since = (datetime.now(timezone.utc) - timedelta(hours=int(cfg.get("lookback_hours", 24)))).strftime("%d-%b-%Y")
        typ, data = M.uid("SEARCH", None, "SINCE", since)
        uids = data[0].split() if typ == "OK" and data and data[0] else []
        last = db.one("SELECT v FROM meta WHERE k='imap_last_uid'")
        last_uid = int(last["v"]) if last else 0
        for uid in uids:
            if int(uid) <= last_uid:
                continue
            typ, msgdata = M.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not msgdata or not isinstance(msgdata[0], tuple):
                continue
            _status["seen"] += 1
            info, why = parse_message(msgdata[0][1], cfg)
            if info is None:
                if why != "no payment found in email":
                    _status["rejected"] += 1
                continue
            if store_payment(info, "email"):
                stored += 1
                _status["stored"] += 1
            last_uid = max(last_uid, int(uid))
        db.run("INSERT INTO meta(k,v) VALUES('imap_last_uid',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(last_uid),))
        _status.update(last_ok=time.time(), last_error="")
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return stored


def _loop():
    while True:
        cfg = config.get("payments.imap", {})
        _status["enabled"] = bool(cfg.get("enabled") and cfg.get("app_password"))
        try:
            poll_once()
        except Exception as e:  # keep polling through network blips
            _status["last_error"] = str(e)[:200]
        time.sleep(max(5, int(cfg.get("poll_seconds", 20))))


def start_poller():
    t = threading.Thread(target=_loop, name="fam-imap-poller", daemon=True)
    t.start()
    return t
