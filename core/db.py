"""Database connection, session management, and schema."""
import os, sqlite3, secrets, threading, json

PORT     = int(os.environ.get("PORT", 8014))
BP       = os.environ.get("BASE_PATH", "").rstrip("/")
DATA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DB_PATH   = os.path.join(DATA_DIR, "nuvodesk.db")
FILES_DIR = os.path.join(DATA_DIR, "files")
os.makedirs(DATA_DIR,  exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

# ── sessions ──────────────────────────────────────────────────────────────────
_sessions: dict = {}
_slock = threading.Lock()

def new_sess(user: dict) -> str:
    tok = secrets.token_hex(24)
    with _slock:
        _sessions[tok] = dict(user)
    return tok

def get_sess(h) -> dict | None:
    for part in h.headers.get("Cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() == "nd_sess":
            with _slock:
                return _sessions.get(v.strip())
    return None

def del_sess(h):
    for part in h.headers.get("Cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() == "nd_sess":
            with _slock:
                _sessions.pop(v.strip(), None)

# ── database ──────────────────────────────────────────────────────────────────
_dbconn: sqlite3.Connection | None = None
_dblock = threading.Lock()

def db() -> sqlite3.Connection:
    global _dbconn
    if _dbconn is None:
        _dbconn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _dbconn.row_factory = sqlite3.Row
        _dbconn.execute("PRAGMA journal_mode=WAL")
        _dbconn.execute("PRAGMA foreign_keys=ON")
    return _dbconn

def q(sql, params=()):
    with _dblock:
        return db().execute(sql, params).fetchall()

def q1(sql, params=()):
    with _dblock:
        return db().execute(sql, params).fetchone()

def run(sql, params=()):
    with _dblock:
        c = db().execute(sql, params)
        db().commit()
        return c.lastrowid

def rs(rows) -> list:
    return [dict(r) for r in rows] if rows else []

def r2d(row) -> dict | None:
    return dict(row) if row else None
