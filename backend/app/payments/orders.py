"""Order creation (unique paise per open order), automatic payment matching and manual claim logic.
Every state change runs inside one IMMEDIATE transaction, so two requests can never use the same payment twice.

How an order gets paid (any one of these):
  1. auto   - the Fam email arrives, exactly one open order has that exact amount (paise are unique per order) -> unlocked.
  2. ref    - customer pastes the UTR or the Fam Transaction ID from the email.
  3. amount - customer says "my payment has no UTR" (Fam to Fam transfers) -> matched by exact amount and time window.
"""
import json
import secrets
import time

from .. import config, db
from ..security import ApiError

MAX_OPEN_ORDERS = 3


def _expire_old(c):
    c.execute("UPDATE orders SET status='expired' WHERE status='pending' AND expires<?", (time.time(),))


def _insert(c, oid, user_id, kind, qr_id, paise, rupees, status, created, expires, paid_at, utr, snapshot, label):
    c.execute("INSERT INTO orders(id,user_id,kind,qr_id,amount_paise,rupees,status,created,expires,paid_at,utr,snapshot,label) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (oid, user_id, kind, qr_id, paise, rupees, status, created, expires, paid_at, utr, json.dumps(snapshot), label))


def create_order(user_id: int, kind: str, rupees: int, qr_id, snapshot: dict, label: str) -> dict:
    mins = int(config.get("payments.order_expiry_minutes", 45))
    t = time.time()
    oid = "QS" + secrets.token_hex(4).upper()
    with db.tx() as c:
        _expire_old(c)
        if rupees == 0:
            _insert(c, oid, user_id, kind, qr_id, 0, 0, "paid", t, t, t, "PASS", snapshot, label)
            return {"id": oid, "amount_paise": 0, "status": "paid", "expires": t}
        # a visitor must not be able to hog the 99 amount slots of a price point
        open_n = c.execute("SELECT COUNT(*) n FROM orders WHERE user_id=? AND status='pending' AND kind!='test'", (user_id,)).fetchone()["n"]
        if open_n >= MAX_OPEN_ORDERS:
            raise ApiError(429, "You already have %d unpaid orders open. Pay one or wait for it to expire (%d min)." % (open_n, mins))
        used = {r["amount_paise"] for r in c.execute("SELECT amount_paise FROM orders WHERE status='pending' AND amount_paise BETWEEN ? AND ?",
                                                      (rupees * 100, rupees * 100 + 99)).fetchall()}
        free = [k for k in range(1, 100) if rupees * 100 + k not in used]
        if not free:
            raise ApiError(503, "Many people are paying at this price right now. Try again in a minute.")
        paise = rupees * 100 + secrets.choice(free)
        _insert(c, oid, user_id, kind, qr_id, paise, rupees, "pending", t, t + mins * 60, None, None, snapshot, label)
    return {"id": oid, "amount_paise": paise, "status": "pending", "expires": t + mins * 60}


def create_test_order(user_id: int, paise: int) -> dict:
    """Admin payment test: ANY amount (no minimum, no maximum), goes through the same matching path as a real order."""
    if paise <= 0 or paise > 10 ** 11:
        raise ApiError(400, "Enter an amount above zero")
    t = time.time()
    oid = "QT" + secrets.token_hex(4).upper()
    with db.tx() as c:
        _expire_old(c)
        if c.execute("SELECT 1 FROM orders WHERE status='pending' AND amount_paise=?", (paise,)).fetchone():
            raise ApiError(409, "Another open order already has exactly this amount. Change the paise (for example 1.07) or wait for it to expire.")
        mins = int(config.get("payments.order_expiry_minutes", 45))
        _insert(c, oid, user_id, "test", None, paise, max(1, paise // 100), "pending", t, t + mins * 60, None, None, {"test": True}, "Payment test")
    return {"id": oid, "amount_paise": paise, "status": "pending", "expires": t + mins * 60}


def upi_link(order: dict) -> str:
    from urllib.parse import quote
    p = config.get("payments", {})
    return "upi://pay?pa=%s&pn=%s&am=%.2f&cu=INR&tn=%s" % (quote(p.get("upi_id", ""), safe="@"), quote(p.get("payee_name", "TeamDev"), safe=""),
                                                          order["amount_paise"] / 100, order["id"])


# ---------- shared finish step ----------
def _finish(c, o, pay_ref: str, via: str):
    """Mark the order paid and apply what it bought. Caller already holds the transaction and has claimed the payment row."""
    c.execute("UPDATE orders SET status='paid', paid_at=?, utr=? WHERE id=?", (time.time(), pay_ref, o["id"]))
    snap = json.loads(o["snapshot"] or "{}")
    uid = o["user_id"]
    if o["kind"] == "pass":
        days = int(config.get("pricing.pass_days", 30))
        u = c.execute("SELECT pass_until FROM users WHERE id=?", (uid,)).fetchone()
        start = max(time.time(), u["pass_until"] or 0)
        c.execute("UPDATE users SET pass_until=? WHERE id=?", (start + days * 86400, uid))
    elif snap.get("dynamic") and o["qr_id"]:
        c.execute("UPDATE qrs SET dyn_active=1 WHERE id=? AND user_id=?", (o["qr_id"], uid))
    c.execute("INSERT INTO events(ts,actor,kind,ref,ip,detail) VALUES(?,?,?,?,?,?)",
              (time.time(), "user:%d" % uid, "order_paid", o["id"], "", "via %s, ref %s, %.2f INR" % (via, pay_ref, o["amount_paise"] / 100)))


def _window_ok(p, o) -> bool:
    """Payment must be made after the order was created (2 min clock slack) and before it expired."""
    return o["created"] - 120 <= p["received_at"] <= o["expires"] + 60


def auto_match(pay_ref: str) -> bool:
    """Called when a payment email is stored. If exactly one open order fits, it is unlocked at once."""
    with db.tx() as c:
        p = c.execute("SELECT * FROM payments WHERE utr=? AND claimed_by IS NULL", (pay_ref,)).fetchone()
        if not p:
            return False
        cands = [o for o in c.execute("SELECT * FROM orders WHERE amount_paise=? AND status IN ('pending','expired') AND kind!='' ORDER BY created DESC", (p["amount_paise"],)).fetchall()
                 if _window_ok(p, o)]
        if len(cands) != 1:                       # none: wait for the customer; several: never guess
            if len(cands) > 1:
                c.execute("INSERT INTO events(ts,actor,kind,ref,ip,detail) VALUES(?,?,?,?,?,?)", (time.time(), "system", "auto_ambiguous", pay_ref, "", "%d orders share this amount" % len(cands)))
            return False
        o = cands[0]
        if c.execute("UPDATE payments SET claimed_by=? WHERE utr=? AND claimed_by IS NULL", (o["id"], pay_ref)).rowcount != 1:
            return False
        _finish(c, o, pay_ref, "auto")
        return True


def _fail(order_id, user_id, ip, why, code):
    db.log_event("user:%d" % user_id, "verify_fail", order_id, ip, why)
    raise ApiError(code, why)


def claim(order_id: str, user_id: int, ref: str, ip: str = "") -> dict:
    """Customer typed a UTR or a Fam Transaction ID. Every check must pass; the claim is atomic."""
    valid_min = int(config.get("payments.payment_valid_minutes", 120))
    ref_u = ref.strip().upper()
    with db.tx() as c:
        o = c.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user_id)).fetchone()
        if not o:
            raise ApiError(404, "Order not found")
        if o["status"] == "paid":
            return {"status": "paid"}
        if o["status"] not in ("pending", "expired"):
            raise ApiError(410, "This order is closed. Create a new one.")
        p = c.execute("SELECT * FROM payments WHERE utr=? OR (txn_id<>'' AND txn_id=?)", (ref_u, ref_u)).fetchone()
        if not p:
            raise ApiError(404, "No payment with this number yet. Fam emails can take a minute. If you paid Fam to Fam and got no UTR, use \"My payment has no UTR\".")
        if p["claimed_by"]:
            raise ApiError(409, "This payment is already used for another order. One payment unlocks one order.")
        if p["amount_paise"] != o["amount_paise"]:
            raise ApiError(422, "This payment is ₹%.2f but your order needs exactly ₹%.2f." % (p["amount_paise"] / 100, o["amount_paise"] / 100))
        if p["received_at"] < o["created"] - 120:
            raise ApiError(422, "This payment was made before the order was created. Pay the exact amount shown for this order.")
        if p["received_at"] > o["expires"] + 60 or time.time() - p["received_at"] > valid_min * 60:
            raise ApiError(422, "This payment is too old for this order. Contact support with your reference number.")
        if c.execute("UPDATE payments SET claimed_by=? WHERE utr=? AND claimed_by IS NULL", (order_id, p["utr"])).rowcount != 1:
            raise ApiError(409, "This payment is already used for another order.")
        _finish(c, o, p["utr"], "reference")
    return {"status": "paid"}


def claim_by_amount(order_id: str, user_id: int, ip: str = "") -> dict:
    """For payments that have no UTR (Fam to Fam): match by exact amount + time window. Needs exactly one candidate."""
    with db.tx() as c:
        o = c.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user_id)).fetchone()
        if not o:
            raise ApiError(404, "Order not found")
        if o["status"] == "paid":
            return {"status": "paid"}
        if o["status"] not in ("pending", "expired"):
            raise ApiError(410, "This order is closed. Create a new one.")
        others = c.execute("SELECT COUNT(*) n FROM orders WHERE amount_paise=? AND id!=? AND status IN ('pending','expired') AND created<=? AND expires>=?",
                           (o["amount_paise"], order_id, o["expires"], o["created"])).fetchone()["n"]
        cands = [p for p in c.execute("SELECT * FROM payments WHERE amount_paise=? AND claimed_by IS NULL ORDER BY received_at DESC", (o["amount_paise"],)).fetchall() if _window_ok(p, o)]
        if not cands:
            raise ApiError(404, "We have not seen a payment of exactly ₹%.2f yet. Fam emails can take 1 to 2 minutes. Try again shortly." % (o["amount_paise"] / 100))
        if len(cands) > 1 or others:
            raise ApiError(409, "More than one payment fits. Paste the UTR or Transaction ID from your email, or contact support.")
        p = cands[0]
        if c.execute("UPDATE payments SET claimed_by=? WHERE utr=? AND claimed_by IS NULL", (order_id, p["utr"])).rowcount != 1:
            raise ApiError(409, "This payment is already used for another order.")
        _finish(c, o, p["utr"], "amount")
    return {"status": "paid"}
