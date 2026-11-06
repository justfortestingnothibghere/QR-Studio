"""SQLite storage. One short-lived connection per call; WAL mode keeps readers and the payment poller from blocking each other."""
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  pw_hash TEXT NOT NULL, created REAL NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
  banned INTEGER NOT NULL DEFAULT 0, pass_until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, csrf TEXT NOT NULL,
  created REAL NOT NULL, expires REAL NOT NULL, ip TEXT, ua TEXT);
CREATE TABLE IF NOT EXISTS qrs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
  design TEXT NOT NULL, theme_id TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
  slug TEXT UNIQUE, dyn_active INTEGER NOT NULL DEFAULT 0, scans INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS qrs_user ON qrs(user_id, updated DESC);
CREATE TABLE IF NOT EXISTS user_themes(
  id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, name TEXT NOT NULL, manifest TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS logos(
  id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, qr_id INTEGER,
  amount_paise INTEGER NOT NULL, rupees INTEGER NOT NULL, status TEXT NOT NULL,
  created REAL NOT NULL, expires REAL NOT NULL, paid_at REAL, utr TEXT, snapshot TEXT, label TEXT);
CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, created DESC);
CREATE INDEX IF NOT EXISTS orders_pending ON orders(status, amount_paise);
CREATE TABLE IF NOT EXISTS payments(
  utr TEXT PRIMARY KEY, amount_paise INTEGER NOT NULL, received_at REAL NOT NULL, payer TEXT,
  source TEXT NOT NULL, claimed_by TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS downloads(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL, user_id INTEGER NOT NULL, fmt TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL,
  ref TEXT, ip TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind, ts DESC);
CREATE TABLE IF NOT EXISTS rl(k TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS rl_k ON rl(k, ts);
"""


def _path():
    return config.data_dir() / config.get("storage.database", "qrstudio.db")


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(_path(), timeout=15, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    return c


def init():
    c = connect()
    try:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(payments)").fetchall()}
        if "txn_id" not in cols:                      # older databases: add the Fam transaction id column
            c.execute("ALTER TABLE payments ADD COLUMN txn_id TEXT NOT NULL DEFAULT ''")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS payments_txn ON payments(txn_id) WHERE txn_id<>''")
        c.execute("CREATE INDEX IF NOT EXISTS payments_amt ON payments(amount_paise, claimed_by)")
    finally:
        c.close()


def log_event(actor: str, kind: str, ref: str = "", ip: str = "", detail: str = ""):
    """Append-only audit trail for payments and admin actions."""
    try:
        run("INSERT INTO events(ts,actor,kind,ref,ip,detail) VALUES(?,?,?,?,?,?)", (time.time(), actor[:80], kind[:40], ref[:80], ip[:64], detail[:400]))
    except Exception:
        pass


@contextmanager
def tx():
    """BEGIN IMMEDIATE transaction; use for anything that reads then writes (payment claims, order numbers)."""
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except BaseException:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()


def one(sql, args=()):
    c = connect()
    try:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def many(sql, args=()):
    c = connect()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def run(sql, args=()):
    c = connect()
    try:
        cur = c.execute(sql, args)
        return cur.lastrowid, cur.rowcount
    finally:
        c.close()


def now() -> float:
    return time.time()
