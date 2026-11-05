"""Order creation (unique paise per open order) and UTR claim logic. All claims run inside one IMMEDIATE transaction."""
import json
import secrets
import time

from .. import config, db
from ..security import ApiError


def _expire_old(c):
    c.execute("UPDATE orders SET status='expired' WHERE status='pending' AND expires<?", (time.time(),))


def create_order(user_id: int, kind: str, rupees: int, qr_id, snapshot: dict, label: str) -> dict:
    mins = int(config.get("payments.order_expiry_minutes", 45))
    t = time.time()
    oid = "QS" + secrets.token_hex(4).upper()
    with db.tx() as c:
        _expire_old(c)
        if rupees == 0:
            c.execute("INSERT INTO orders(id,user_id,kind,qr_id,amount_paise,rupees,status,created,expires,paid_at,utr,snapshot,label) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (oid, user_id, kind, qr_id, 0, 0, "paid", t, t, t, "PASS", json.dumps(snapshot), label))
            return {"id": oid, "amount_paise": 0, "status": "paid", "expires": t}
        used = {r["amount_paise"] for r in c.execute("SELECT amount_paise FROM orders WHERE status='pending' AND amount_paise BETWEEN ? AND ?",
                                                      (rupees * 100, rupees * 100 + 99)).fetchall()}
        free = [k for k in range(1, 100) if rupees * 100 + k not in used]
        if not free:
            raise ApiError(503, "Many people are paying at this price right now. Try again in a minute.")
        paise = rupees * 100 + secrets.choice(free)
        c.execute("INSERT INTO orders(id,user_id,kind,qr_id,amount_paise,rupees,status,created,expires,paid_at,utr,snapshot,label) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (oid, user_id, kind, qr_id, paise, rupees, "pending", t, t + mins * 60, None, None, json.dumps(snapshot), label))
    return {"id": oid, "amount_paise": paise, "status": "pending", "expires": t + mins * 60}


def upi_link(order: dict) -> str:
    from urllib.parse import quote
    p = config.get("payments", {})
    return "upi://pay?pa=%s&pn=%s&am=%.2f&cu=INR&tn=%s" % (quote(p.get("upi_id", ""), safe="@"), quote(p.get("payee_name", "TeamDev"), safe=""),
                                                          order["amount_paise"] / 100, order["id"])


def claim(order_id: str, user_id: int, utr: str) -> dict:
    """Match a user supplied UTR against a stored payment. Every check must pass; the claim is atomic."""
    valid_min = int(config.get("payments.payment_valid_minutes", 120))
    with db.tx() as c:
        o = c.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (order_id, user_id)).fetchone()
        if not o:
            raise ApiError(404, "Order not found")
        if o["status"] == "paid":
            return {"status": "paid"}
        if o["status"] != "pending" or o["expires"] < time.time():
            c.execute("UPDATE orders SET status='expired' WHERE id=? AND status='pending'", (order_id,))
            raise ApiError(410, "This order expired. Create a new one.")
        p = c.execute("SELECT * FROM payments WHERE utr=?", (utr,)).fetchone()
        if not p:
            raise ApiError(404, "No payment with this UTR yet. Fam emails can take a minute, try again shortly.")
        if p["claimed_by"]:
            raise ApiError(409, "This UTR is already used for another order. One payment unlocks one order.")
        if p["amount_paise"] != o["amount_paise"]:
            raise ApiError(422, "This payment is ₹%.2f but your order needs exactly ₹%.2f." % (p["amount_paise"] / 100, o["amount_paise"] / 100))
        if p["received_at"] < o["created"] - 120:
            raise ApiError(422, "This payment was made before the order was created. Pay the exact amount shown for this order.")
        if time.time() - p["received_at"] > valid_min * 60:
            raise ApiError(422, "This payment is older than %d minutes. Contact support with your UTR." % valid_min)
        n = c.execute("UPDATE payments SET claimed_by=? WHERE utr=? AND claimed_by IS NULL", (order_id, utr)).rowcount
        if n != 1:
            raise ApiError(409, "This UTR is already used for another order.")
        c.execute("UPDATE orders SET status='paid', paid_at=?, utr=? WHERE id=?", (time.time(), utr, order_id))
        snap = json.loads(o["snapshot"] or "{}")
        if o["kind"] == "pass":
            days = int(config.get("pricing.pass_days", 30))
            u = c.execute("SELECT pass_until FROM users WHERE id=?", (user_id,)).fetchone()
            start = max(time.time(), u["pass_until"] or 0)
            c.execute("UPDATE users SET pass_until=? WHERE id=?", (start + days * 86400, user_id))
        elif snap.get("dynamic") and o["qr_id"]:
            c.execute("UPDATE qrs SET dyn_active=1 WHERE id=? AND user_id=?", (o["qr_id"], user_id))
    return {"status": "paid"}
