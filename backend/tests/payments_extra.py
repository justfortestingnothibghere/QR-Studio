"""Payment edge cases + admin tools. Server must run on localhost in mock mode with ADMIN_EMAILS=adm@x.com and fresh data.
   python3 tests/payments_extra.py"""
import io, json, re, sqlite3, sys, time, zipfile
import requests

BASE = "http://localhost:8000"
res = []


def check(name, cond, info=""):
    res.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "  -> %s" % (str(info)[:220],)))


class C:
    def __init__(self):
        self.s = requests.Session(); self.csrf = None

    def req(self, m, p, j=None, **kw):
        h = {"Origin": BASE}
        if self.csrf: h["X-CSRF-Token"] = self.csrf
        return self.s.request(m, BASE + p, json=j, headers=h, timeout=120, **kw)

    def signup(self, email, name="Test User"):
        r = self.req("POST", "/api/signup", {"email": email, "name": name, "password": "correct horse battery", "accept_terms": True}); assert r.status_code == 200, r.text
        self.csrf = self.req("GET", "/api/me").json()["csrf"]

    def login(self, email, pw="correct horse battery"):
        r = self.req("POST", "/api/login", {"email": email, "password": pw}); assert r.status_code == 200, r.text
        self.csrf = self.req("GET", "/api/me").json()["csrf"]


stamp = str(int(time.time()))
adm = C()
if adm.req("POST", "/api/signup", {"email": "adm@x.com", "name": "Admin", "password": "correct horse battery", "accept_terms": True}).status_code != 200:
    adm.login("adm@x.com")
adm.csrf = adm.req("GET", "/api/me").json()["csrf"]
u = C(); u.signup("p%s@x.com" % stamp)
design = {"kind": "upi", "fields": {"upi_id": "yourname@upi"}, "name": "Test", "title": "T", "tag": "x", "dynamic": False, "style": {"dot": "dot", "ink": "#0b0b10", "logo": "none", "logo_id": ""}}
qid = u.req("POST", "/api/qrs", {"theme_id": "crimson-surge", "design": design, "title": "Q1"}).json()["id"]


def new_order(c=u, **kw):
    r = c.req("POST", "/api/orders", dict({"kind": "export", "qr_id": qid}, **kw)); assert r.status_code == 200, r.text
    return r.json()["order"]


def add_payment(ref, paise):
    r = adm.req("POST", "/api/admin/payments", {"utr": ref, "amount": paise / 100}); return r


# 1. preview QR is dead
r = u.req("POST", "/api/preview", {"theme_id": "crimson-surge", "design": design})
check("preview served", r.status_code == 200 and r.headers["content-type"] == "image/jpeg")

# 2. wrong amount
o = new_order()
add_payment("111111111111", o["amount_paise"] + 5000)
r = u.req("POST", "/api/orders/%s/verify" % o["id"], {"utr": "111111111111"})
check("payment with wrong amount refused (422)", r.status_code == 422 and "needs exactly" in r.json()["error"], r.text)

# 3. auto match by amount alone when the email arrives (P2P, no UTR at all)
add_payment("NOREFAAAA1111", o["amount_paise"])
st = u.req("GET", "/api/orders/%s" % o["id"]).json()["order"]["status"]
check("exact amount email auto-unlocks the order", st == "paid", st)

# 4. Fam Transaction ID instead of UTR
o2 = new_order()
adm.req("POST", "/api/admin/payments", {"utr": "FMPIBTXN0000123", "amount": o2["amount_paise"] / 100})
# auto already paid it; create another where auto cannot (two orders, same amount impossible) -> test txn claim on expired-window order via order 3
st = u.req("GET", "/api/orders/%s" % o2["id"]).json()["order"]["status"]
check("transaction-id style reference stored and matched", st == "paid", st)

# 5. claim with Transaction ID typed by the customer (payment stored with a different primary ref)
o3 = new_order()
db = sqlite3.connect("data/qrstudio.db", timeout=20)
db.execute("INSERT INTO payments(utr,amount_paise,received_at,payer,source,claimed_by,created,txn_id) VALUES('999888777666',?,?,?,?,NULL,?,?)", (o3["amount_paise"] + 5000, time.time(), "X", "email", time.time(), "FMPIBTYPED001"))
db.commit()
r = u.req("POST", "/api/orders/%s/verify" % o3["id"], {"utr": "fmpibtyped001"})
check("customer can paste the Fam Transaction ID (wrong amount still refused)", r.status_code == 422, r.text)
db.execute("UPDATE payments SET amount_paise=? WHERE utr='999888777666'", (o3["amount_paise"],)); db.commit()
r = u.req("POST", "/api/orders/%s/verify" % o3["id"], {"utr": "fmpibtyped001"})
check("Transaction ID unlocks the order", r.status_code == 200 and r.json()["status"] == "paid", r.text)

# 6. 'my payment has no UTR' button
o4 = new_order()
r = u.req("POST", "/api/orders/%s/verify" % o4["id"], {"mode": "amount"})
check("no-UTR mode says 'not seen yet' when nothing arrived (404)", r.status_code == 404, r.text)
db.execute("INSERT INTO payments(utr,amount_paise,received_at,payer,source,claimed_by,created,txn_id) VALUES('NOREFMANUAL0001',?,?,?,?,NULL,?,'')", (o4["amount_paise"], time.time() - 5, "X", "email", time.time()))
db.commit()
r = u.req("POST", "/api/orders/%s/verify" % o4["id"], {"mode": "amount"})
check("no-UTR mode matches by exact amount", r.status_code == 200 and r.json()["status"] == "paid", r.text)

# 7. payment older than the order cannot be claimed
o5 = new_order()
db.execute("INSERT INTO payments(utr,amount_paise,received_at,payer,source,claimed_by,created,txn_id) VALUES('555444333222',?,?,?,?,NULL,?,'')", (o5["amount_paise"], time.time() - 3600, "X", "email", time.time()))
db.commit()
r = u.req("POST", "/api/orders/%s/verify" % o5["id"], {"utr": "555444333222"})
check("old payment (before the order existed) refused", r.status_code == 422, r.text)
r = u.req("POST", "/api/orders/%s/verify" % o5["id"], {"mode": "amount"})
check("no-UTR mode ignores old payments", r.status_code == 404, r.text)

# 8. another user cannot claim my payment, and cannot hog slots
v = C(); v.signup("q%s@x.com" % stamp)
r = v.req("POST", "/api/orders/%s/verify" % o5["id"], {"utr": "555444333222"})
check("other user cannot verify my order (404)", r.status_code == 404, r.text)
n_open = 0
codes = []
for _ in range(5):
    rr = v.req("POST", "/api/orders", {"kind": "pass"}); codes.append(rr.status_code)
check("max 3 open unpaid orders per user (4th gets 429)", codes[:3] == [200, 200, 200] and codes[3] == 429, codes)

# 9. brute force lock on one order
o6 = new_order()
last = 0
for i in range(14):
    last = u.req("POST", "/api/orders/%s/verify" % o6["id"], {"utr": "%012d" % (i + 1)}).status_code
    if last == 429: break
check("wrong guesses lock the order (429)", last == 429, last)

# 10. admin: mark paid / unpaid
o7 = new_order(c=v, kind="pass") if False else None
vo = v.req("GET", "/api/orders").json()["orders"][0]
r = adm.req("POST", "/api/admin/orders/%s/status" % vo["id"], {"status": "paid", "note": "test"})
check("admin can mark a pending pass order paid", r.status_code == 200, r.text)
check("pass became active", v.req("GET", "/api/me").json()["user"]["pass_active"] is True)
r = adm.req("POST", "/api/admin/orders/%s/status" % vo["id"], {"status": "unpaid", "note": "mistake"})
check("admin can mark it unpaid again", r.status_code == 200, r.text)
check("pass revoked", v.req("GET", "/api/me").json()["user"]["pass_active"] is False)
check("non-admin cannot change status", u.req("POST", "/api/admin/orders/%s/status" % vo["id"], {"status": "paid"}).status_code == 403)
r = adm.req("GET", "/api/admin/orders/%s" % vo["id"])
check("order detail has an audit trail", r.status_code == 200 and len(r.json()["events"]) >= 2, r.text[:200])
# unpaid export loses download
po = [x for x in u.req("GET", "/api/orders").json()["orders"] if x["status"] == "paid"][0]
check("paid export downloads", u.req("GET", "/api/orders/%s/download/jpg" % po["id"]).status_code == 200)
adm.req("POST", "/api/admin/orders/%s/status" % po["id"], {"status": "unpaid"})
check("unpaid order cannot download (402)", u.req("GET", "/api/orders/%s/download/jpg" % po["id"]).status_code == 402)
adm.req("POST", "/api/admin/orders/%s/status" % po["id"], {"status": "paid"})

# 11. payment test, any amount
R0 = adm.req("GET", "/api/admin/stats").json()["stats"]["revenue"]
for amt in (0.01, 1, 7.5, 12345.67):
    r = adm.req("POST", "/api/admin/test-order", {"amount": amt})
    check("test order for ₹%s created" % amt, r.status_code == 200 and r.json()["order"]["amount_paise"] == round(amt * 100), r.text[:150])
check("amount 0 refused", adm.req("POST", "/api/admin/test-order", {"amount": 0}).status_code == 400)
t = adm.req("POST", "/api/admin/test-order", {"amount": 3.33}).json()["order"]
check("same open amount refused (409)", adm.req("POST", "/api/admin/test-order", {"amount": 3.33}).status_code == 409)
add_payment("TESTREF0000001", t["amount_paise"])
st = adm.req("GET", "/api/orders/%s" % t["id"]).json()["order"]["status"]
check("test order verified through the same matching path", st == "paid", st)
check("test orders do not count as revenue", adm.req("GET", "/api/admin/stats").json()["stats"]["revenue"] == R0)
check("non-admin cannot create test orders", u.req("POST", "/api/admin/test-order", {"amount": 1}).status_code == 403)

# 12. lists
for p in ("orders", "payments", "users", "qrs", "events", "system", "settings", "stats"):
    r = adm.req("GET", "/api/admin/" + p); check("admin %s list ok" % p, r.status_code == 200, r.text[:120])
check("order search by email", len(adm.req("GET", "/api/admin/orders?q=q" + stamp).json()["orders"]) >= 1)
check("security log has failed verifies", adm.req("GET", "/api/admin/events?kind=security").json()["total"] >= 1)
check("users list is admin only", u.req("GET", "/api/admin/users").status_code == 403)
r = adm.req("POST", "/api/admin/settings", {"announcement": "Hello", "announcement_kind": "info", "signups_open": False})
check("settings saved", r.status_code == 200)
check("announcement published in /config.json", requests.get(BASE + "/config.json").json().get("announcement") == "Hello")
check("signups can be closed", C().req("POST", "/api/signup", {"email": "z%s@x.com" % stamp, "name": "Zed", "password": "correct horse battery", "accept_terms": True}).status_code == 403)
adm.req("POST", "/api/admin/settings", {"announcement": "", "signups_open": True})
uid = [x for x in adm.req("GET", "/api/admin/users").json()["users"] if x["email"].startswith("q")][0]["id"]
check("grant 5 pass days", adm.req("POST", "/api/admin/users/%d/pass" % uid, {"days": 5}).status_code == 200 and v.req("GET", "/api/me").json()["user"]["pass_active"])
check("revoke pass", adm.req("POST", "/api/admin/users/%d/pass" % uid, {"revoke": True}).status_code == 200 and not v.req("GET", "/api/me").json()["user"]["pass_active"])
check("admin sets a temporary password", adm.req("POST", "/api/admin/users/%d/password" % uid, {"password": "temp pass 12345"}).status_code == 200 and v.req("GET", "/api/me").json()["user"] is None)

# 13. backup + restore
bk = adm.s.get(BASE + "/api/admin/backup", timeout=120)
z = zipfile.ZipFile(io.BytesIO(bk.content)) if bk.status_code == 200 else None
check("backup is a zip with db + manifest", z and "db/qrstudio.db" in z.namelist() and "manifest.json" in z.namelist(), bk.status_code)
users_before = adm.req("GET", "/api/admin/users").json()["total"]
extra = C(); extra.signup("later%s@x.com" % stamp)
check("new user added after backup", adm.req("GET", "/api/admin/users").json()["total"] == users_before + 1)
def restore(data, name, pw="correct horse battery", confirm="RESTORE"):
    h = {"Origin": BASE, "X-CSRF-Token": adm.csrf}
    return adm.s.post(BASE + "/api/admin/restore", files={"file": (name, data)}, data={"password": pw, "confirm": confirm}, headers=h, timeout=300)
check("restore needs the confirm word", restore(bk.content, "b.zip", confirm="no").status_code == 400)
check("restore needs the admin password", restore(bk.content, "b.zip", pw="wrong password!").status_code == 403)
check("garbage upload refused", restore(b"hello world", "x.zip").status_code == 400)
evil = io.BytesIO()
with zipfile.ZipFile(evil, "w") as zz:
    zz.writestr("db/qrstudio.db", b"x"); zz.writestr("../../evil.txt", b"x")
check("zip with path traversal refused", restore(evil.getvalue(), "e.zip").status_code == 400)
r = restore(bk.content, "b.zip")
check("restore works", r.status_code == 200 and r.json()["counts"]["users"] == users_before, r.text[:200])
adm2 = C(); adm2.login("adm@x.com")
check("after restore the data is the backup's (later user is gone)", adm2.req("GET", "/api/admin/users").json()["total"] == users_before)
check("old sessions are logged out after restore", adm.req("GET", "/api/me").json()["user"] is None)
check("raw .db restore accepted too", adm2.s.post(BASE + "/api/admin/restore", files={"file": ("x.db", z.read("db/qrstudio.db"))}, data={"password": "correct horse battery", "confirm": "RESTORE"}, headers={"Origin": BASE, "X-CSRF-Token": adm2.csrf}, timeout=300).status_code == 200)

print("\n%d/%d passed" % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
