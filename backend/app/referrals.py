"""Invite rule: friends are counted in the order they joined, in groups of 3.
A group earns ONE free download as soon as at least one friend of that group has paid for a download.
Repeats for every group. A credit covers one download up to referral.credit_max_rupees."""
import secrets
import time

from . import config, db
from .security import ApiError

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def per_group() -> int:
    return max(1, int(config.get("referral.invites_needed", 3)))


def credit_max() -> int:
    return int(config.get("referral.credit_max_rupees", 49))


def ensure_code(uid: int) -> str:
    r = db.one("SELECT ref_code FROM users WHERE id=?", (uid,))
    if r and r["ref_code"]:
        return r["ref_code"]
    for _ in range(20):
        code = "".join(secrets.choice(ALPHABET) for _ in range(7))
        try:
            db.run("UPDATE users SET ref_code=? WHERE id=? AND ref_code IS NULL", (code, uid))
        except Exception:
            continue
        r = db.one("SELECT ref_code FROM users WHERE id=?", (uid,))
        if r and r["ref_code"]:
            return r["ref_code"]
    raise ApiError(500, "Could not create an invite code")


def find_referrer(code: str):
    code = (code or "").strip().upper()[:12]
    if not code:
        return None
    r = db.one("SELECT id FROM users WHERE ref_code=?", (code,))
    return r["id"] if r else None


def stats(uid: int) -> dict:
    n = per_group()
    rows = db.many(
        "SELECT u.id, u.name, u.created, EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status='paid' AND o.rupees>0 AND o.kind IN ('export','pass')) paid "
        "FROM users u WHERE u.referred_by=? ORDER BY u.created, u.id", (uid,))
    groups = []
    earned = 0
    for i in range(0, len(rows), n):
        g = rows[i:i + n]
        done = len(g) == n and any(x["paid"] for x in g)
        earned += 1 if done else 0
        groups.append({"joined": len(g), "paid": sum(1 for x in g if x["paid"]), "complete": done, "full": len(g) == n})
    used = (db.one("SELECT ref_credits_used u FROM users WHERE id=?", (uid,)) or {"u": 0})["u"]
    cur = next((g for g in groups if not g["complete"]), {"joined": 0, "paid": 0, "full": False, "complete": False})
    return {"per_group": n, "joined": len(rows), "paid_friends": sum(1 for x in rows if x["paid"]), "earned": earned, "used": used,
            "available": max(0, earned - used), "current": cur, "credit_max": credit_max(),
            "friends": [{"name": (x["name"].split() or ["Friend"])[0], "joined": x["created"], "paid": bool(x["paid"])} for x in rows[-20:]]}


def consume(uid: int):
    """Spend one credit atomically. Raises 409 if none is available."""
    with db.tx() as c:
        s = stats_in_tx(c, uid)
        if s["available"] < 1:
            raise ApiError(409, "You have no free download credit right now.")
        c.execute("UPDATE users SET ref_credits_used=ref_credits_used+1 WHERE id=?", (uid,))


def refund(uid: int):
    db.run("UPDATE users SET ref_credits_used=MAX(0,ref_credits_used-1) WHERE id=?", (uid,))


def stats_in_tx(c, uid: int) -> dict:
    n = per_group()
    rows = c.execute(
        "SELECT u.id, EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status='paid' AND o.rupees>0 AND o.kind IN ('export','pass')) paid "
        "FROM users u WHERE u.referred_by=? ORDER BY u.created, u.id", (uid,)).fetchall()
    earned = sum(1 for i in range(0, len(rows), n) if len(rows[i:i + n]) == n and any(x["paid"] for x in rows[i:i + n]))
    used = c.execute("SELECT ref_credits_used u FROM users WHERE id=?", (uid,)).fetchone()["u"]
    return {"earned": earned, "used": used, "available": max(0, earned - used)}
