#!/usr/bin/env python3
"""Growth features: referral credits, new QR types, SEO pages, share, reviews, analytics.  Run on a fresh mock server."""
import json, re, secrets, sys
sys.argv = sys.argv[:1] + sys.argv[1:2]
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from e2e import BASE, Client, DESIGN, check, RES
import requests

def mk(ref=None):
    c = Client(); e = "g%s@x.com" % secrets.token_hex(4)
    body = {"email": e, "name": "Gro User", "password": "correct horse battery", "accept_terms": True}
    if ref: body["ref"] = ref; body["src"] = "invite"
    r = c.req("POST", "/api/signup", body); c.me(); return c, r

def pay(c, design=DESIGN, **extra):
    q = c.req("POST", "/api/qrs", {"id": None, "theme_id": "crimson-surge", "design": design, "title": "t"}).json()
    o = c.req("POST", "/api/orders", {"kind": "export", "qr_id": q["id"], **extra}).json()["order"]
    return q["id"], o

def paid(c):
    qid, o = pay(c)
    r = c.req("POST", "/api/orders/%s/simulate" % o["id"], {})
    return r.status_code == 200

a, _ = mk()
info = a.req("GET", "/api/referral").json()
check("referral link uses site url", info["link"].startswith("https://qr.teamdev.sbs/?ref="), info["link"])
code = info["code"]
fr = []
for i in range(3):
    c, r = mk(code); fr.append(c); check("invitee %d signed up" % i, r.status_code == 200, r.text)
s = a.req("GET", "/api/referral").json()["stats"]
check("3 joined, none paid -> no credit", s["joined"] == 3 and s["available"] == 0)
check("credit can't be used without credit", pay(a, )[1] is not None and a.req("POST", "/api/orders", {"kind": "export", "qr_id": pay(a)[0], "use_credit": True}).status_code == 409)
check("friend pays", paid(fr[1]))
s = a.req("GET", "/api/referral").json()["stats"]
check("one friend paying earns 1 credit", s["available"] == 1, s)
check("me shows credits", a.me()["user"]["credits"] == 1)
qid = a.req("POST", "/api/qrs", {"id": None, "theme_id": "crimson-surge", "design": DESIGN, "title": "t"}).json()["id"]
r = a.req("POST", "/api/orders", {"kind": "export", "qr_id": qid, "use_credit": True})
check("credit order is paid at once", r.status_code == 200 and r.json()["order"]["status"] == "paid", r.text[:200])
check("credit consumed", a.req("GET", "/api/referral").json()["stats"]["available"] == 0)
r = a.req("POST", "/api/orders", {"kind": "export", "qr_id": qid, "use_credit": True})
check("no second use", r.status_code in (409, 400, 422))
c4, _ = mk(code); c5, _ = mk(code)
check("more invites without payment give nothing", a.req("GET", "/api/referral").json()["stats"]["available"] == 0)
x, _ = mk()
r = x.req("POST", "/api/orders", {"kind": "export", "qr_id": x.req("POST", "/api/qrs", {"id": None, "theme_id": "crimson-surge", "design": DESIGN, "title": "t"}).json()["id"], "use_credit": True})
check("new user can't get free download", r.status_code == 409)

# new QR types
kinds = {"whatsapp": {"phone": "9876543210", "message": "Hi"}, "instagram": {"handle": "its_iarmxn_khxn"}, "youtube": {"url": "@teamdev"}, "maps": {"query": "Guwahati Paltan Bazaar"},
         "email": {"to": "a@b.com", "subject": "Hi", "message": "x"}, "sms": {"phone": "9876543210", "message": "Hi"}, "phone": {"phone": "9876543210"}, "telegram": {"handle": "teamdev_x"}}
for k, f in kinds.items():
    d = dict(DESIGN, kind=k, fields=f)
    r = a.req("POST", "/api/preview", {"theme_id": "crimson-surge", "design": d})
    check("preview %s" % k, r.status_code == 200 and r.headers.get("X-Scan-OK") == "1", r.text[:120])
check("bad instagram rejected", a.req("POST", "/api/preview", {"theme_id": "crimson-surge", "design": dict(DESIGN, kind="instagram", fields={"handle": "a b!"})}).status_code in (400, 422))

# SEO
def get(p): return requests.get(BASE + p, headers={"User-Agent": "Mozilla/5.0"})
for p in ["/", "/qr", "/qr/upi-qr-code-poster", "/guides", "/about", "/faq", "/pricing", "/themes", "/themes/noir-gold"]:
    r = get(p); t = r.text
    ok = r.status_code == 200 and t.count("<title>") == 1 and 'rel="canonical"' in t and "https://qr.teamdev.sbs" in t
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
        try: json.loads(m)
        except Exception: ok = False
    check("seo page %s" % p, ok)
check("home has Organization+FAQ ld", "FAQPage" in get("/").text and "Organization" in get("/").text)
check("login is noindex", "noindex" in get("/login").text)
sm = get("/sitemap.xml").text
check("sitemap lists qr pages on site url", "https://qr.teamdev.sbs/qr/wifi-qr-code-generator" in sm and "/dashboard" not in sm and "/admin" not in sm)
check("robots has sitemap", "Sitemap: https://qr.teamdev.sbs/sitemap.xml" in get("/robots.txt").text)
check("404 page", get("/qr/nope").status_code == 404)
check("og image", get("/assets/img/og.jpg").status_code == 200 and get("/manifest.webmanifest").status_code == 200)
cfg = get("/config.json").json()
check("config branding", cfg["support_email"] == "teamdevmail@gmail.com" and cfg["support_instagram"] == "its_iarmxn_khxn" and cfg["instagram_verified"])

# share
r = a.req("POST", "/api/qrs/%d/share" % qid, {}); tok = r.json()["url"].rsplit("/", 1)[1]
check("share page", get("/p/" + tok).status_code == 200 and "noindex" in get("/p/" + tok).text)
im = get("/api/p/%s.jpg" % tok); check("share image jpeg", im.status_code == 200 and im.headers["content-type"] == "image/jpeg")
a.req("DELETE", "/api/qrs/%d/share" % qid)
check("unshared gone", get("/p/" + tok).status_code == 404)
check("other user can't share my qr", x.req("POST", "/api/qrs/%d/share" % qid, {}).status_code == 404)

# reviews
check("unpaid can't review", x.req("POST", "/api/reviews", {"stars": 5, "text": "great stuff"}).status_code == 403)
check("paid can review", fr[1].req("POST", "/api/reviews", {"stars": 5, "text": "great stuff"}).status_code == 200)
check("not public until approved", get("/api/reviews").json()["count"] == 0)
adm = Client(); adm.req("POST", "/api/signup", {"email": "adm@x.com", "name": "Adm", "password": "correct horse battery", "accept_terms": True}); adm.me()
l = adm.req("GET", "/api/admin/reviews")
if l.status_code != 200:
    adm.req("POST", "/api/login", {"email": "adm@x.com", "password": "correct horse battery"}); adm.me(); l = adm.req("GET", "/api/admin/reviews")
rid = l.json()["reviews"][0]["id"]
check("admin approves", adm.req("POST", "/api/admin/reviews/%d" % rid, {"status": "approved"}).status_code == 200)
check("approved is public", get("/api/reviews").json()["count"] == 1)
check("non-admin blocked from growth", a.req("GET", "/api/admin/growth").status_code in (401, 403))
g = adm.req("GET", "/api/admin/growth").json()
check("analytics recorded", g["views"] >= 5 and any(p["path"] == "/qr/upi-qr-code-poster" for p in g["pages"]) and any(x["src"] == "invite" for x in g["signups"]), g)
check("leaderboard", g["referrers"] and g["referrers"][0]["joined"] >= 3)
print("\n%d/%d passed" % (sum(RES), len(RES)))
sys.exit(0 if all(RES) else 1)
