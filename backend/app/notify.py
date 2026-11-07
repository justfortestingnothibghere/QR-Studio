"""Telegram alerts to the owner (new order paid, unmatched payment, new review, mailbox trouble). Optional: needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID."""
import json
import threading
import time
import urllib.request

from . import config

_last = {}


def enabled() -> bool:
    return bool(config.get("notify.telegram_token") and config.get("notify.telegram_chat_id"))


def _post(text: str):
    try:
        url = "https://api.telegram.org/bot%s/sendMessage" % config.get("notify.telegram_token")
        data = json.dumps({"chat_id": config.get("notify.telegram_chat_id"), "text": text[:3500], "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:      # an alert must never break a payment
        print("[qrstudio] telegram alert failed:", str(e)[:120], flush=True)


def send(text: str, key: str = "", every: int = 0):
    """Fire and forget. `key` + `every` (seconds) stops the same alert from repeating."""
    if not enabled():
        return False
    if key and every:
        now = time.time()
        if now - _last.get(key, 0) < every:
            return False
        _last[key] = now
    threading.Thread(target=_post, args=("QR Studio\n" + text,), daemon=True).start()
    return True
