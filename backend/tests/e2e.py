#!/usr/bin/env python3
"""End-to-end test against a running server (payments.mode must be 'mock').  python tests/e2e.py [http://localhost:8000]"""
import io
import json
import secrets
import sys
import time

import cv2
import numpy as np
import requests
from PIL import Image

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
ORIGIN = {"Origin": BASE}
RES = []


def check(name, cond, extra=""):
    RES.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name + (("  -> " + str(extra)) if (extra and not cond) else ""))


class Client:
    def __init__(self):
        self.s = requests.Session()
        self.csrf = None

    def req(self, method, path, json_body=None, files=None, data=None, origin=True, csrf=True, **kw):
        h = dict(ORIGIN) if origin else {}
        if csrf and self.csrf:
            h["X-CSRF-Token"] = self.csrf
        return self.s.request(method, BASE + path, json=json_body, files=files, data=data, headers=h, timeout=120, **kw)

    def me(self):
        d = self.req("GET", "/api/me").json()
        self.csrf = d.get("csrf")
        return d

    def signup(self, email, name="Test User", pw="correct horse battery"):
        r = self.req("POST", "/api/signup", {"email": email, "name": name, "password": pw, "accept_terms": True})
        self.me()
        return r


DESIGN = {"kind": "upi", "fields": {"upi_id": "shop@fam", "amount": "", "note": ""}, "name": "Arman Khan", "title": "Your Pocket UPI QR", "tag": "SCAN · PAY · DONE", "dynamic": False,
          "style": {"dot": "dot", "ink": "#0b0b10", "logo": "letter", "logo_id": ""}}


def decode(img_bytes, expect_prefix=None):
    arr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    res, _ = cv2.wechat_qrcode_WeChatQRCode().detectAndDecode(arr)
    return res[0] if res else ""


def main():
    # ---- public pages and themes
    for p in ("/", "/studio", "/themes", "/pricing", "/login", "/signup", "/terms", "/privacy"):
        r = requests.get(BASE + p, timeout=30)
        check("page %s 200" % p, r.status_code == 200 and "text/html" in r.headers.get("content-type", ""), r.status_code)
    r = requests.get(BASE + "/nope", timeout=30)
    check("404 page for unknown path", r.status_code == 404 and "Page not found" in r.text)
    r = requests.get(BASE + "/api/nope", timeout=30)
    check("404 json for unknown api", r.status_code == 404 and r.headers["content-type"].startswith("application/json"))
    r = requests.get(BASE + "/api/themes", timeout=30).json()
    ids = [t["id"] for t in r["themes"]]
    check("18 built-in themes listed", len(ids) >= 18, len(ids))
    r = requests.get(BASE + "/api/themes/crimson-surge/thumb", timeout=60)
    check("theme thumb is a JPEG", r.status_code == 200 and r.headers["content-type"] == "image/jpeg")
    r = requests.get(BASE + "/api/themes/does-not-exist/thumb", timeout=30)
    check("unknown theme thumb 404", r.status_code == 404)
    r = requests.get(BASE + "/assets/js/app.js", timeout=30)
    check("static asset served", r.status_code == 200)
    r = requests.get(BASE + "/assets/../backend/config.json", timeout=30)
    check("path traversal to config blocked", r.status_code in (400, 404) and "secret_key" not in r.text)
    r = requests.get(BASE + "/", timeout=30)
    check("security headers present", "default-src 'self'" in r.headers.get("content-security-policy", "") and r.headers.get("x-frame-options") == "DENY")

    # ---- anonymous preview + watermark
    anon = Client()
    r = anon.req("POST", "/api/preview", {"theme_id": "azure-void", "design": DESIGN})
    check("anonymous preview returns JPEG", r.status_code == 200 and r.headers["content-type"] == "image/jpeg", r.text[:200])
    pv = Image.open(io.BytesIO(r.content))
    check("preview is low-res (640x960)", pv.size == (640, 960), pv.size)
    check("scan check header says OK", r.headers.get("X-Scan-OK") == "1")
    check("preview not cacheable", "no-store" in r.headers.get("cache-control", ""))
    r2 = anon.req("POST", "/api/preview", {"theme_id": "azure-void", "design": DESIGN | {"fields": {"upi_id": "bad id"}}})
    check("invalid UPI id rejected with message", r2.status_code == 400 and "UPI" in r2.json()["error"], r2.text[:100])
    r3 = anon.req("POST", "/api/preview", {"theme_id": "azure-void", "design": DESIGN}, origin=False)
    check("POST without Origin blocked (CSRF)", r3.status_code == 403)
    r3 = requests.post(BASE + "/api/preview", json={"theme_id": "azure-void", "design": DESIGN}, headers={"Origin": "https://evil.example"}, timeout=30)
    check("cross-site Origin blocked", r3.status_code == 403)
    r4 = anon.req("POST", "/api/orders", {"kind": "pass"})
    check("order needs login", r4.status_code == 401)

    # ---- signup / login / sessions
    a = Client()
    ea = "alice_%s@example.com" % secrets.token_hex(3)
    r = a.signup(ea, "Alice Test")
    check("signup works", r.status_code == 200 and r.json()["user"]["email"] == ea, r.text[:200])
    check("session cookie is HttpOnly", "httponly" in r.headers.get("set-cookie", "").lower())
    check("signup without terms rejected", Client().req("POST", "/api/signup", {"email": "x%s@example.com" % secrets.token_hex(2), "name": "Xx", "password": "longenough1", "accept_terms": False}).status_code == 400)
    check("weak password rejected", Client().req("POST", "/api/signup", {"email": "w%s@example.com" % secrets.token_hex(2), "name": "Ww", "password": "short", "accept_terms": True}).status_code == 400)
    check("duplicate email rejected", Client().req("POST", "/api/signup", {"email": ea, "name": "Alice", "password": "correct horse battery", "accept_terms": True}).status_code == 409)
    bad = Client().req("POST", "/api/login", {"email": ea, "password": "wrong password!"})
    nouser = Client().req("POST", "/api/login", {"email": "nobody_%s@example.com" % secrets.token_hex(3), "password": "wrong password!"})
    check("wrong password and unknown email give the same error", bad.status_code == 401 and nouser.status_code == 401 and bad.json() == nouser.json())

    # ---- save, quote, order without payment
    r = a.req("POST", "/api/qrs", {"theme_id": "crimson-surge", "design": DESIGN, "title": "Shop QR"})
    check("save QR", r.status_code == 200, r.text[:200])
    qid = r.json()["id"]
    r = a.req("POST", "/api/qrs", {"theme_id": "crimson-surge", "design": DESIGN, "title": "x"}, csrf=False)
    check("state change without CSRF token rejected", r.status_code == 403)
    r = a.req("POST", "/api/quote", {"theme_id": "crimson-surge", "design": DESIGN, "print": True})
    q = r.json()
    check("quote: base 29 + logo 10 + print 10 = 49", q["rupees"] == 49, q)
    r = a.req("POST", "/api/orders", {"kind": "export", "qr_id": qid, "print": True})
    o1 = r.json()["order"]
    check("order created with unique paise (4901..4999)", r.status_code == 200 and 4901 <= o1["amount_paise"] <= 4999 and o1["status"] == "pending", o1)
    r = a.req("GET", "/api/orders/%s/download/png" % o1["id"])
    check("download blocked before payment (402)", r.status_code == 402)
    r = a.req("POST", "/api/orders/%s/verify" % o1["id"], {"utr": "123456789012"})
    check("unknown UTR -> 404 message", r.status_code == 404, r.text[:100])
    r = a.req("POST", "/api/orders/%s/verify" % o1["id"], {"utr": "abc"})
    check("malformed UTR -> 400", r.status_code == 400)
    r = a.req("GET", "/api/orders/%s/payqr" % o1["id"])
    check("pay QR image served for pending order", r.status_code == 200 and r.headers["content-type"] == "image/png" and "upi://pay" in decode(r.content))

    # ---- payment: wrong amount, replay, right amount
    r = a.req("POST", "/api/orders/%s/simulate" % o1["id"], {})
    utr1 = r.json()["utr"]
    o2 = a.req("POST", "/api/orders", {"kind": "export", "qr_id": qid, "print": False}).json()["order"]
    r = a.req("POST", "/api/orders/%s/verify" % o2["id"], {"utr": utr1})
    check("UTR with wrong amount rejected (422)", r.status_code == 422 and "needs exactly" in r.json()["error"], r.text[:200])
    r = a.req("POST", "/api/orders/%s/verify" % o1["id"], {"utr": utr1})
    check("correct UTR unlocks order", r.status_code == 200 and r.json()["status"] == "paid", r.text[:200])
    r = a.req("POST", "/api/orders", {"kind": "export", "qr_id": qid, "print": True})
    o3 = r.json()["order"]
    r = a.req("POST", "/api/orders/%s/verify" % o3["id"], {"utr": utr1})
    check("replaying a used UTR rejected (409)", r.status_code == 409, r.text[:200])

    # ---- downloads + clean export correctness
    r = a.req("GET", "/api/orders/%s/download/png" % o1["id"])
    check("PNG download works", r.status_code == 200 and r.content[:4] == b"\x89PNG", r.status_code)
    img = Image.open(io.BytesIO(r.content))
    check("export is 2048x3072", img.size == (2048, 3072), img.size)
    txt = decode(r.content)
    check("clean export QR decodes to the right UPI link", txt.startswith("upi://pay?pa=shop@fam"), txt)
    check("export has no watermark text region difference (clean differs from preview)", img.resize((640, 960)).tobytes() != pv.tobytes())
    for fmt, magic in (("jpg", b"\xff\xd8"), ("pdf", b"%PDF"), ("svg", b"<svg"), ("qrpng", b"\x89PNG")):
        r = a.req("GET", "/api/orders/%s/download/%s" % (o1["id"], fmt))
        check("download %s works" % fmt, r.status_code == 200 and r.content[:4].startswith(magic[:len(magic)]) or (fmt == "svg" and b"<svg" in r.content[:200]), (r.status_code, r.content[:8]))
    r = a.req("GET", "/api/orders/%s/download/svg" % o2["id"])
    check("unpaid order cannot download", r.status_code == 402)

    # ---- IDOR: second user
    b = Client()
    b.signup("bob_%s@example.com" % secrets.token_hex(3), "Bob Test")
    check("other user cannot download my order", b.req("GET", "/api/orders/%s/download/png" % o1["id"]).status_code == 402)
    check("other user cannot read my order", b.req("GET", "/api/orders/%s" % o1["id"]).status_code == 404)
    check("other user cannot verify my order", b.req("POST", "/api/orders/%s/verify" % o3["id"], {"utr": "111111111111"}).status_code == 404)
    check("other user cannot delete my QR", b.req("DELETE", "/api/qrs/%d" % qid).status_code == 404)
    check("other user's QR list is empty", b.req("GET", "/api/qrs").json()["qrs"] == [])

    # ---- uploads
    png = io.BytesIO()
    Image.effect_noise((600, 900), 60).convert("RGB").save(png, "PNG")
    r = a.req("POST", "/api/themes/upload", files={"image": ("art.png", png.getvalue(), "image/png")}, data={"name": "My Art", "tpl": "A", "accent": "#ff00aa", "ink": "#ffffff", "soft": "#eeeeee"})
    check("custom theme upload works", r.status_code == 200 and r.json()["theme"]["mine"], r.text[:200])
    tid = r.json()["theme"]["id"]
    r = a.req("POST", "/api/themes/upload", files={"image": ("x.png", b"<?php system($_GET['c']); ?>", "image/png")}, data={"name": "bad", "tpl": "A", "accent": "#ff00aa", "ink": "#ffffff", "soft": "#eeeeee"})
    check("non-image disguised as PNG rejected", r.status_code == 415, r.text[:100])
    r = a.req("POST", "/api/themes/upload", files={"image": ("x.png", png.getvalue(), "image/png")}, data={"name": "bad", "tpl": "A", "accent": "red;}", "ink": "#ffffff", "soft": "#eeeeee"})
    check("bad colour value rejected", r.status_code == 400)
    r = a.req("POST", "/api/preview", {"theme_id": tid, "design": DESIGN})
    check("preview with own theme works", r.status_code == 200 and r.headers["content-type"] == "image/jpeg", r.text[:100])
    check("other user cannot use my custom theme", b.req("POST", "/api/preview", {"theme_id": tid, "design": DESIGN}).status_code == 404)
    check("other user cannot see my theme thumb", requests.get(BASE + "/api/themes/%s/thumb" % tid, timeout=30).status_code == 404)
    q = a.req("POST", "/api/quote", {"theme_id": tid, "design": DESIGN}).json()
    check("own theme adds ₹20 (29+10+20=59)", q["rupees"] == 59, q)
    lg = io.BytesIO()
    Image.new("RGB", (200, 200), (255, 100, 0)).save(lg, "PNG")
    r = a.req("POST", "/api/logos/upload", files={"image": ("l.png", lg.getvalue(), "image/png")})
    check("logo upload works", r.status_code == 200, r.text[:100])
    lid = r.json()["logo_id"]
    d2 = json.loads(json.dumps(DESIGN))
    d2["style"].update(logo="image", logo_id=lid)
    r = a.req("POST", "/api/preview", {"theme_id": "azure-void", "design": d2})
    check("preview with uploaded logo works", r.status_code == 200)
    check("other user cannot read my logo", b.req("GET", "/api/logos/%s" % lid).status_code == 404)
    r = b.req("POST", "/api/preview", {"theme_id": "azure-void", "design": d2})
    check("other user's design referencing my logo falls back safely", r.status_code == 200)

    # ---- dynamic QR
    d3 = {"kind": "url", "fields": {"url": "https://example.com/menu"}, "name": "Cafe", "title": "Menu", "tag": "SCAN", "dynamic": True, "style": {"dot": "square", "ink": "#0b0b10", "logo": "none", "logo_id": ""}}
    r = a.req("POST", "/api/qrs", {"theme_id": "neon-horizon", "design": d3, "title": "Cafe menu"})
    dq = r.json()
    check("dynamic QR gets a slug", bool(dq.get("slug")), dq)
    check("dynamic link inactive until paid", requests.get(BASE + "/r/" + dq["slug"], allow_redirects=False, timeout=30).status_code == 404)
    od = a.req("POST", "/api/orders", {"kind": "export", "qr_id": dq["id"]}).json()["order"]
    u = a.req("POST", "/api/orders/%s/simulate" % od["id"], {}).json()["utr"]
    a.req("POST", "/api/orders/%s/verify" % od["id"], {"utr": u})
    r = requests.get(BASE + "/r/" + dq["slug"], allow_redirects=False, timeout=30)
    check("dynamic link redirects once paid", r.status_code == 302 and r.headers["location"] == "https://example.com/menu", (r.status_code, r.headers.get("location")))
    a.req("POST", "/api/qrs/%d/target" % dq["id"], {"url": "https://example.com/new"})
    r = requests.get(BASE + "/r/" + dq["slug"], allow_redirects=False, timeout=30)
    check("retargeting changes redirect without changing QR", r.headers.get("location") == "https://example.com/new")
    r = a.req("POST", "/api/qrs/%d/target" % dq["id"], {"url": "javascript:alert(1)"})
    check("javascript: target rejected", r.status_code == 400)
    qs_ = [x for x in a.req("GET", "/api/qrs").json()["qrs"] if x["id"] == dq["id"]][0]
    check("scan counter counted 2 scans", qs_["scans"] == 2, qs_["scans"])
    ex = requests.get(BASE + "/api/orders/%s/download/png" % od["id"], cookies=a.s.cookies, timeout=120)
    check("dynamic export QR points at the short link", decode(ex.content).endswith("/r/" + dq["slug"]), decode(ex.content))

    # ---- pass
    r = a.req("POST", "/api/orders", {"kind": "pass"})
    op = r.json()["order"]
    check("pass order is ₹99.xx", 9901 <= op["amount_paise"] <= 9999, op)
    u = a.req("POST", "/api/orders/%s/simulate" % op["id"], {}).json()["utr"]
    a.req("POST", "/api/orders/%s/verify" % op["id"], {"utr": u})
    check("pass activates", a.me()["user"]["pass_active"] is True)
    r = a.req("POST", "/api/orders", {"kind": "export", "qr_id": qid})
    check("export is free with an active pass", r.json()["order"]["status"] == "paid" and r.json()["order"]["amount_paise"] == 0, r.text[:200])

    # ---- password change, logout
    r = a.req("POST", "/api/password", {"old": "correct horse battery", "new": "another long password"})
    check("password change works", r.status_code == 200)
    r = a.req("POST", "/api/logout", {})
    check("logout works and session is dead", r.status_code == 200 and a.req("GET", "/api/qrs").status_code == 401)
    r = a.req("POST", "/api/login", {"email": ea, "password": "another long password"})
    check("login with new password", r.status_code == 200)

    # ---- admin protection
    check("non-admin cannot read admin stats", a.req("GET", "/api/admin/stats").status_code == 403)
    check("anonymous cannot read admin stats", requests.get(BASE + "/api/admin/stats", timeout=30).status_code == 401)

    # ---- rate limit on login
    victim = "rl_%s@example.com" % secrets.token_hex(3)
    codes = [Client().req("POST", "/api/login", {"email": victim, "password": "nope-nope-nope"}).status_code for _ in range(10)]
    check("login brute force gets 429", 429 in codes, codes)

    print("\n%d/%d passed" % (sum(RES), len(RES)))
    sys.exit(0 if all(RES) else 1)


if __name__ == "__main__":
    main()
