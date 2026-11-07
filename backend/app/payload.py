"""Design validation and QR payload building. Everything coming from the browser passes through clean_design()."""
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

KINDS = ("upi", "url", "text", "wifi", "contact", "whatsapp", "instagram", "youtube", "maps", "email", "sms", "phone", "telegram")
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
TG_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")
MAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
YT_RE = re.compile(r"^(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/[^\s]{2,200}$", re.I)
UPI_RE = re.compile(r"^[A-Za-z0-9._\-]{2,64}@[A-Za-z0-9._\-]{2,64}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
URL_RE = re.compile(r"^https?://[^\s]{3,480}$", re.I)


class DesignError(ValueError):
    pass


def _s(v, n):
    return str(v if v is not None else "").replace("\x00", "").strip()[:n]


def _phone(v: str) -> str:
    """Digits with country code. A bare 10 digit number is taken as an Indian mobile (+91)."""
    d = re.sub(r"\D", "", v or "")
    if len(d) == 10:
        d = "91" + d
    if not 8 <= len(d) <= 15:
        raise DesignError("Enter the phone number with country code, like 919876543210")
    return d


def clean_design(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise DesignError("Invalid design")
    kind = raw.get("kind", "upi")
    if kind not in KINDS:
        raise DesignError("Unknown QR type")
    f_in = raw.get("fields") or {}
    f = {}
    if kind == "upi":
        f["upi_id"] = _s(f_in.get("upi_id"), 80)
        if not UPI_RE.match(f["upi_id"]):
            raise DesignError("Enter a valid UPI ID like name@bank")
        amt = _s(f_in.get("amount"), 12)
        if amt:
            try:
                a = Decimal(amt)
                if a <= 0 or a > 100000 or a.as_tuple().exponent < -2:
                    raise InvalidOperation
            except InvalidOperation:
                raise DesignError("Amount must be a number up to 2 decimals")
            f["amount"] = format(a, "f")
        f["note"] = _s(f_in.get("note"), 40)
    elif kind == "url":
        f["url"] = _s(f_in.get("url"), 480)
        if not URL_RE.match(f["url"]):
            raise DesignError("Link must start with http:// or https://")
    elif kind == "text":
        f["text"] = _s(f_in.get("text"), 400)
        if not f["text"]:
            raise DesignError("Text is empty")
    elif kind == "wifi":
        f["ssid"] = _s(f_in.get("ssid"), 32)
        f["password"] = _s(f_in.get("password"), 64)
        f["enc"] = f_in.get("enc") if f_in.get("enc") in ("WPA", "WEP", "nopass") else "WPA"
        if not f["ssid"]:
            raise DesignError("Network name is required")
    elif kind == "contact":
        f["phone"] = _s(f_in.get("phone"), 20)
        f["email"] = _s(f_in.get("email"), 80)
        if not (f["phone"] or f["email"]):
            raise DesignError("Add a phone number or email")

    elif kind == "whatsapp":
        f["phone"] = _phone(_s(f_in.get("phone"), 20))
        f["message"] = _s(f_in.get("message"), 200)
    elif kind == "instagram":
        h = _s(f_in.get("handle"), 60).lstrip("@")
        h = re.sub(r"^https?://(www\.)?instagram\.com/", "", h, flags=re.I).strip("/").split("?")[0]
        if not HANDLE_RE.match(h):
            raise DesignError("Enter your Instagram username, like its_iarmxn_khxn")
        f["handle"] = h
    elif kind == "youtube":
        f["url"] = _s(f_in.get("url"), 220)
        if f["url"].startswith("@"):
            f["url"] = "https://www.youtube.com/" + f["url"]
        if not YT_RE.match(f["url"]):
            raise DesignError("Paste a YouTube link or a handle like @yourchannel")
        if not f["url"].lower().startswith("http"):
            f["url"] = "https://" + f["url"]
    elif kind == "maps":
        f["query"] = _s(f_in.get("query"), 200)
        if len(f["query"]) < 3:
            raise DesignError("Enter a place name, an address, or latitude,longitude")
    elif kind == "email":
        f["to"] = _s(f_in.get("to"), 100)
        if not MAIL_RE.match(f["to"]):
            raise DesignError("Enter a valid email address")
        f["subject"] = _s(f_in.get("subject"), 100)
        f["message"] = _s(f_in.get("message"), 300)
    elif kind == "sms":
        f["phone"] = "+" + _phone(_s(f_in.get("phone"), 20))
        f["message"] = _s(f_in.get("message"), 160)
    elif kind == "phone":
        f["phone"] = "+" + _phone(_s(f_in.get("phone"), 20))
    elif kind == "telegram":
        h = _s(f_in.get("handle"), 60).lstrip("@")
        h = re.sub(r"^https?://(www\.)?t\.me/", "", h, flags=re.I).strip("/")
        if not TG_RE.match(h):
            raise DesignError("Enter your Telegram username (5 to 32 letters, digits or _)")
        f["handle"] = h

    st_in = raw.get("style") or {}
    style = {
        "dot": st_in.get("dot") if st_in.get("dot") in ("square", "dot", "round") else "dot",
        "ink": st_in.get("ink") if HEX_RE.match(str(st_in.get("ink", ""))) else "#0b0b10",
        "logo": st_in.get("logo") if st_in.get("logo") in ("none", "letter", "image") else "letter",
        "logo_id": _s(st_in.get("logo_id"), 40),
    }
    if style["logo"] == "image" and not style["logo_id"]:
        style["logo"] = "letter"
    return {
        "kind": kind,
        "fields": f,
        "name": _s(raw.get("name"), 28),
        "title": _s(raw.get("title"), 30),
        "tag": _s(raw.get("tag"), 26),
        "dynamic": bool(raw.get("dynamic")) and kind == "url",
        "style": style,
    }


def _esc(s: str) -> str:
    return re.sub(r'([\\;,:"])', r"\\\1", s)


def build_payload(design: dict, public_url: str = "", slug: str = "") -> str:
    k, f = design["kind"], design["fields"]
    if k == "upi":
        s = "upi://pay?pa=" + quote(f["upi_id"], safe="@") + "&pn=" + quote(design.get("name") or "Payee", safe="")
        if f.get("amount"):
            s += "&am=" + f["amount"]
        s += "&cu=INR"
        if f.get("note"):
            s += "&tn=" + quote(f["note"], safe="")
        return s
    if k == "url":
        if design.get("dynamic") and slug:
            return public_url.rstrip("/") + "/r/" + slug
        return f["url"]
    if k == "text":
        return f["text"]
    if k == "wifi":
        s = "WIFI:T:" + f["enc"] + ";S:" + _esc(f["ssid"]) + ";"
        if f["enc"] != "nopass":
            s += "P:" + _esc(f.get("password", "")) + ";"
        return s + ";"
    if k == "contact":
        lines = ["BEGIN:VCARD", "VERSION:3.0", "FN:" + (design.get("name") or "Contact")]
        if f.get("phone"):
            lines.append("TEL:" + f["phone"])
        if f.get("email"):
            lines.append("EMAIL:" + f["email"])
        lines.append("END:VCARD")
        return "\n".join(lines)
    if k == "whatsapp":
        return "https://wa.me/" + f["phone"] + ("?text=" + quote(f["message"], safe="") if f.get("message") else "")
    if k == "instagram":
        return "https://www.instagram.com/" + f["handle"]
    if k == "youtube":
        return f["url"]
    if k == "maps":
        return "https://www.google.com/maps/search/?api=1&query=" + quote(f["query"], safe="")
    if k == "email":
        q = []
        if f.get("subject"):
            q.append("subject=" + quote(f["subject"], safe=""))
        if f.get("message"):
            q.append("body=" + quote(f["message"], safe=""))
        return "mailto:" + f["to"] + ("?" + "&".join(q) if q else "")
    if k == "sms":
        return "SMSTO:" + f["phone"] + ":" + f.get("message", "")
    if k == "phone":
        return "tel:" + f["phone"]
    if k == "telegram":
        return "https://t.me/" + f["handle"]
    raise DesignError("Unknown type")


def id_line(design: dict) -> str:
    k, f = design["kind"], design["fields"]
    if k == "upi":
        return "UPI ID : " + f["upi_id"]
    if k == "url":
        return re.sub(r"^https?://", "", f["url"])[:30]
    if k == "text":
        return re.sub(r"\s+", " ", f["text"])[:30]
    if k == "wifi":
        return "WiFi : " + f["ssid"][:24]
    if k == "contact":
        return ((design.get("name") or "") + " · " + (f.get("phone") or f.get("email") or ""))[:32]
    if k == "whatsapp":
        return "WhatsApp : +" + f["phone"]
    if k == "instagram":
        return "Instagram : @" + f["handle"]
    if k == "youtube":
        return re.sub(r"^https?://(www\.)?", "", f["url"])[:30]
    if k == "maps":
        return "Map : " + f["query"][:24]
    if k == "email":
        return "Email : " + f["to"][:24]
    if k in ("sms", "phone"):
        return ("SMS : " if k == "sms" else "Call : ") + f["phone"]
    if k == "telegram":
        return "Telegram : @" + f["handle"]
    return ""
