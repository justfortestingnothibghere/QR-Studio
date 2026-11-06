"""Parses Fampay "You have successfully received" emails and verifies they really came from Fam.

Layout of the real email (from the owner's screenshot):
  Hey <name>, You have successfully received ₹1.0 from <payer>
  Transaction ID: FMPIB...   Date: 01:17 AM IST, 04 November 2026   Updated Balance: ₹87.64   UTR: 845304841118
"""
import hashlib
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
TXN_RE = re.compile(r"\bTransaction\s*(?:ID|Id|No\.?|Number)\s*[:#\-]?\s*([A-Za-z0-9]{8,40})\b", re.I)
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
    """Returns dict(amount_paise, utr, txn_id, ref, received_at, payer) or None.
    Fam to Fam (P2P) payments often carry no UTR, only a Transaction ID, or nothing at all. Both are supported:
    ref = UTR, else Transaction ID, else a fingerprint of the email so it is stored once and can still be auto-matched by amount."""
    a, u, t = AMT_RE.search(text), UTR_RE.search(text), TXN_RE.search(text)
    f = FROM_RE.search(text)
    if not a or not (u or t or f):
        return None
    try:
        paise = int((Decimal(a.group(1).replace(",", "")) * 100).to_integral_value())
    except InvalidOperation:
        return None
    if paise <= 0:
        return None
    ts = None
    d = DATE_RE.search(text)
    if d:
        try:
            ts = datetime.strptime(d.group(1).upper().replace(" ", "") + " " + " ".join(d.group(2).split()), "%I:%M%p %d %B %Y").replace(tzinfo=IST).timestamp()
        except ValueError:
            ts = None
    utr = u.group(1) if u else ""
    txn = t.group(1).upper() if t else ""
    payer = (f.group(1).strip() if f else "")[:60]
    ref = utr or txn
    if not ref:
        ref = "NOREF" + hashlib.sha1(("%s|%s|%s|%s" % (paise, payer, d.group(0) if d else "", text[:300])).encode()).hexdigest()[:14].upper()
    return {"amount_paise": paise, "utr": ref, "real_utr": utr, "txn_id": txn, "received_at": ts, "payer": payer}


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
    _, n = db.run("INSERT OR IGNORE INTO payments(utr,amount_paise,received_at,payer,source,claimed_by,created,txn_id) VALUES(?,?,?,?,?,NULL,?,?)",
                  (info["utr"], info["amount_paise"], info["received_at"], info.get("payer", ""), source, time.time(), info.get("txn_id", "")))
    if n == 1:
        db.log_event("system", "payment_in", info["utr"], "", "%s paise via %s%s" % (info["amount_paise"], source, "" if info.get("real_utr") else " (no UTR)"))
        try:
            from . import orders
            orders.auto_match(info["utr"])          # the order is unlocked without the customer typing anything
        except Exception as e:
            print("[qrstudio] auto-match error:", e, flush=True)
    return n == 1


# ---------- IMAP poller ----------
_status = {"enabled": False, "last_ok": 0, "last_error": "", "seen": 0, "stored": 0, "rejected": 0}


def _save_status():
    try:
        import json as _j
        db.run("INSERT INTO meta(k,v) VALUES('imap_status',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (_j.dumps(_status),))
    except Exception:
        pass


def status():
    try:
        import json as _j
        r = db.one("SELECT v FROM meta WHERE k='imap_status'")
        if r:
            d = _j.loads(r["v"])
            return {**dict(_status), **d} if d.get("last_ok", 0) >= _status.get("last_ok", 0) else dict(_status)
    except Exception:
        pass
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
            last_uid = max(last_uid, int(uid))            # never re-read an email we already processed
            if info is None:
                if why != "no payment found in email":
                    _status["rejected"] += 1
                continue
            if store_payment(info, "email"):
                stored += 1
                _status["stored"] += 1
        db.run("INSERT INTO meta(k,v) VALUES('imap_last_uid',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(last_uid),))
        _status.update(last_ok=time.time(), last_error="")
        _save_status()
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
            _save_status()
        time.sleep(max(5, int(cfg.get("poll_seconds", 20))))


def start_poller():
    t = threading.Thread(target=_loop, name="fam-imap-poller", daemon=True)
    t.start()
    return t
