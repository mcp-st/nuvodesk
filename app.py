#!/usr/bin/env python3
"""NuvoDesk v2 — Nuvolink field project & materials management."""

import os, json, sqlite3, hashlib, secrets, threading, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote_plus
from datetime import datetime, date as _date

PORT     = int(os.environ.get("PORT", 8014))
BP       = os.environ.get("BASE_PATH", "").rstrip("/")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH  = os.path.join(DATA_DIR, "nuvodesk.db")
os.makedirs(DATA_DIR, exist_ok=True)

# ── sessions ──────────────────────────────────────────────────────────────────
_sessions: dict = {}
_slock = threading.Lock()

def _new_sess(user: dict) -> str:
    tok = secrets.token_hex(24)
    with _slock:
        _sessions[tok] = dict(user)
    return tok

def _get_sess(h) -> dict | None:
    for part in h.headers.get("Cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() == "nd_sess":
            with _slock:
                return _sessions.get(v.strip())
    return None

def _del_sess(h):
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

# ── schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT UNIQUE NOT NULL,
    pw_hash      TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'technician',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    client          TEXT NOT NULL,
    description     TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    priority        TEXT NOT NULL DEFAULT 'normal',
    address         TEXT DEFAULT '',
    reference       TEXT DEFAULT '',
    contact_name    TEXT DEFAULT '',
    contact_phone   TEXT DEFAULT '',
    estimated_hours REAL DEFAULT 0,
    start_date      TEXT DEFAULT '',
    due_date        TEXT DEFAULT '',
    completed_date  TEXT DEFAULT '',
    assigned_to     INTEGER REFERENCES users(id),
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    description    TEXT DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    priority       TEXT NOT NULL DEFAULT 'normal',
    assigned_to    INTEGER REFERENCES users(id),
    due_date       TEXT DEFAULT '',
    completed_date TEXT DEFAULT '',
    created_by     INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS task_checklist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    pos        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS materials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    unit            TEXT NOT NULL DEFAULT 'ud',
    stock_warehouse INTEGER NOT NULL DEFAULT 0,
    stock_field     INTEGER NOT NULL DEFAULT 0,
    stock_min       INTEGER NOT NULL DEFAULT 0,
    category        TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS assignments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    material_id   INTEGER NOT NULL REFERENCES materials(id),
    qty_requested INTEGER NOT NULL DEFAULT 0,
    qty_assigned  INTEGER NOT NULL DEFAULT 0,
    qty_consumed  INTEGER NOT NULL DEFAULT 0,
    qty_returned  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'requested',
    notes         TEXT DEFAULT '',
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS project_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    body       TEXT NOT NULL,
    hours      REAL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tech_kit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    qty         INTEGER NOT NULL DEFAULT 0,
    notes       TEXT DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, material_id)
);
CREATE TABLE IF NOT EXISTS stock_movements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    qty         INTEGER NOT NULL,
    direction   TEXT NOT NULL,
    source      TEXT DEFAULT '',
    ref_id      INTEGER DEFAULT 0,
    user_id     INTEGER REFERENCES users(id),
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

MIGRATIONS = [
    "ALTER TABLE projects ADD COLUMN reference TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN contact_name TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN contact_phone TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN estimated_hours REAL DEFAULT 0",
]

def init_db():
    with _dblock:
        db().executescript(SCHEMA)
        db().commit()
        for m in MIGRATIONS:
            try:
                db().execute(m)
                db().commit()
            except sqlite3.OperationalError:
                pass
        if db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            db().execute(
                "INSERT INTO users (username,pw_hash,display_name,role) VALUES (?,?,?,?)",
                ("admin", _hash("admin"), "Administrador", "admin"))
            db().commit()

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _esc(s) -> str:
    if s is None: return ""
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def _stock_move(material_id, qty, direction, source, ref_id, user_id, notes=""):
    run("INSERT INTO stock_movements (material_id,qty,direction,source,ref_id,user_id,notes) VALUES (?,?,?,?,?,?,?)",
        (material_id, qty, direction, source, ref_id, user_id, notes))

STATUS_LABEL = {
    "active":"Activo","paused":"Pausado","completed":"Completado","cancelled":"Cancelado",
    "pending":"Pendiente","in_progress":"En curso","done":"Hecho","blocked":"Bloqueado",
    "requested":"Solicitado","assigned":"Asignado","consumed":"Consumido",
    "returned":"Devuelto","partial":"Parcial"
}
STATUS_COLOR = {
    "active":"#15803d","paused":"#b45309","completed":"#1558c2","cancelled":"#6b7280",
    "pending":"#64748b","in_progress":"#1558c2","done":"#15803d","blocked":"#dc2626",
    "requested":"#b45309","assigned":"#1558c2","consumed":"#15803d",
    "returned":"#6d28d9","partial":"#b45309"
}
PRIORITY_COLOR = {"low":"#64748b","normal":"#1558c2","high":"#b45309","urgent":"#dc2626"}

def _badge(status, text=None):
    t = text or STATUS_LABEL.get(status, status)
    c = STATUS_COLOR.get(status, "#64748b")
    return f'<span class="badge" style="background:{c}22;color:{c}">{_esc(t)}</span>'

def _pbadge(priority):
    labels = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}
    t = labels.get(priority, priority)
    c = PRIORITY_COLOR.get(priority, "#64748b")
    return f'<span style="color:{c};font-size:.78rem;font-weight:600">▲ {t}</span>'

# ── CSS ───────────────────────────────────────────────────────────────────────
def _css():
    return """
:root{
  --bg:#f0f4f8;--bg2:#fff;--bg3:#f8fafc;--bg4:#eef2f7;
  --text:#1a2536;--muted:#64748b;--border:#dce4ee;
  --blue:#1558c2;--blue-dim:rgba(21,88,194,.08);
  --green:#15803d;--green-dim:rgba(21,128,61,.1);
  --amber:#b45309;--amber-dim:rgba(180,83,9,.08);
  --red:#dc2626;--red-dim:rgba(220,38,38,.08);
  --violet:#6d28d9;--violet-dim:rgba(109,40,217,.08);
  --teal:#0d9488;
  --side-bg:#192e4a;--side-text:#c8d8ec;--sidebar-w:220px;
  --radius:8px;--shadow:0 1px 4px rgba(0,0,0,.08);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;
  background:var(--bg);color:var(--text);display:flex;min-height:100vh}
a{color:var(--blue);text-decoration:none}
button{font-family:inherit;cursor:pointer}

/* ── sidebar ── */
#sidebar{width:var(--sidebar-w);background:var(--side-bg);color:var(--side-text);
  display:flex;flex-direction:column;min-height:100vh;
  position:fixed;top:0;left:0;z-index:200;transition:transform .22s ease}
#sidebar .logo{padding:20px 16px 12px;font-size:1.15rem;font-weight:700;
  color:#fff;border-bottom:1px solid rgba(255,255,255,.08)}
#sidebar .logo span{color:#4db6ac;font-size:.65rem;display:block;letter-spacing:1.5px;margin-top:2px}
#sidebar nav{flex:1;padding:10px 0;overflow-y:auto}
#sidebar nav a{display:flex;align-items:center;gap:10px;padding:10px 18px;
  color:var(--side-text);font-size:.88rem;border-left:3px solid transparent;transition:.15s}
#sidebar nav a:hover,#sidebar nav a.active{background:rgba(255,255,255,.1);color:#fff;
  border-left-color:#4db6ac}
#sidebar nav a .ic{width:20px;text-align:center;font-size:1rem;flex-shrink:0}
#sidebar .user-area{padding:14px 16px;border-top:1px solid rgba(255,255,255,.08);font-size:.8rem}
#sidebar .user-area strong{color:#fff;display:block;margin-bottom:2px}
#sidebar .user-area a{color:#94a3b8;font-size:.75rem}

/* ── overlay (mobile) ── */
#overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:199}
#overlay.open{display:block}

/* ── main ── */
#main{margin-left:var(--sidebar-w);flex:1;padding:26px 30px;min-width:0}

/* ── bottom nav (mobile only) ── */
#bottom-nav{display:none}

/* ── headings ── */
h1{font-size:1.35rem;font-weight:700;color:var(--text);margin-bottom:20px}
h2{font-size:1.05rem;font-weight:700;margin-bottom:14px}
h3{font-size:.92rem;font-weight:700;margin-bottom:8px}

/* ── cards ── */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
  padding:20px;margin-bottom:18px;box-shadow:var(--shadow)}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px;margin-bottom:22px}
.kpi{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px 18px;box-shadow:var(--shadow)}
.kpi .val{font-size:1.9rem;font-weight:700;line-height:1}
.kpi .lbl{font-size:.75rem;color:var(--muted);margin-top:5px;text-transform:uppercase;letter-spacing:.4px}

/* ── table ── */
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.72rem;font-weight:600;color:var(--muted);
  text-transform:uppercase;letter-spacing:.5px;padding:8px 12px;
  border-bottom:2px solid var(--border);background:var(--bg3);white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafbfd}

/* ── buttons ── */
.btn{display:inline-flex;align-items:center;gap:5px;padding:7px 14px;
  border-radius:6px;font-size:.83rem;font-weight:600;border:none;transition:opacity .15s,transform .1s}
.btn:active{transform:scale(.97)}
.btn:hover{opacity:.85}
.btn-primary{background:var(--blue);color:#fff}
.btn-success{background:var(--green);color:#fff}
.btn-danger{background:var(--red);color:#fff}
.btn-amber{background:var(--amber);color:#fff}
.btn-ghost{background:transparent;color:var(--blue);border:1px solid var(--blue)}
.btn-sm{padding:4px 10px;font-size:.78rem}
.btn-icon{padding:5px 8px;font-size:.9rem;line-height:1}

/* ── form ── */
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.form-row.cols3{grid-template-columns:1fr 1fr 1fr}
.form-row.single{grid-template-columns:1fr}
.field{margin-bottom:14px}
label{display:block;font-size:.78rem;font-weight:600;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.3px}
input,select,textarea{width:100%;padding:8px 10px;border:1px solid var(--border);
  border-radius:6px;font-size:.88rem;background:var(--bg3);color:var(--text);outline:none;
  transition:border-color .15s}
input:focus,select:focus,textarea:focus{border-color:var(--blue);background:#fff;
  box-shadow:0 0 0 3px var(--blue-dim)}
textarea{resize:vertical;min-height:70px}

/* ── modal ── */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);
  z-index:500;align-items:center;justify-content:center;padding:16px}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:10px;padding:26px;width:min(580px,100%);
  max-height:92vh;overflow-y:auto;box-shadow:0 8px 40px rgba(0,0,0,.2)}
.modal h2{margin-bottom:18px;font-size:1.1rem}
.modal-foot{display:flex;justify-content:flex-end;gap:10px;margin-top:20px;
  padding-top:16px;border-top:1px solid var(--border)}

/* ── tabs ── */
.tabs{display:flex;gap:2px;margin-bottom:20px;border-bottom:2px solid var(--border)}
.tab-btn{background:none;border:none;padding:10px 18px;font-size:.88rem;font-weight:600;
  color:var(--muted);border-bottom:3px solid transparent;margin-bottom:-2px;
  cursor:pointer;transition:color .15s}
.tab-btn.active{color:var(--blue);border-bottom-color:var(--blue)}
.tab-pane{display:none}
.tab-pane.active{display:block}

/* ── toolbar ── */
.toolbar{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:16px;flex-wrap:wrap;gap:10px}
.toolbar-left{display:flex;align-items:center;gap:8px;flex-wrap:wrap}

/* ── badge ── */
.badge{padding:2px 9px;border-radius:12px;font-size:.75rem;font-weight:600}
.chip{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75rem;
  font-weight:600;background:var(--blue-dim);color:var(--blue);white-space:nowrap}

/* ── alerts ── */
.alert{padding:10px 14px;border-radius:6px;margin-bottom:14px;font-size:.88rem}
.alert-red{background:var(--red-dim);color:var(--red);border-left:3px solid var(--red)}
.alert-amber{background:var(--amber-dim);color:var(--amber);border-left:3px solid var(--amber)}
.alert-green{background:var(--green-dim);color:var(--green);border-left:3px solid var(--green)}

/* ── timeline (work log) ── */
.timeline{list-style:none}
.timeline li{display:flex;gap:12px;padding-bottom:16px;position:relative}
.timeline li:not(:last-child)::before{content:'';position:absolute;left:15px;top:32px;
  bottom:0;width:2px;background:var(--border)}
.tl-dot{width:32px;height:32px;border-radius:50%;background:var(--blue-dim);
  color:var(--blue);display:flex;align-items:center;justify-content:center;
  font-size:.8rem;font-weight:700;flex-shrink:0}
.tl-body{flex:1;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius);padding:10px 14px}
.tl-meta{font-size:.75rem;color:var(--muted);margin-bottom:4px}
.tl-hours{float:right;background:var(--blue-dim);color:var(--blue);
  padding:1px 7px;border-radius:10px;font-size:.72rem;font-weight:700}
.tl-text{line-height:1.5;white-space:pre-wrap;word-break:break-word}

/* ── checklist ── */
.checklist{list-style:none}
.checklist li{display:flex;align-items:center;gap:8px;padding:6px 0;
  border-bottom:1px solid var(--border)}
.checklist li:last-child{border-bottom:none}
.checklist input[type=checkbox]{width:16px;height:16px;cursor:pointer;accent-color:var(--green)}
.checklist .cl-label{flex:1;font-size:.88rem}
.checklist li.done .cl-label{text-decoration:line-through;color:var(--muted)}
.checklist .cl-del{background:none;border:none;color:var(--muted);cursor:pointer;
  font-size:1rem;padding:2px 4px}
.checklist .cl-del:hover{color:var(--red)}

/* ── kit card ── */
.kit-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px;box-shadow:var(--shadow)}
.kit-card h3{font-size:.9rem;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.kit-card h3 .role-badge{font-size:.65rem;padding:2px 6px;border-radius:8px;
  font-weight:600;background:var(--blue-dim);color:var(--blue)}

/* ── stock movement indicator ── */
.mv-in{color:var(--green);font-weight:700}
.mv-out{color:var(--red);font-weight:700}

/* ── progress bar ── */
.progress{background:#e2e8f0;border-radius:4px;height:6px;overflow:hidden}
.progress-bar{height:100%;border-radius:4px;background:var(--blue);transition:width .3s}

/* ── misc ── */
.muted{color:var(--muted)}
.text-red{color:var(--red)}
.text-green{color:var(--green)}
.text-amber{color:var(--amber)}
.fw7{font-weight:700}
.sep{color:var(--border);margin:0 6px}
.add-row-form{display:flex;gap:8px;margin-top:12px}
.add-row-form input{flex:1}

/* ── responsive ── */
@media(max-width:768px){
  #sidebar{transform:translateX(-100%)}
  #sidebar.open{transform:translateX(0)}
  #main{margin-left:0;padding:14px 14px 80px}
  #bottom-nav{
    display:flex;position:fixed;bottom:0;left:0;right:0;
    background:var(--side-bg);z-index:200;
    padding:6px 0 max(6px,env(safe-area-inset-bottom));
    border-top:1px solid rgba(255,255,255,.1);
    justify-content:space-around
  }
  #bottom-nav a{display:flex;flex-direction:column;align-items:center;
    gap:2px;color:var(--side-text);font-size:.58rem;font-weight:600;
    padding:4px 8px;text-decoration:none;letter-spacing:.3px}
  #bottom-nav a .ic{font-size:1.3rem;line-height:1}
  #bottom-nav a.active{color:#4db6ac}
  .card-grid{grid-template-columns:repeat(2,1fr)}
  .form-row,.form-row.cols3{grid-template-columns:1fr}
  .col-m-hide{display:none!important}
  h1{font-size:1.15rem;margin-bottom:14px}
  .modal{padding:18px;border-radius:8px}
  .tabs{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .tab-btn{white-space:nowrap;padding:8px 12px;font-size:.82rem}
}
  /* kanban mobile: horizontal scroll */
  .kanban{grid-template-columns:repeat(4,80vw)!important;overflow-x:auto;
    scroll-snap-type:x mandatory;padding-bottom:8px;gap:10px!important}
  .kanban-col{scroll-snap-align:start;min-width:0}
  .proj-cards{grid-template-columns:repeat(auto-fill,minmax(260px,300px))!important}
}
@media(min-width:769px){
  #menu-btn{display:none!important}
}
#menu-btn{position:fixed;top:10px;left:10px;z-index:210;
  background:var(--side-bg);color:#fff;border:none;border-radius:6px;
  width:38px;height:38px;font-size:1.1rem;display:flex;align-items:center;justify-content:center}

/* ── kanban board ── */
.kanban{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;align-items:start;margin-bottom:20px}
.kanban-col{background:var(--bg4);border-radius:var(--radius);padding:12px;
  min-height:180px;transition:background .15s}
.kanban-col.drag-over{background:var(--blue-dim);outline:2px dashed var(--blue)}
.kanban-col-hd{display:flex;align-items:center;justify-content:space-between;
  padding-bottom:10px;border-bottom:2px solid var(--border);margin-bottom:10px}
.kanban-col-hd .col-title{font-size:.75rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;display:flex;align-items:center;gap:7px}
.kanban-col-hd .col-count{background:var(--bg2);border:1px solid var(--border);
  border-radius:10px;padding:1px 7px;font-size:.72rem;font-weight:700;color:var(--muted)}
.kanban-cards{min-height:60px}
.task-card{background:#fff;border:1px solid var(--border);border-radius:7px;
  padding:11px 13px;margin-bottom:8px;cursor:grab;box-shadow:0 1px 3px rgba(0,0,0,.06);
  user-select:none;transition:box-shadow .15s,transform .1s;position:relative}
.task-card:hover{box-shadow:0 3px 10px rgba(0,0,0,.1)}
.task-card.dragging{opacity:.45;transform:rotate(1.5deg);box-shadow:0 6px 20px rgba(0,0,0,.18);cursor:grabbing}
.task-card-title{font-weight:600;font-size:.87rem;line-height:1.35;margin-bottom:6px}
.task-card-foot{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:7px}
.task-card-strip{position:absolute;left:0;top:0;bottom:0;width:4px;border-radius:7px 0 0 7px}
.task-card-inner{padding-left:8px}
.kanban-add{width:100%;background:none;border:1px dashed var(--border);border-radius:6px;
  padding:7px;font-size:.8rem;color:var(--muted);cursor:pointer;margin-top:6px;transition:.15s}
.kanban-add:hover{background:var(--bg2);color:var(--blue);border-color:var(--blue)}

/* ── project cards (grid view) ── */
.proj-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,300px));
  justify-content:start;gap:16px;margin-bottom:20px}
.proj-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius);
  overflow:hidden;box-shadow:var(--shadow);transition:box-shadow .15s,transform .1s;
  display:flex;flex-direction:column;text-decoration:none;color:var(--text);width:100%}
.proj-card:hover{box-shadow:0 6px 20px rgba(0,0,0,.1);transform:translateY(-2px)}
.proj-card-strip{height:5px}
.proj-card-body{padding:14px 16px;flex:1}
.proj-card-name{font-weight:700;font-size:.97rem;margin-bottom:2px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.proj-card-client{font-size:.77rem;color:var(--muted);margin-bottom:10px}
.proj-card-tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.proj-card-prog{margin-top:8px}
.proj-card-prog-label{font-size:.72rem;color:var(--muted);margin-bottom:3px;
  display:flex;justify-content:space-between}
.proj-card-foot{padding:9px 16px;border-top:1px solid var(--border);
  background:var(--bg3);display:flex;align-items:center;
  justify-content:space-between;font-size:.75rem;color:var(--muted)}

/* ── view toggle ── */
.view-toggle{display:inline-flex;border:1px solid var(--border);border-radius:6px;overflow:hidden}
.view-toggle button{background:none;border:none;padding:6px 12px;font-size:.8rem;
  cursor:pointer;color:var(--muted);transition:.15s}
.view-toggle button.active{background:var(--blue);color:#fff}
"""

# ── shell ─────────────────────────────────────────────────────────────────────
def _shell(page, user, content, extra_head=""):
    bp = BP
    nav = [
        ("dashboard", f"{bp}/",          "⊞",  "Dashboard"),
        ("projects",  f"{bp}/projects",  "📋", "Proyectos"),
        ("inventory", f"{bp}/inventory", "📦", "Inventario"),
        ("kit",       f"{bp}/kit",       "🎒", "Kit campo"),
        ("users",     f"{bp}/users",     "👥", "Usuarios"),
    ]
    sidebar_links = ""
    bottom_links = ""
    for key, url, ic, label in nav:
        if key == "users" and user.get("role") != "admin":
            continue
        cls = ' class="active"' if page == key else ""
        sidebar_links += f'<a href="{url}"{cls}><span class="ic">{ic}</span>{label}</a>\n'
        bottom_links  += f'<a href="{url}"{cls}><span class="ic">{ic}</span>{label}</a>\n'

    role_lbl = {"admin":"Admin","technician":"Técnico","backoffice":"Backoffice"}.get(
        user.get("role",""), user.get("role",""))

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>NuvoDesk</title>
<style>{_css()}</style>
{extra_head}
</head>
<body>
<button id="menu-btn" onclick="toggleSidebar()" aria-label="Menú">☰</button>
<div id="overlay" onclick="closeSidebar()"></div>
<div id="sidebar">
  <div class="logo">NuvoDesk<span>NUVOLINK TELECOMS</span></div>
  <nav>{sidebar_links}</nav>
  <div class="user-area">
    <strong>{_esc(user.get('display_name',''))}</strong>
    {_esc(role_lbl)} &nbsp;&middot;&nbsp; <a href="{bp}/logout">Salir</a>
  </div>
</div>
<div id="main">{content}</div>
<nav id="bottom-nav">{bottom_links}</nav>
<script>
function toggleSidebar(){{
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('overlay').classList.toggle('open');
}}
function closeSidebar(){{
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('overlay').classList.remove('open');
}}
// close sidebar on nav click (mobile)
document.querySelectorAll('#sidebar nav a').forEach(function(a){{
  a.addEventListener('click', function(){{
    if(window.innerWidth<=768) closeSidebar();
  }});
}});
</script>
</body>
</html>"""

# ── login ─────────────────────────────────────────────────────────────────────
def _login_page(err=""):
    err_html = f'<div class="alert alert-red">{_esc(err)}</div>' if err else ""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NuvoDesk</title>
<style>
{_css()}
body{{display:flex;align-items:center;justify-content:center;min-height:100vh}}
.login-box{{background:#fff;border:1px solid var(--border);border-radius:12px;
  padding:36px 32px;width:min(360px,94vw);box-shadow:0 4px 24px rgba(0,0,0,.1)}}
.login-box h1{{text-align:center;margin-bottom:4px;font-size:1.3rem}}
.login-box .sub{{text-align:center;color:var(--muted);font-size:.82rem;margin-bottom:26px}}
.login-box .btn{{width:100%;justify-content:center;padding:10px;font-size:.9rem}}
</style>
</head>
<body>
<div class="login-box">
  <h1>NuvoDesk</h1>
  <p class="sub">Nuvolink — gestión de proyectos de campo</p>
  {err_html}
  <form method="POST" action="{BP}/api/login">
    <div class="field"><label>Usuario</label>
      <input name="username" autofocus autocomplete="username"></div>
    <div class="field"><label>Contraseña</label>
      <input type="password" name="password" autocomplete="current-password"></div>
    <button type="submit" class="btn btn-primary">Entrar</button>
  </form>
</div>
</body></html>"""

# ── dashboard ─────────────────────────────────────────────────────────────────
def _dashboard(user):
    ps = r2d(q1("""SELECT COUNT(*) t,
        SUM(CASE WHEN status='active'    THEN 1 ELSE 0 END) active,
        SUM(CASE WHEN status='paused'    THEN 1 ELSE 0 END) paused,
        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) done
        FROM projects"""))
    ts = r2d(q1("""SELECT COUNT(*) t,
        SUM(CASE WHEN status='done'    THEN 1 ELSE 0 END) done,
        SUM(CASE WHEN status='blocked' THEN 1 ELSE 0 END) blocked
        FROM tasks"""))
    ps = ps or {}; ts = ts or {}

    low_stock = rs(q("""SELECT * FROM materials WHERE stock_warehouse<=stock_min AND stock_min>0
        ORDER BY (stock_warehouse-stock_min) ASC LIMIT 5"""))

    overdue = rs(q("""SELECT t.title,t.due_date,t.status,p.id pid,p.name pname
        FROM tasks t JOIN projects p ON p.id=t.project_id
        WHERE t.status NOT IN ('done','cancelled') AND t.due_date!='' AND t.due_date<date('now')
        ORDER BY t.due_date ASC LIMIT 6"""))

    recent = rs(q("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to
        ORDER BY p.updated_at DESC LIMIT 8"""))

    kit_empty = rs(q("""SELECT u.display_name,COUNT(k.id) items
        FROM users u LEFT JOIN tech_kit k ON k.user_id=u.id AND k.qty>0
        WHERE u.active=1 AND u.role IN ('technician','admin')
        GROUP BY u.id HAVING items=0"""))

    kpis = f"""<div class="card-grid">
  <div class="kpi"><div class="val">{ps.get('t',0)}</div><div class="lbl">Proyectos</div></div>
  <div class="kpi"><div class="val text-green">{ps.get('active',0)}</div><div class="lbl">Activos</div></div>
  <div class="kpi"><div class="val text-amber">{ps.get('paused',0)}</div><div class="lbl">Pausados</div></div>
  <div class="kpi"><div class="val" style="color:var(--blue)">{ps.get('done',0)}</div><div class="lbl">Completados</div></div>
  <div class="kpi"><div class="val">{ts.get('t',0)}</div><div class="lbl">Tareas</div></div>
  <div class="kpi"><div class="val text-red">{ts.get('blocked',0)}</div><div class="lbl">Bloqueadas</div></div>
</div>"""

    low_html = ""
    if low_stock:
        rows = "".join(f"<tr><td><span class='chip'>{_esc(m['code'])}</span></td>"
            f"<td>{_esc(m['name'])}</td>"
            f"<td class='text-red fw7'>{m['stock_warehouse']}</td>"
            f"<td class='muted'>{m['stock_min']}</td>"
            f"<td class='muted'>{_esc(m['unit'])}</td></tr>" for m in low_stock)
        low_html = f"""<div class="card" style="border-left:4px solid var(--amber)">
  <h2>⚠️ Stock crítico ({len(low_stock)})</h2>
  <div class="tbl-wrap"><table><thead><tr><th>Código</th><th>Material</th>
    <th>Almacén</th><th>Mínimo</th><th>Ud</th></tr></thead><tbody>{rows}</tbody></table></div>
</div>"""

    od_html = ""
    if overdue:
        rows = "".join(f"<tr>"
            f"<td><a href='{BP}/projects/{t['pid']}'>{_esc(t['pname'])}</a></td>"
            f"<td>{_esc(t['title'])}</td>"
            f"<td class='text-red'>{_esc(t['due_date'])}</td>"
            f"<td>{_badge(t['status'])}</td></tr>" for t in overdue)
        od_html = f"""<div class="card" style="border-left:4px solid var(--red)">
  <h2>🕒 Tareas vencidas ({len(overdue)})</h2>
  <div class="tbl-wrap"><table><thead><tr><th>Proyecto</th><th>Tarea</th>
    <th>Vencimiento</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div>
</div>"""

    kit_html = ""
    if kit_empty:
        names = ", ".join(_esc(k['display_name']) for k in kit_empty)
        kit_html = f'<div class="alert alert-amber">🎒 Técnicos sin kit configurado: {names}</div>'

    rp_rows = "".join(f"<tr>"
        f"<td><a href='{BP}/projects/{p['id']}' class='fw7'>{_esc(p['name'])}</a>"
        f"<br><span class='muted' style='font-size:.75rem'>{_esc(p['client'])}</span></td>"
        f"<td>{_badge(p['status'])}</td><td class='col-m-hide'>{_pbadge(p['priority'])}</td>"
        f"<td class='muted col-m-hide'>{_esc(p['tech'] or '—')}</td>"
        f"<td class='muted col-m-hide'>{_esc((p['due_date'] or '—')[:10])}</td></tr>" for p in recent)

    rp_html = f"""<div class="card">
  <div class="toolbar"><h2>Proyectos recientes</h2>
    <a href="{BP}/projects" class="btn btn-ghost btn-sm">Ver todos →</a></div>
  <div class="tbl-wrap"><table><thead><tr><th>Proyecto</th><th>Estado</th>
    <th class="col-m-hide">Prioridad</th><th class="col-m-hide">Técnico</th>
    <th class="col-m-hide">Límite</th></tr></thead><tbody>{rp_rows}</tbody></table></div>
</div>"""

    content = f"<h1>Dashboard</h1>{kit_html}{kpis}{low_html}{od_html}{rp_html}"
    return _shell("dashboard", user, content)

# ── projects list ─────────────────────────────────────────────────────────────
def _projects_page(user, filter_status="", view="cards"):
    where = "WHERE p.status=?" if filter_status else ""
    params = (filter_status,) if filter_status else ()
    projects = rs(q(f"""SELECT p.*,u.display_name tech,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id) task_t,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') task_d
        FROM projects p LEFT JOIN users u ON u.id=p.assigned_to
        {where}
        ORDER BY CASE p.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
          WHEN 'normal' THEN 2 ELSE 3 END, p.updated_at DESC""", params))

    techs = rs(q("SELECT id,display_name FROM users WHERE active=1 ORDER BY display_name"))
    tech_opts = "".join(f'<option value="{t["id"]}">{_esc(t["display_name"])}</option>' for t in techs)

    fbtn = lambda s, l: (f'<a href="{BP}/projects{"?status="+s if s else ""}{"&view="+view if view else ""}" '
        f'class="btn btn-sm {"btn-primary" if filter_status==s else "btn-ghost"}">{l}</a>')
    filters = (fbtn("","Todos")+fbtn("active","Activos")+fbtn("paused","Pausados")
               +fbtn("completed","Completados")+fbtn("cancelled","Cancelados"))

    strip_color = {"active":"#15803d","paused":"#b45309","completed":"#1558c2",
                   "cancelled":"#94a3b8","":  "#94a3b8"}

    # ── card view ──
    cards_html = ""
    for p in projects:
        pct = int(p['task_d']/p['task_t']*100) if p['task_t'] else 0
        sc = strip_color.get(p['status'], "#94a3b8")
        pc = PRIORITY_COLOR.get(p['priority'], "#64748b")
        ref_chip = f'<span class="chip" style="background:#f1f5f9;color:#64748b">#{_esc(p["reference"])}</span>' if p.get("reference") else ""
        due_html = f'🗓 {_esc(p["due_date"][:10])}' if p.get("due_date") else ""
        tech_html = f'👤 {_esc(p["tech"])}' if p.get("tech") else ""
        plabel = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(p["priority"],"")
        prog_html = ""
        if p["task_t"]:
            prog_html = (f'<div class="proj-card-prog">'
                f'<div class="proj-card-prog-label">'
                f'<span>Tareas</span><span>{p["task_d"]}/{p["task_t"]}</span></div>'
                f'<div class="progress"><div class="progress-bar" style="width:{pct}%"></div></div></div>')
        cards_html += (
            f'<a class="proj-card" href="{BP}/projects/{p["id"]}">'
            f'<div class="proj-card-strip" style="background:{sc}"></div>'
            f'<div class="proj-card-body">'
            f'<div class="proj-card-name">{_esc(p["name"])}</div>'
            f'<div class="proj-card-client">{_esc(p["client"])}</div>'
            f'<div class="proj-card-tags">'
            f'{_badge(p["status"])}'
            f'<span style="color:{pc};font-size:.75rem;font-weight:700">▲ {plabel}</span>'
            f'{ref_chip}</div>'
            f'{prog_html}'
            f'</div>'
            f'<div class="proj-card-foot">'
            f'<span>{due_html}</span><span>{tech_html}</span>'
            f'<button onclick="event.preventDefault();event.stopPropagation();editProject({json.dumps(dict(p))})" '
            f'class="btn btn-ghost btn-icon">✏️</button>'
            f'</div></a>')

    # ── table view ──
    rows = ""
    for p in projects:
        pct = int(p['task_d']/p['task_t']*100) if p['task_t'] else 0
        prog = (f'<div class="progress" style="width:70px;display:inline-block;vertical-align:middle">'
                f'<div class="progress-bar" style="width:{pct}%"></div></div>'
                f'<span class="muted" style="font-size:.72rem;margin-left:4px">{pct}%</span>')
        ref_html = f'<br><span class="muted" style="font-size:.72rem">#{_esc(p["reference"])}</span>' if p.get("reference") else ""
        rows += (f'<tr><td><a href="{BP}/projects/{p["id"]}" class="fw7">{_esc(p["name"])}</a>'
            f'{ref_html}<br><span class="muted" style="font-size:.75rem">{_esc(p["client"])}</span></td>'
            f'<td>{_badge(p["status"])}</td><td class="col-m-hide">{_pbadge(p["priority"])}</td>'
            f'<td class="muted col-m-hide">{_esc(p["tech"] or "—")}</td>'
            f'<td class="muted col-m-hide">{_esc((p["due_date"] or "—")[:10])}</td>'
            f'<td class="col-m-hide">{prog}</td>'
            f'<td><button class="btn btn-ghost btn-icon" onclick="editProject({json.dumps(dict(p))})">✏️</button>'
            f'<a href="{BP}/projects/{p["id"]}" class="btn btn-ghost btn-icon">→</a></td></tr>')

    empty = "<p class='muted' style='text-align:center;padding:32px;grid-column:1/-1'>Sin proyectos todavía</p>"
    view_qs = f"{'&status='+filter_status if filter_status else ''}"
    vt_cards = "active" if view == "cards" else ""
    vt_list  = "active" if view == "list"  else ""

    content = f"""
<div class="toolbar">
  <h1>Proyectos</h1>
  <div style="display:flex;gap:10px;align-items:center">
    <div class="view-toggle">
      <button class="{vt_cards}" onclick="window.location='{BP}/projects?view=cards{view_qs}'">⊞ Tarjetas</button>
      <button class="{vt_list}"  onclick="window.location='{BP}/projects?view=list{view_qs}'">☰ Lista</button>
    </div>
    <button class="btn btn-primary" onclick="openNewProject()">+ Nuevo</button>
  </div>
</div>
<div class="toolbar-left" style="margin-bottom:18px">{filters}</div>

<div id="view-cards" style="{"" if view=="cards" else "display:none"}">
  <div class="proj-cards">{cards_html or empty}</div>
</div>
<div id="view-list" style="{"" if view=="list" else "display:none"}">
<div class="card">
  <div class="tbl-wrap"><table><thead><tr>
    <th>Proyecto / Cliente</th><th>Estado</th>
    <th class="col-m-hide">Prioridad</th><th class="col-m-hide">Técnico</th>
    <th class="col-m-hide">Límite</th><th class="col-m-hide">Avance</th><th></th>
  </tr></thead><tbody>{rows or "<tr><td colspan='7' class='muted' style='text-align:center;padding:24px'>Sin proyectos</td></tr>"}</tbody></table></div>
</div>
</div>

<div class="modal-bg" id="proj-modal">
<div class="modal">
  <h2 id="proj-modal-title">Nuevo proyecto</h2>
  <form id="proj-form">
  <input type="hidden" id="proj-id">
  <div class="form-row">
    <div><label>Nombre</label><input id="f-name" required></div>
    <div><label>Referencia / Ticket</label><input id="f-ref" placeholder="OT-2026-001"></div>
  </div>
  <div class="form-row">
    <div><label>Cliente</label><input id="f-client" required></div>
    <div><label>Dirección / Localización</label><input id="f-addr"></div>
  </div>
  <div class="form-row">
    <div><label>Contacto en obra</label><input id="f-cname" placeholder="Nombre"></div>
    <div><label>Teléfono contacto</label><input id="f-cphone" type="tel" placeholder="+34 600 000 000"></div>
  </div>
  <div class="form-row single"><label>Descripción / Alcance</label><textarea id="f-desc"></textarea></div>
  <div class="form-row">
    <div><label>Estado</label><select id="f-status">
      <option value="active">Activo</option><option value="paused">Pausado</option>
      <option value="completed">Completado</option><option value="cancelled">Cancelado</option>
    </select></div>
    <div><label>Prioridad</label><select id="f-priority">
      <option value="low">Baja</option><option value="normal">Normal</option>
      <option value="high">Alta</option><option value="urgent">Urgente</option>
    </select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha inicio</label><input type="date" id="f-start"></div>
    <div><label>Fecha límite</label><input type="date" id="f-due"></div>
  </div>
  <div class="form-row">
    <div><label>Horas estimadas</label><input type="number" id="f-hours" min="0" step="0.5" value="0"></div>
    <div><label>Técnico responsable</label>
      <select id="f-tech"><option value="">Sin asignar</option>{tech_opts}</select></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeProjModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<script>
var bp={json.dumps(BP)};
function openNewProject(){{
  document.getElementById('proj-modal-title').textContent='Nuevo proyecto';
  ['id','name','ref','client','addr','cname','cphone','desc'].forEach(function(f){{
    document.getElementById('f-'+f).value='';
  }});
  document.getElementById('f-status').value='active';
  document.getElementById('f-priority').value='normal';
  document.getElementById('f-start').value='';
  document.getElementById('f-due').value='';
  document.getElementById('f-hours').value=0;
  document.getElementById('f-tech').value='';
  document.getElementById('proj-modal').classList.add('open');
}}
function editProject(p){{
  document.getElementById('proj-modal-title').textContent='Editar proyecto';
  document.getElementById('f-id').value=p.id;
  document.getElementById('f-name').value=p.name||'';
  document.getElementById('f-ref').value=p.reference||'';
  document.getElementById('f-client').value=p.client||'';
  document.getElementById('f-addr').value=p.address||'';
  document.getElementById('f-cname').value=p.contact_name||'';
  document.getElementById('f-cphone').value=p.contact_phone||'';
  document.getElementById('f-desc').value=p.description||'';
  document.getElementById('f-status').value=p.status||'active';
  document.getElementById('f-priority').value=p.priority||'normal';
  document.getElementById('f-start').value=p.start_date||'';
  document.getElementById('f-due').value=p.due_date||'';
  document.getElementById('f-hours').value=p.estimated_hours||0;
  document.getElementById('f-tech').value=p.assigned_to||'';
  document.getElementById('proj-modal').classList.add('open');
}}
function closeProjModal(){{document.getElementById('proj-modal').classList.remove('open');}}
document.getElementById('proj-modal').onclick=function(e){{if(e.target===this)closeProjModal();}};
document.getElementById('proj-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('f-id').value;
  var d={{name:document.getElementById('f-name').value,
    reference:document.getElementById('f-ref').value,
    client:document.getElementById('f-client').value,
    address:document.getElementById('f-addr').value,
    contact_name:document.getElementById('f-cname').value,
    contact_phone:document.getElementById('f-cphone').value,
    description:document.getElementById('f-desc').value,
    status:document.getElementById('f-status').value,
    priority:document.getElementById('f-priority').value,
    start_date:document.getElementById('f-start').value,
    due_date:document.getElementById('f-due').value,
    estimated_hours:parseFloat(document.getElementById('f-hours').value)||0,
    assigned_to:document.getElementById('f-tech').value||null}};
  fetch(id?bp+'/api/projects/'+id:bp+'/api/projects',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
</script>"""
    return _shell("projects", user, content)


# ── kanban builder ────────────────────────────────────────────────────────────
def _build_kanban(tasks, pid):
    cols = [
        ("pending",    "Pendiente",  "🔘", "#64748b"),
        ("in_progress","En curso",   "🔵", "#1558c2"),
        ("blocked",    "Bloqueado",  "🔴", "#dc2626"),
        ("done",       "Hecho",      "🟢", "#15803d"),
    ]
    task_by_status = {s: [] for s, *_ in cols}
    for t in tasks:
        s = t['status'] if t['status'] in task_by_status else 'pending'
        task_by_status[s].append(t)

    html = '<div class="kanban">'
    for status, label, icon, color in cols:
        col_tasks = task_by_status[status]
        cards = ""
        for t in col_tasks:
            pcolor = PRIORITY_COLOR.get(t['priority'], "#64748b")
            plabel = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(t['priority'],'')
            cl_total = t.get('cl_t', 0)
            cl_done  = t.get('cl_d', 0)
            cl_pct   = int(cl_done/cl_total*100) if cl_total else 0
            cl_html  = ""
            if cl_total:
                cl_html = (f'<div style="margin-top:6px">'
                           f'<div style="font-size:.7rem;color:var(--muted);margin-bottom:2px">'
                           f'Checklist {cl_done}/{cl_total}</div>'
                           f'<div class="progress"><div class="progress-bar" style="width:{cl_pct}%"></div></div></div>')
            due_html = f'<span style="font-size:.72rem;color:var(--muted)">🗓 {t["due_date"][:10]}</span>' if t.get('due_date') else ""
            cards += (
                f'<div class="task-card" draggable="true" '
                f'data-task-id="{t["id"]}" data-status="{t["status"]}" '
                f'data-title="{_esc(t["title"])}" data-priority="{t["priority"]}">'
                f'<div class="task-card-strip" style="background:{pcolor}"></div>'
                f'<div class="task-card-inner">'
                f'<div class="task-card-title">{_esc(t["title"])}</div>'
                f'{("<div style=font-size:.75rem;color:var(--muted);margin-bottom:4px>"+_esc(t["description"])+"</div>") if t.get("description") else ""}'
                f'{cl_html}'
                f'<div class="task-card-foot">'
                f'<span style="color:{pcolor};font-size:.72rem;font-weight:700">▲ {plabel}</span>'
                f'{due_html}'
                f'<button class="btn btn-ghost btn-icon" style="margin-left:auto;font-size:.75rem" '
                f'onclick="openChecklist({t["id"]},{json.dumps(t["title"])})">☑</button>'
                f'<button class="btn btn-ghost btn-icon" style="font-size:.75rem" '
                f'onclick="editTask({json.dumps(dict(t))})">✏️</button>'
                f'<button class="btn btn-danger btn-icon" style="font-size:.75rem" '
                f'onclick="delTask({t["id"]})">✕</button>'
                f'</div></div></div>')

        count = len(col_tasks)
        html += (f'<div class="kanban-col" data-status="{status}">'
                 f'<div class="kanban-col-hd">'
                 f'<div class="col-title" style="color:{color}">{icon} {label}</div>'
                 f'<span class="col-count">{count}</span></div>'
                 f'<div class="kanban-cards" data-status="{status}">{cards}</div>'
                 f'<button class="kanban-add" onclick="openNewTaskStatus(\'{status}\')">+ Añadir tarea</button>'
                 f'</div>')
    html += '</div>'
    return html

# ── project detail ────────────────────────────────────────────────────────────
def _project_detail(user, pid):
    p = r2d(q1("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to WHERE p.id=?""", (pid,)))
    if not p: return None

    tasks = rs(q("""SELECT t.*,
        (SELECT COUNT(*) FROM task_checklist c WHERE c.task_id=t.id) cl_t,
        (SELECT COUNT(*) FROM task_checklist c WHERE c.task_id=t.id AND c.done=1) cl_d
        FROM tasks t WHERE t.project_id=?
        ORDER BY CASE t.status WHEN 'blocked' THEN 0 WHEN 'in_progress' THEN 1
          WHEN 'pending' THEN 2 ELSE 3 END, t.priority DESC""", (pid,)))

    assignments = rs(q("""SELECT a.*,m.name mat_name,m.code mat_code,m.unit mat_unit
        FROM assignments a JOIN materials m ON m.id=a.material_id
        WHERE a.project_id=? ORDER BY a.created_at DESC""", (pid,)))

    logs = rs(q("""SELECT l.*,u.display_name uname
        FROM project_logs l JOIN users u ON u.id=l.user_id
        WHERE l.project_id=? ORDER BY l.created_at DESC LIMIT 40""", (pid,)))

    mats = rs(q("SELECT id,code,name,unit,stock_warehouse FROM materials ORDER BY name"))
    mat_opts = "".join(
        f'<option value="{m["id"]}" data-stock="{m["stock_warehouse"]}">'
        f'[{_esc(m["code"])}] {_esc(m["name"])} ({_esc(m["unit"])})</option>'
        for m in mats)

    # ── task rows (no assigned_to shown — tasks are team work) ──
    t_rows = ""
    for t in tasks:
        cl_pct = int(t['cl_d']/t['cl_t']*100) if t['cl_t'] else -1
        cl_html = ""
        if t['cl_t'] > 0:
            cl_html = (f'<div class="progress" style="width:50px;display:inline-block;vertical-align:middle;margin-left:6px">'
                       f'<div class="progress-bar" style="width:{cl_pct}%"></div></div>'
                       f'<span class="muted" style="font-size:.7rem"> {t["cl_d"]}/{t["cl_t"]}</span>')
        done_btn_style = 'background:var(--green);color:#fff' if t['status']=='done' else ''
        t_rows += (f'<tr><td>'
            f'<button class="btn btn-ghost btn-icon" style="{done_btn_style}" '
            f'onclick="toggleTask({t["id"]},{json.dumps(t["status"])})" title="Toggle estado">✓</button></td>'
            f'<td><span class="fw7">{_esc(t["title"])}</span>{cl_html}'
            f'{"<br><span class=muted style=font-size:.75rem>"+_esc(t["description"])+"</span>" if t.get("description") else ""}</td>'
            f'<td>{_badge(t["status"])}</td>'
            f'<td class="col-m-hide">{_pbadge(t["priority"])}</td>'
            f'<td class="muted col-m-hide">{_esc((t["due_date"] or "—")[:10])}</td>'
            f'<td>'
            f'<button class="btn btn-ghost btn-icon" onclick="openChecklist({t["id"]},{json.dumps(t["title"])})">☑</button>'
            f'<button class="btn btn-ghost btn-icon" onclick="editTask({json.dumps(dict(t))})">✏️</button>'
            f'<button class="btn btn-danger btn-icon" onclick="delTask({t["id"]})">✕</button>'
            f'</td></tr>')

    # ── assignment rows ──
    a_rows = ""
    for a in assignments:
        a_rows += (f'<tr><td><span class="chip">{_esc(a["mat_code"])}</span> {_esc(a["mat_name"])}</td>'
            f'<td style="text-align:center">{a["qty_requested"]}</td>'
            f'<td style="text-align:center">{a["qty_assigned"]}</td>'
            f'<td style="text-align:center">{a["qty_consumed"]}</td>'
            f'<td style="text-align:center">{a["qty_returned"]}</td>'
            f'<td>{_badge(a["status"])}</td>'
            f'<td class="muted col-m-hide">{_esc(a["mat_unit"])}</td>'
            f'<td><button class="btn btn-ghost btn-icon" onclick="updateAssign({a["id"]},{json.dumps(dict(a))})">⚙️</button></td></tr>')

    # ── work log ──
    log_items = ""
    for l in logs:
        initials = "".join(w[0].upper() for w in l['uname'].split()[:2])
        h_badge = f'<span class="tl-hours">{l["hours"]}h</span>' if l['hours'] else ""
        log_items += (f'<li><div class="tl-dot">{_esc(initials)}</div><div class="tl-body">'
            f'<div class="tl-meta">{_esc(l["uname"])} &middot; {_esc(l["created_at"][:16])}{h_badge}</div>'
            f'<div class="tl-text">{_esc(l["body"])}</div></div></li>')

    # ── priority/status display ──
    plabel = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(p['priority'],p['priority'])
    pcolor = PRIORITY_COLOR.get(p['priority'],"#64748b")
    desc_html = f'<p style="color:var(--muted);margin-bottom:16px;line-height:1.6">{_esc(p["description"])}</p>' if p.get('description') else ''

    # info tab content
    info_rows = ""
    info_fields = [("Referencia", p.get("reference","")), ("Cliente", p.get("client","")),
                   ("Dirección", p.get("address","")), ("Técnico responsable", p.get("tech","")),
                   ("Contacto en obra", p.get("contact_name","")),
                   ("Teléfono", p.get("contact_phone","")),
                   ("Inicio", (p.get("start_date") or "")[:10]),
                   ("Fecha límite", (p.get("due_date") or "")[:10]),
                   ("Horas estimadas", f'{p.get("estimated_hours",0) or 0}h')]
    for label, val in info_fields:
        if val:
            info_rows += f'<tr><td class="muted" style="width:40%;padding:8px 12px">{_esc(label)}</td><td style="padding:8px 12px">{_esc(str(val))}</td></tr>'

    # hours logged
    hours_total = q1("SELECT COALESCE(SUM(hours),0) FROM project_logs WHERE project_id=?", (pid,))
    h_logged = hours_total[0] if hours_total else 0
    h_est = p.get("estimated_hours") or 0
    h_pct = min(100, int(h_logged/h_est*100)) if h_est else 0
    hours_html = ""
    if h_est:
        hours_html = (f'<div class="kpi" style="margin-bottom:16px">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
            f'<div><div class="val" style="font-size:1.2rem">{h_logged}h <span class="muted" style="font-size:.9rem">/ {h_est}h</span></div>'
            f'<div class="lbl">Horas registradas</div></div></div>'
            f'<div class="progress" style="margin-top:8px"><div class="progress-bar" style="width:{h_pct}%"></div></div></div>')

    content = f"""
<div style="margin-bottom:8px"><a href="{BP}/projects" class="muted" style="font-size:.85rem">← Proyectos</a></div>
<div class="toolbar">
  <div>
    <h1 style="margin-bottom:4px">{_esc(p["name"])}</h1>
    <span class="muted" style="font-size:.88rem">{_esc(p["client"])}</span>
    {('&nbsp;<span class="chip">#'+_esc(p["reference"])+'</span>') if p.get("reference") else ""}
    &nbsp;{_badge(p["status"])}
    &nbsp;<span style="color:{pcolor};font-weight:600;font-size:.8rem">▲ {plabel}</span>
  </div>
  <button class="btn btn-ghost btn-sm" onclick="editProject({json.dumps(p)})">✏️ Editar</button>
</div>
{desc_html}

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('tareas',this)">Tareas ({len(tasks)})</button>
  <button class="tab-btn" onclick="showTab('materiales',this)">Materiales ({len(assignments)})</button>
  <button class="tab-btn" onclick="showTab('diario',this)">Diario ({len(logs)})</button>
  <button class="tab-btn" onclick="showTab('info',this)">Info</button>
</div>

<!-- TAB TAREAS -->
<div id="tab-tareas" class="tab-pane active">
<div class="toolbar">
  <div style="display:flex;align-items:center;gap:10px">
    <h2 style="margin:0">Tareas</h2>
    <div class="view-toggle" id="task-view-toggle">
      <button class="active" id="vbtn-kanban" onclick="setTaskView('kanban')">⊞ Kanban</button>
      <button id="vbtn-list" onclick="setTaskView('list')">☰ Lista</button>
    </div>
  </div>
  <button class="btn btn-primary btn-sm" onclick="openNewTask()">+ Tarea</button>
</div>

<!-- kanban view (default) -->
<div id="tasks-kanban">
{_build_kanban(tasks, pid)}
</div>

<!-- list view (hidden by default) -->
<div id="tasks-list" style="display:none">
<div class="card">
  <div class="tbl-wrap"><table><thead><tr>
    <th style="width:40px"></th><th>Tarea</th><th>Estado</th>
    <th class="col-m-hide">Prioridad</th><th class="col-m-hide">Vencimiento</th><th></th>
  </tr></thead><tbody>{t_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:20px'>Sin tareas</td></tr>"}</tbody></table></div>
</div>
</div>
</div>

<!-- TAB MATERIALES -->
<div id="tab-materiales" class="tab-pane">
<div class="toolbar">
  <h2>Materiales asignados</h2>
  <button class="btn btn-primary btn-sm" onclick="openNewAssign()">+ Material</button>
</div>
<div class="card">
  <div class="tbl-wrap"><table><thead><tr>
    <th>Material</th><th style="text-align:center">Solicitado</th>
    <th style="text-align:center">Asignado</th><th style="text-align:center">Consumido</th>
    <th style="text-align:center">Devuelto</th><th>Estado</th>
    <th class="col-m-hide">Ud</th><th></th>
  </tr></thead><tbody>{a_rows or "<tr><td colspan='8' class='muted' style='text-align:center;padding:20px'>Sin materiales asignados</td></tr>"}</tbody></table></div>
</div>
</div>

<!-- TAB DIARIO -->
<div id="tab-diario" class="tab-pane">
<div class="toolbar"><h2>Diario de obra</h2></div>
{hours_html}
<div class="card">
  <div class="field"><label>Nueva entrada</label><textarea id="log-body" rows="3" placeholder="¿Qué se hizo hoy? Instalación, incidencias, pendientes..."></textarea></div>
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:0">
    <div style="flex:0 0 120px"><label>Horas trabajadas</label><input type="number" id="log-hours" min="0" max="24" step="0.5" value="0" placeholder="h"></div>
    <button class="btn btn-primary" onclick="addLog()" style="margin-top:18px">Añadir entrada</button>
  </div>
</div>
{"<ul class='timeline'>" + log_items + "</ul>" if log_items else "<p class='muted' style='text-align:center;padding:20px'>Sin entradas en el diario todavía</p>"}
</div>

<!-- TAB INFO -->
<div id="tab-info" class="tab-pane">
<div class="card">
  <table><tbody>{info_rows or "<tr><td class='muted'>Sin datos adicionales</td></tr>"}</tbody></table>
</div>
</div>

<!-- MODAL editar proyecto -->
<div class="modal-bg" id="proj-modal">
<div class="modal">
  <h2>Editar proyecto</h2>
  <form id="proj-form">
  <div class="form-row">
    <div><label>Nombre</label><input id="f-name"></div>
    <div><label>Referencia</label><input id="f-ref"></div>
  </div>
  <div class="form-row">
    <div><label>Cliente</label><input id="f-client"></div>
    <div><label>Dirección</label><input id="f-addr"></div>
  </div>
  <div class="form-row">
    <div><label>Contacto obra</label><input id="f-cname"></div>
    <div><label>Teléfono</label><input id="f-cphone"></div>
  </div>
  <div class="form-row single"><label>Descripción</label><textarea id="f-desc"></textarea></div>
  <div class="form-row">
    <div><label>Estado</label><select id="f-status">
      <option value="active">Activo</option><option value="paused">Pausado</option>
      <option value="completed">Completado</option><option value="cancelled">Cancelado</option>
    </select></div>
    <div><label>Prioridad</label><select id="f-priority">
      <option value="low">Baja</option><option value="normal">Normal</option>
      <option value="high">Alta</option><option value="urgent">Urgente</option>
    </select></div>
  </div>
  <div class="form-row">
    <div><label>Inicio</label><input type="date" id="f-start"></div>
    <div><label>Límite</label><input type="date" id="f-due"></div>
  </div>
  <div class="form-row">
    <div><label>Horas estimadas</label><input type="number" id="f-hours" min="0" step="0.5"></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeProjModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<!-- MODAL tarea -->
<div class="modal-bg" id="task-modal">
<div class="modal">
  <h2 id="task-modal-title">Nueva tarea</h2>
  <form id="task-form">
  <input type="hidden" id="task-id">
  <div class="form-row single"><label>Título</label><input id="t-title" required placeholder="Ej: Montar rack, Grimpar cables, Configurar switches..."></div>
  <div class="form-row single"><label>Descripción (opcional)</label><textarea id="t-desc"></textarea></div>
  <div class="form-row">
    <div><label>Estado</label><select id="t-status">
      <option value="pending">Pendiente</option><option value="in_progress">En curso</option>
      <option value="done">Hecho</option><option value="blocked">Bloqueado</option>
    </select></div>
    <div><label>Prioridad</label><select id="t-priority">
      <option value="low">Baja</option><option value="normal" selected>Normal</option>
      <option value="high">Alta</option><option value="urgent">Urgente</option>
    </select></div>
  </div>
  <div class="form-row"><div><label>Fecha límite</label><input type="date" id="t-due"></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeTaskModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<!-- MODAL checklist -->
<div class="modal-bg" id="cl-modal">
<div class="modal">
  <h2 id="cl-modal-title">Checklist</h2>
  <ul class="checklist" id="cl-list"></ul>
  <div class="add-row-form" style="margin-top:12px">
    <input id="cl-new" placeholder="Nuevo paso...">
    <button class="btn btn-primary btn-sm" onclick="addChecklistItem()">+</button>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeClModal()">Cerrar</button>
  </div>
</div></div>

<!-- MODAL material asignado -->
<div class="modal-bg" id="assign-modal">
<div class="modal">
  <h2 id="assign-modal-title">Asignar material</h2>
  <form id="assign-form">
  <input type="hidden" id="assign-id">
  <div class="form-row single">
    <div><label>Material</label><select id="a-mat">{mat_opts}</select>
    <span id="a-stock-info" style="font-size:.75rem;color:var(--muted);margin-top:4px;display:block"></span>
    </div>
  </div>
  <div class="form-row">
    <div><label>Solicitado</label><input type="number" id="a-req" min="0" value="1"></div>
    <div><label>Asignado</label><input type="number" id="a-asgn" min="0" value="0"></div>
  </div>
  <div class="form-row">
    <div><label>Consumido</label><input type="number" id="a-cons" min="0" value="0"></div>
    <div><label>Devuelto</label><input type="number" id="a-ret" min="0" value="0"></div>
  </div>
  <div class="form-row single"><div><label>Estado</label><select id="a-status">
    <option value="requested">Solicitado</option><option value="assigned">Asignado</option>
    <option value="consumed">Consumido</option><option value="returned">Devuelto</option>
    <option value="partial">Parcial</option>
  </select></div></div>
  <div class="form-row single"><label>Notas</label><textarea id="a-notes"></textarea></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeAssignModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<script>
var bp={json.dumps(BP)}, pid={pid};
var _clTaskId=null;

// ── tabs ──
function showTab(name,btn){{
  document.querySelectorAll('.tab-pane').forEach(function(p){{p.classList.remove('active');}});
  document.querySelectorAll('.tab-btn').forEach(function(b){{b.classList.remove('active');}});
  document.getElementById('tab-'+name).classList.add('active');
  if(btn) btn.classList.add('active');
}}

// ── project ──
function editProject(p){{
  document.getElementById('f-name').value=p.name||'';
  document.getElementById('f-ref').value=p.reference||'';
  document.getElementById('f-client').value=p.client||'';
  document.getElementById('f-addr').value=p.address||'';
  document.getElementById('f-cname').value=p.contact_name||'';
  document.getElementById('f-cphone').value=p.contact_phone||'';
  document.getElementById('f-desc').value=p.description||'';
  document.getElementById('f-status').value=p.status||'active';
  document.getElementById('f-priority').value=p.priority||'normal';
  document.getElementById('f-start').value=p.start_date||'';
  document.getElementById('f-due').value=p.due_date||'';
  document.getElementById('f-hours').value=p.estimated_hours||0;
  document.getElementById('proj-modal').classList.add('open');
}}
function closeProjModal(){{document.getElementById('proj-modal').classList.remove('open');}}
document.getElementById('proj-modal').onclick=function(e){{if(e.target===this)closeProjModal();}};
document.getElementById('proj-form').onsubmit=function(e){{
  e.preventDefault();
  fetch(bp+'/api/projects/'+pid,{{method:'PUT',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:document.getElementById('f-name').value,
      reference:document.getElementById('f-ref').value,
      client:document.getElementById('f-client').value,address:document.getElementById('f-addr').value,
      contact_name:document.getElementById('f-cname').value,contact_phone:document.getElementById('f-cphone').value,
      description:document.getElementById('f-desc').value,status:document.getElementById('f-status').value,
      priority:document.getElementById('f-priority').value,start_date:document.getElementById('f-start').value,
      due_date:document.getElementById('f-due').value,estimated_hours:parseFloat(document.getElementById('f-hours').value)||0}})
  }}).then(function(r){{if(r.ok)location.reload();}});
}};

// ── task view toggle ──
function setTaskView(v){{
  document.getElementById('tasks-kanban').style.display=v==='kanban'?'':'none';
  document.getElementById('tasks-list').style.display=v==='list'?'':'none';
  document.getElementById('vbtn-kanban').className=v==='kanban'?'active':'';
  document.getElementById('vbtn-list').className=v==='list'?'active':'';
  localStorage.setItem('nd_task_view_'+pid,v);
}}
(function(){{
  var saved=localStorage.getItem('nd_task_view_'+pid);
  if(saved&&saved==='list') setTaskView('list');
}})();

// ── kanban drag & drop ──
var _dragging=null;
document.querySelectorAll('.task-card').forEach(function(card){{
  card.addEventListener('dragstart',function(e){{
    _dragging=this;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed='move';
    e.dataTransfer.setData('text/plain',this.dataset.taskId);
  }});
  card.addEventListener('dragend',function(){{
    this.classList.remove('dragging');
    _dragging=null;
    document.querySelectorAll('.kanban-col').forEach(function(c){{c.classList.remove('drag-over');}});
  }});
}});
document.querySelectorAll('.kanban-col').forEach(function(col){{
  col.addEventListener('dragover',function(e){{
    e.preventDefault();e.dataTransfer.dropEffect='move';
    this.classList.add('drag-over');
  }});
  col.addEventListener('dragleave',function(e){{
    if(!col.contains(e.relatedTarget)) this.classList.remove('drag-over');
  }});
  col.addEventListener('drop',function(e){{
    e.preventDefault();
    this.classList.remove('drag-over');
    if(!_dragging) return;
    var newStatus=this.dataset.status;
    var oldStatus=_dragging.dataset.status;
    if(newStatus===oldStatus) return;
    var cardsEl=this.querySelector('.kanban-cards');
    cardsEl.appendChild(_dragging);
    _dragging.dataset.status=newStatus;
    // update count badges
    document.querySelectorAll('.kanban-col').forEach(function(c){{
      var cnt=c.querySelectorAll('.task-card').length;
      c.querySelector('.col-count').textContent=cnt;
    }});
    // persist
    fetch(bp+'/api/tasks/'+_dragging.dataset.taskId,{{method:'PUT',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{status:newStatus,title:_dragging.dataset.title,
        priority:_dragging.dataset.priority}})}});
  }});
}});

// ── tasks ──
var _newTaskStatus='pending';
function openNewTaskStatus(status){{
  _newTaskStatus=status||'pending';
  openNewTask();
}}
function openNewTask(){{
  document.getElementById('task-modal-title').textContent='Nueva tarea';
  document.getElementById('task-id').value='';
  document.getElementById('t-title').value='';
  document.getElementById('t-desc').value='';
  document.getElementById('t-status').value=_newTaskStatus||'pending';
  document.getElementById('t-priority').value='normal';
  document.getElementById('t-due').value='';
  _newTaskStatus='pending';
  document.getElementById('task-modal').classList.add('open');
}}
function editTask(t){{
  document.getElementById('task-modal-title').textContent='Editar tarea';
  document.getElementById('task-id').value=t.id;
  document.getElementById('t-title').value=t.title||'';
  document.getElementById('t-desc').value=t.description||'';
  document.getElementById('t-status').value=t.status||'pending';
  document.getElementById('t-priority').value=t.priority||'normal';
  document.getElementById('t-due').value=t.due_date||'';
  document.getElementById('task-modal').classList.add('open');
}}
function closeTaskModal(){{document.getElementById('task-modal').classList.remove('open');}}
document.getElementById('task-modal').onclick=function(e){{if(e.target===this)closeTaskModal();}};
document.getElementById('task-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('task-id').value;
  var d={{title:document.getElementById('t-title').value,description:document.getElementById('t-desc').value,
    status:document.getElementById('t-status').value,priority:document.getElementById('t-priority').value,
    due_date:document.getElementById('t-due').value}};
  var url=id?bp+'/api/tasks/'+id:bp+'/api/projects/'+pid+'/tasks';
  fetch(url,{{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();}});
}};
function toggleTask(id,status){{
  var next=status==='done'?'pending':'done';
  fetch(bp+'/api/tasks/'+id+'/toggle',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{status:next}})}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
function delTask(id){{
  if(!confirm('¿Eliminar tarea?')) return;
  fetch(bp+'/api/tasks/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
}}

// ── checklist ──
function openChecklist(taskId,title){{
  _clTaskId=taskId;
  document.getElementById('cl-modal-title').textContent='Checklist: '+title;
  document.getElementById('cl-list').innerHTML='<li class=muted>Cargando...</li>';
  document.getElementById('cl-modal').classList.add('open');
  fetch(bp+'/api/tasks/'+taskId+'/checklist')
    .then(function(r){{return r.json();}}).then(renderChecklist);
}}
function renderChecklist(items){{
  var ul=document.getElementById('cl-list');
  if(!items.length){{ul.innerHTML='<li class=muted style="padding:8px 0">Sin pasos — añade el primero</li>';return;}}
  ul.innerHTML=items.map(function(c){{
    var cls=c.done?'done':'';
    return '<li class="'+cls+'" id="cl-'+c.id+'">'
      +'<input type="checkbox"'+(c.done?' checked':'')
      +' onchange="toggleCl('+c.id+',this.checked)">'
      +'<span class=cl-label>'+c.label.replace(/</g,'&lt;')+'</span>'
      +'<button class=cl-del onclick="delCl('+c.id+')">✕</button></li>';
  }}).join('');
}}
function addChecklistItem(){{
  var inp=document.getElementById('cl-new');
  var label=inp.value.trim();
  if(!label) return;
  fetch(bp+'/api/tasks/'+_clTaskId+'/checklist',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{label:label}})}})
    .then(function(r){{return r.json();}}).then(function(){{
      inp.value='';
      fetch(bp+'/api/tasks/'+_clTaskId+'/checklist').then(function(r){{return r.json();}}).then(renderChecklist);
    }});
}}
document.getElementById('cl-new').addEventListener('keydown',function(e){{
  if(e.key==='Enter'){{e.preventDefault();addChecklistItem();}}
}});
function toggleCl(id,done){{
  fetch(bp+'/api/checklist/'+id,{{method:'PUT',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{done:done?1:0}})}})
    .then(function(){{
      var li=document.getElementById('cl-'+id);
      if(li) li.className=done?'done':'';
    }});
}}
function delCl(id){{
  fetch(bp+'/api/checklist/'+id,{{method:'DELETE'}})
    .then(function(){{
      var li=document.getElementById('cl-'+id);
      if(li) li.remove();
    }});
}}
function closeClModal(){{document.getElementById('cl-modal').classList.remove('open');}}
document.getElementById('cl-modal').onclick=function(e){{if(e.target===this)closeClModal();}};

// ── log ──
function addLog(){{
  var body=document.getElementById('log-body').value.trim();
  if(!body) return;
  var hours=parseFloat(document.getElementById('log-hours').value)||0;
  fetch(bp+'/api/projects/'+pid+'/log',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{body:body,hours:hours}})}})
    .then(function(r){{if(r.ok)location.reload();}});
}}

// ── assignments ──
function openNewAssign(){{
  document.getElementById('assign-modal-title').textContent='Asignar material';
  document.getElementById('assign-id').value='';
  document.getElementById('a-mat').disabled=false;
  document.getElementById('a-req').value=1;
  document.getElementById('a-asgn').value=0;
  document.getElementById('a-cons').value=0;
  document.getElementById('a-ret').value=0;
  document.getElementById('a-status').value='requested';
  document.getElementById('a-notes').value='';
  updateStockInfo();
  document.getElementById('assign-modal').classList.add('open');
}}
function updateAssign(id,a){{
  document.getElementById('assign-modal-title').textContent='Actualizar material';
  document.getElementById('assign-id').value=id;
  document.getElementById('a-mat').value=a.material_id;
  document.getElementById('a-mat').disabled=true;
  document.getElementById('a-req').value=a.qty_requested;
  document.getElementById('a-asgn').value=a.qty_assigned;
  document.getElementById('a-cons').value=a.qty_consumed;
  document.getElementById('a-ret').value=a.qty_returned;
  document.getElementById('a-status').value=a.status;
  document.getElementById('a-notes').value=a.notes||'';
  updateStockInfo();
  document.getElementById('assign-modal').classList.add('open');
}}
function closeAssignModal(){{document.getElementById('assign-modal').classList.remove('open');}}
document.getElementById('assign-modal').onclick=function(e){{if(e.target===this)closeAssignModal();}};
function updateStockInfo(){{
  var sel=document.getElementById('a-mat');
  var opt=sel.options[sel.selectedIndex];
  var s=opt?opt.getAttribute('data-stock'):'?';
  document.getElementById('a-stock-info').textContent='Stock en almacén: '+s+' ud';
}}
document.getElementById('a-mat').onchange=updateStockInfo;
document.getElementById('assign-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('assign-id').value;
  var d={{material_id:document.getElementById('a-mat').value,
    qty_requested:parseInt(document.getElementById('a-req').value)||0,
    qty_assigned:parseInt(document.getElementById('a-asgn').value)||0,
    qty_consumed:parseInt(document.getElementById('a-cons').value)||0,
    qty_returned:parseInt(document.getElementById('a-ret').value)||0,
    status:document.getElementById('a-status').value,notes:document.getElementById('a-notes').value}};
  var url=id?bp+'/api/assignments/'+id:bp+'/api/projects/'+pid+'/assignments';
  fetch(url,{{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
updateStockInfo();
</script>"""
    return _shell("projects", user, content)


# ── inventory ─────────────────────────────────────────────────────────────────
def _inventory_page(user):
    mats = rs(q("SELECT * FROM materials ORDER BY category, name"))
    cats = sorted({m['category'] for m in mats if m.get('category')})
    moves = rs(q("""SELECT mv.*,m.name mat_name,m.code mat_code,u.display_name uname
        FROM stock_movements mv JOIN materials m ON m.id=mv.material_id
        LEFT JOIN users u ON u.id=mv.user_id
        ORDER BY mv.created_at DESC LIMIT 30"""))

    cat_opts = "".join(f'<option value="{_esc(c)}">{_esc(c)}</option>' for c in cats)

    rows = ""
    for m in mats:
        critical = m['stock_warehouse'] <= m['stock_min'] and m['stock_min'] > 0
        low_style = 'color:var(--red);font-weight:700' if critical else ''
        critical_icon = ' ⚠️' if critical else ''
        rows += (f'<tr><td><span class="chip">{_esc(m["code"])}</span></td>'
            f'<td><span class="fw7">{_esc(m["name"])}</span>{critical_icon}'
            f'{"<br><span class=muted style=font-size:.72rem>"+_esc(m["description"])+"</span>" if m.get("description") else ""}</td>'
            f'<td class="muted col-m-hide">{_esc(m["category"] or "—")}</td>'
            f'<td style="text-align:center;{low_style}">{m["stock_warehouse"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_field"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_warehouse"]+m["stock_field"]}</td>'
            f'<td style="text-align:center" class="col-m-hide">{m["stock_min"]}</td>'
            f'<td class="muted col-m-hide">{_esc(m["unit"])}</td>'
            f'<td>'
            f'<button class="btn btn-ghost btn-icon" title="Ajustar stock" onclick="openAdjust({m["id"]},{json.dumps(m["name"])},{m["stock_warehouse"]})">±</button>'
            f'<button class="btn btn-ghost btn-icon" onclick="editMat({json.dumps(dict(m))})">✏️</button>'
            f'<button class="btn btn-danger btn-icon" onclick="delMat({m["id"]})">✕</button>'
            f'</td></tr>')

    mv_rows = ""
    for mv in moves:
        icon = '<span class="mv-in">+</span>' if mv['direction']=='in' else '<span class="mv-out">−</span>'
        mv_rows += (f'<tr><td class="muted" style="font-size:.75rem;white-space:nowrap">{mv["created_at"][:16]}</td>'
            f'<td><span class="chip">{_esc(mv["mat_code"])}</span> {_esc(mv["mat_name"])}</td>'
            f'<td style="text-align:center">{icon} {mv["qty"]}</td>'
            f'<td class="muted col-m-hide">{_esc(mv["source"] or "—")}</td>'
            f'<td class="muted col-m-hide">{_esc(mv["uname"] or "—")}</td>'
            f'<td class="muted col-m-hide" style="font-size:.78rem">{_esc(mv["notes"] or "")}</td></tr>')

    content = f"""
<div class="toolbar"><h1>Inventario</h1>
  <button class="btn btn-primary" onclick="openNewMat()">+ Material</button>
</div>
<div class="card">
<div class="tbl-wrap"><table><thead><tr>
  <th>Código</th><th>Nombre</th><th class="col-m-hide">Categoría</th>
  <th style="text-align:center">Almacén</th><th style="text-align:center" class="col-m-hide">Campo</th>
  <th style="text-align:center" class="col-m-hide">Total</th>
  <th style="text-align:center" class="col-m-hide">Mínimo</th>
  <th class="col-m-hide">Ud</th><th></th>
</tr></thead><tbody>{rows or "<tr><td colspan='9' class='muted' style='text-align:center;padding:24px'>Sin materiales</td></tr>"}</tbody></table></div>
</div>

<div class="card">
  <h2>Últimos movimientos de stock</h2>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Fecha</th><th>Material</th><th style="text-align:center">Cant.</th>
    <th class="col-m-hide">Origen</th><th class="col-m-hide">Usuario</th><th class="col-m-hide">Notas</th>
  </tr></thead><tbody>{mv_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:16px'>Sin movimientos</td></tr>"}</tbody></table></div>
</div>

<!-- modal material -->
<div class="modal-bg" id="mat-modal">
<div class="modal">
  <h2 id="mat-modal-title">Nuevo material</h2>
  <form id="mat-form">
  <input type="hidden" id="mat-id">
  <div class="form-row">
    <div><label>Código</label><input id="m-code" required placeholder="SFP-SM-1G"></div>
    <div><label>Nombre</label><input id="m-name" required placeholder="Transceptor SFP SM 1G"></div>
  </div>
  <div class="form-row">
    <div><label>Categoría</label><input id="m-cat" list="cat-dl" placeholder="Transceivers">
      <datalist id="cat-dl">{cat_opts}</datalist></div>
    <div><label>Unidad</label><select id="m-unit">
      <option value="ud">ud</option><option value="m">m</option>
      <option value="m2">m²</option><option value="kg">kg</option>
      <option value="l">l</option><option value="bobina">bobina</option>
      <option value="caja">caja</option><option value="rollo">rollo</option>
      <option value="par">par</option>
    </select></div>
  </div>
  <div class="form-row single"><label>Descripción</label><textarea id="m-desc" rows="2"></textarea></div>
  <div class="form-row">
    <div><label>Stock almacén</label><input type="number" id="m-wh" min="0" value="0"></div>
    <div><label>Stock campo</label><input type="number" id="m-fi" min="0" value="0"></div>
  </div>
  <div class="form-row"><div><label>Stock mínimo</label><input type="number" id="m-min" min="0" value="0"></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeMatModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<!-- modal ajuste rápido -->
<div class="modal-bg" id="adj-modal">
<div class="modal" style="max-width:360px">
  <h2 id="adj-title">Ajuste de stock</h2>
  <input type="hidden" id="adj-mid">
  <div class="field"><label>Variación (+entrada / -salida)</label>
    <input type="number" id="adj-qty" placeholder="Ej: +10 o -5"></div>
  <div class="field"><label>Notas</label>
    <input id="adj-notes" placeholder="Motivo del ajuste"></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeAdjModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="doAdjust()">Aplicar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
function openNewMat(){{
  document.getElementById('mat-modal-title').textContent='Nuevo material';
  document.getElementById('mat-id').value='';
  ['code','name','cat','desc'].forEach(function(f){{document.getElementById('m-'+f).value='';}});
  document.getElementById('m-unit').value='ud';
  ['wh','fi','min'].forEach(function(f){{document.getElementById('m-'+f).value=0;}});
  document.getElementById('mat-modal').classList.add('open');
}}
function editMat(m){{
  document.getElementById('mat-modal-title').textContent='Editar material';
  document.getElementById('mat-id').value=m.id;
  document.getElementById('m-code').value=m.code||'';
  document.getElementById('m-name').value=m.name||'';
  document.getElementById('m-cat').value=m.category||'';
  document.getElementById('m-desc').value=m.description||'';
  document.getElementById('m-unit').value=m.unit||'ud';
  document.getElementById('m-wh').value=m.stock_warehouse||0;
  document.getElementById('m-fi').value=m.stock_field||0;
  document.getElementById('m-min').value=m.stock_min||0;
  document.getElementById('mat-modal').classList.add('open');
}}
function closeMatModal(){{document.getElementById('mat-modal').classList.remove('open');}}
document.getElementById('mat-modal').onclick=function(e){{if(e.target===this)closeMatModal();}};
document.getElementById('mat-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('mat-id').value;
  var d={{code:document.getElementById('m-code').value,name:document.getElementById('m-name').value,
    category:document.getElementById('m-cat').value,description:document.getElementById('m-desc').value,
    unit:document.getElementById('m-unit').value,
    stock_warehouse:parseInt(document.getElementById('m-wh').value)||0,
    stock_field:parseInt(document.getElementById('m-fi').value)||0,
    stock_min:parseInt(document.getElementById('m-min').value)||0}};
  fetch(id?bp+'/api/materials/'+id:bp+'/api/materials',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
function delMat(id){{
  if(!confirm('¿Eliminar material?')) return;
  fetch(bp+'/api/materials/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function openAdjust(id,name,cur){{
  document.getElementById('adj-title').textContent='Ajuste: '+name+' (actual: '+cur+')';
  document.getElementById('adj-mid').value=id;
  document.getElementById('adj-qty').value='';
  document.getElementById('adj-notes').value='';
  document.getElementById('adj-modal').classList.add('open');
}}
function closeAdjModal(){{document.getElementById('adj-modal').classList.remove('open');}}
document.getElementById('adj-modal').onclick=function(e){{if(e.target===this)closeAdjModal();}};
function doAdjust(){{
  var mid=document.getElementById('adj-mid').value;
  var qty=parseInt(document.getElementById('adj-qty').value);
  var notes=document.getElementById('adj-notes').value;
  if(isNaN(qty)||qty===0){{alert('Introduce una cantidad distinta de 0');return;}}
  fetch(bp+'/api/materials/'+mid+'/adjust',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{qty:qty,notes:notes}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
</script>"""
    return _shell("inventory", user, content)

# ── kit de técnico ────────────────────────────────────────────────────────────
def _kit_page(user):
    techs = rs(q("""SELECT u.id,u.display_name,u.role,
        COUNT(k.id) items, COALESCE(SUM(k.qty),0) total_qty
        FROM users u LEFT JOIN tech_kit k ON k.user_id=u.id AND k.qty>0
        WHERE u.active=1
        GROUP BY u.id ORDER BY u.display_name"""))
    mats = rs(q("SELECT id,code,name,unit,stock_warehouse FROM materials ORDER BY category,name"))
    mat_opts = "".join(
        f'<option value="{m["id"]}" data-stock="{m["stock_warehouse"]}" data-unit="{_esc(m["unit"])}">'
        f'[{_esc(m["code"])}] {_esc(m["name"])}</option>' for m in mats)
    user_opts = "".join(
        f'<option value="{t["id"]}">{_esc(t["display_name"])}</option>' for t in techs)

    cards = ""
    for t in techs:
        kit_items = rs(q("""SELECT k.*,m.name mat_name,m.code mat_code,m.unit mat_unit
            FROM tech_kit k JOIN materials m ON m.id=k.material_id
            WHERE k.user_id=? AND k.qty>0 ORDER BY m.category,m.name""", (t['id'],)))
        role_lbl = {"admin":"Admin","technician":"Técnico","backoffice":"Backoffice"}.get(t['role'],t['role'])

        item_rows = ""
        for ki in kit_items:
            item_rows += (f'<tr><td><span class="chip">{_esc(ki["mat_code"])}</span></td>'
                f'<td>{_esc(ki["mat_name"])}</td>'
                f'<td style="text-align:center;font-weight:700">{ki["qty"]}</td>'
                f'<td class="muted">{_esc(ki["mat_unit"])}</td>'
                f'<td class="muted" style="font-size:.75rem">{_esc(ki["notes"] or "")}</td>'
                f'<td><button class="btn btn-danger btn-icon" '
                f'onclick="returnFromKit({ki["id"]},{ki["qty"]},{json.dumps(ki["mat_name"])},{t["id"]})">↩</button></td></tr>')

        empty_msg = '<p class="muted" style="padding:12px 0;font-size:.85rem">Kit vacío</p>'
        kit_table = (f'<div class="tbl-wrap"><table><thead><tr><th>Cód</th><th>Material</th>'
            f'<th style="text-align:center">Qty</th><th>Ud</th><th>Notas</th><th></th></tr></thead>'
            f'<tbody>{item_rows}</tbody></table></div>') if kit_items else empty_msg

        tid = t['id']
        cards += f"""<div class="kit-card">
  <h3>👤 {_esc(t['display_name'])} <span class="role-badge">{_esc(role_lbl)}</span>
    <span class="muted" style="font-size:.75rem;font-weight:400;margin-left:auto">{t['items']} items · {t['total_qty']} uds</span>
  </h3>
  {kit_table}
  <div style="margin-top:10px">
    <button class="btn btn-primary btn-sm" onclick="openAddKit({tid},{json.dumps(t['display_name'])})">+ Añadir al kit</button>
  </div>
</div>"""

    content = f"""
<div class="toolbar">
  <h1>🎒 Kit de campo por técnico</h1>
</div>
<div class="alert alert-amber" style="font-size:.85rem">
  El kit de campo son los materiales que cada técnico lleva habitualmente:
  SFP/GLC, latiguillos, inyectores POE, herramientas, conectores, etc.
  Al añadir al kit se descuenta del stock de almacén.
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px">
{cards}
</div>

<!-- modal añadir al kit -->
<div class="modal-bg" id="kit-modal">
<div class="modal" style="max-width:420px">
  <h2 id="kit-modal-title">Añadir al kit</h2>
  <input type="hidden" id="kit-uid">
  <div class="field"><label>Material</label>
    <select id="kit-mat">{mat_opts}</select>
    <span id="kit-stock-info" style="font-size:.75rem;color:var(--muted);margin-top:4px;display:block"></span>
  </div>
  <div class="form-row">
    <div><label>Cantidad</label><input type="number" id="kit-qty" min="1" value="1"></div>
    <div><label>Notas</label><input id="kit-notes" placeholder="Opcional"></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeKitModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="doAddKit()">Añadir al kit</button>
  </div>
</div></div>

<!-- modal devolver al almacén -->
<div class="modal-bg" id="ret-modal">
<div class="modal" style="max-width:380px">
  <h2 id="ret-title">Devolver al almacén</h2>
  <input type="hidden" id="ret-kid">
  <input type="hidden" id="ret-uid">
  <div class="field"><label>Cantidad a devolver</label>
    <input type="number" id="ret-qty" min="1" value="1"></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeRetModal()">Cancelar</button>
    <button class="btn btn-amber" onclick="doReturn()">Devolver</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
function openAddKit(uid,name){{
  document.getElementById('kit-modal-title').textContent='Añadir kit: '+name;
  document.getElementById('kit-uid').value=uid;
  document.getElementById('kit-qty').value=1;
  document.getElementById('kit-notes').value='';
  updateKitStock();
  document.getElementById('kit-modal').classList.add('open');
}}
function closeKitModal(){{document.getElementById('kit-modal').classList.remove('open');}}
document.getElementById('kit-modal').onclick=function(e){{if(e.target===this)closeKitModal();}};
function updateKitStock(){{
  var sel=document.getElementById('kit-mat');
  var opt=sel.options[sel.selectedIndex];
  var s=opt?opt.getAttribute('data-stock'):'?';
  var u=opt?opt.getAttribute('data-unit'):'';
  document.getElementById('kit-stock-info').textContent='Stock almacén disponible: '+s+' '+u;
}}
document.getElementById('kit-mat').onchange=updateKitStock;
function doAddKit(){{
  var uid=document.getElementById('kit-uid').value;
  var mid=document.getElementById('kit-mat').value;
  var qty=parseInt(document.getElementById('kit-qty').value)||0;
  var notes=document.getElementById('kit-notes').value;
  if(qty<1){{alert('Cantidad mínima: 1');return;}}
  fetch(bp+'/api/kit',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{user_id:uid,material_id:mid,qty:qty,notes:notes}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function returnFromKit(kid,maxQty,name,uid){{
  document.getElementById('ret-title').textContent='Devolver: '+name;
  document.getElementById('ret-kid').value=kid;
  document.getElementById('ret-uid').value=uid;
  document.getElementById('ret-qty').max=maxQty;
  document.getElementById('ret-qty').value=maxQty;
  document.getElementById('ret-modal').classList.add('open');
}}
function closeRetModal(){{document.getElementById('ret-modal').classList.remove('open');}}
document.getElementById('ret-modal').onclick=function(e){{if(e.target===this)closeRetModal();}};
function doReturn(){{
  var kid=document.getElementById('ret-kid').value;
  var qty=parseInt(document.getElementById('ret-qty').value)||0;
  if(qty<1){{alert('Cantidad mínima: 1');return;}}
  fetch(bp+'/api/kit/'+kid+'/return',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{qty:qty}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
</script>"""
    return _shell("kit", user, content)

# ── users ─────────────────────────────────────────────────────────────────────
def _users_page(user):
    users = rs(q("""SELECT u.*,COUNT(k.id) kit_items
        FROM users u LEFT JOIN tech_kit k ON k.user_id=u.id AND k.qty>0
        GROUP BY u.id ORDER BY u.display_name"""))
    rows = ""
    for u in users:
        role_lbl = {"admin":"Admin","technician":"Técnico","backoffice":"Backoffice"}.get(u['role'],u['role'])
        active_dot = '🟢' if u['active'] else '⚫'
        uid_val = u['id']
        del_btn = ("" if uid_val == user['id'] else
                   f'<button class="btn btn-danger btn-icon" onclick="delUser({uid_val})">✕</button>')
        rows += (f'<tr><td class="fw7">{_esc(u["display_name"])}</td>'
            f'<td class="muted">{_esc(u["username"])}</td>'
            f'<td>{_esc(role_lbl)}</td>'
            f'<td>{active_dot}</td>'
            f'<td class="muted col-m-hide">{u["kit_items"]} items</td>'
            f'<td class="muted col-m-hide">{_esc((u["created_at"] or "")[:10])}</td>'
            f'<td><button class="btn btn-ghost btn-icon" onclick="editUser({json.dumps(dict(u))})">✏️</button>'
            f'{del_btn}</td></tr>')

    content = f"""
<div class="toolbar"><h1>Usuarios</h1>
  <button class="btn btn-primary" onclick="openNewUser()">+ Usuario</button>
</div>
<div class="card">
<div class="tbl-wrap"><table><thead><tr>
  <th>Nombre</th><th>Usuario</th><th>Rol</th><th></th>
  <th class="col-m-hide">Kit</th><th class="col-m-hide">Creado</th><th></th>
</tr></thead><tbody>{rows}</tbody></table></div>
</div>

<div class="modal-bg" id="user-modal">
<div class="modal">
  <h2 id="user-modal-title">Nuevo usuario</h2>
  <form id="user-form">
  <input type="hidden" id="user-id">
  <div class="form-row">
    <div><label>Nombre completo</label><input id="u-display" required></div>
    <div><label>Usuario (login)</label><input id="u-username" required autocomplete="off"></div>
  </div>
  <div class="form-row">
    <div><label>Contraseña <span id="u-pw-hint" class="muted" style="font-weight:400">(vacío = no cambiar)</span></label>
      <input type="password" id="u-pw" autocomplete="new-password"></div>
    <div><label>Rol</label><select id="u-role">
      <option value="technician">Técnico</option>
      <option value="backoffice">Backoffice</option>
      <option value="admin">Administrador</option>
    </select></div>
  </div>
  <div class="form-row"><div><label>Activo</label>
    <select id="u-active"><option value="1">Sí</option><option value="0">No</option></select>
  </div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeUserModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<script>
var bp={json.dumps(BP)};
function openNewUser(){{
  document.getElementById('user-modal-title').textContent='Nuevo usuario';
  document.getElementById('user-id').value='';
  ['display','username','pw'].forEach(function(f){{document.getElementById('u-'+f).value='';}});
  document.getElementById('u-pw-hint').style.display='none';
  document.getElementById('u-role').value='technician';
  document.getElementById('u-active').value='1';
  document.getElementById('user-modal').classList.add('open');
}}
function editUser(u){{
  document.getElementById('user-modal-title').textContent='Editar usuario';
  document.getElementById('user-id').value=u.id;
  document.getElementById('u-display').value=u.display_name||'';
  document.getElementById('u-username').value=u.username||'';
  document.getElementById('u-pw').value='';
  document.getElementById('u-pw-hint').style.display='';
  document.getElementById('u-role').value=u.role||'technician';
  document.getElementById('u-active').value=u.active?'1':'0';
  document.getElementById('user-modal').classList.add('open');
}}
function closeUserModal(){{document.getElementById('user-modal').classList.remove('open');}}
document.getElementById('user-modal').onclick=function(e){{if(e.target===this)closeUserModal();}};
document.getElementById('user-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('user-id').value;
  var d={{display_name:document.getElementById('u-display').value,
    username:document.getElementById('u-username').value,
    role:document.getElementById('u-role').value,
    active:document.getElementById('u-active').value==='1'?1:0}};
  var pw=document.getElementById('u-pw').value;
  if(pw) d.password=pw;
  fetch(id?bp+'/api/users/'+id:bp+'/api/users',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
function delUser(id){{
  if(!confirm('¿Eliminar usuario?')) return;
  fetch(bp+'/api/users/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
}}
</script>"""
    return _shell("users", user, content)


# ── HTTP handler ──────────────────────────────────────────────────────────────
def _body(h) -> dict:
    n = int(h.headers.get("Content-Length", 0))
    if not n: return {}
    raw = h.rfile.read(n)
    ct = h.headers.get("Content-Type","")
    if "json" in ct:
        try: return json.loads(raw)
        except: return {}
    parts = {}
    for pair in raw.decode().split("&"):
        k,_,v = pair.partition("=")
        parts[unquote_plus(k)] = unquote_plus(v)
    return parts

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _send(self, code, body, ct="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _json(self, code, data):
        self._send(code, json.dumps(data, ensure_ascii=False), "application/json")

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def _auth(self):
        s = _get_sess(self)
        if not s: self._redirect(f"{BP}/login")
        return s

    def do_GET(self):
        p = urlparse(self.path)
        path = p.path
        qs = parse_qs(p.query)
        rel = path[len(BP):] if path.startswith(BP) and BP else path
        rel = rel or "/"

        if rel == "/login":
            self._send(200, _login_page()); return
        if rel == "/logout":
            _del_sess(self)
            self.send_response(302)
            self.send_header("Location", f"{BP}/login")
            self.send_header("Set-Cookie", f"nd_sess=; Path={BP or '/'}; Max-Age=0; HttpOnly")
            self.end_headers(); return

        sess = _get_sess(self)
        if not sess: self._redirect(f"{BP}/login"); return

        if rel in ("/", "/dashboard"):
            self._send(200, _dashboard(sess)); return
        if rel == "/projects":
            self._send(200, _projects_page(sess, qs.get("status",[""])[0], qs.get("view",["cards"])[0])); return
        m = re.match(r"^/projects/(\d+)$", rel)
        if m:
            html = _project_detail(sess, int(m.group(1)))
            self._send(200 if html else 404, html or "Not found"); return
        if rel == "/inventory":
            self._send(200, _inventory_page(sess)); return
        if rel == "/kit":
            self._send(200, _kit_page(sess)); return
        if rel == "/users":
            if sess.get("role") != "admin": self._redirect(f"{BP}/"); return
            self._send(200, _users_page(sess)); return

        # JSON GET APIs
        if rel == "/api/projects":
            self._json(200, rs(q("SELECT * FROM projects ORDER BY updated_at DESC"))); return
        m = re.match(r"^/api/projects/(\d+)/tasks$", rel)
        if m:
            self._json(200, rs(q("SELECT * FROM tasks WHERE project_id=?", (int(m.group(1)),)))); return
        m = re.match(r"^/api/tasks/(\d+)/checklist$", rel)
        if m:
            self._json(200, rs(q("SELECT * FROM task_checklist WHERE task_id=? ORDER BY pos,id",
                                 (int(m.group(1)),)))); return
        if rel == "/api/materials":
            self._json(200, rs(q("SELECT * FROM materials ORDER BY name"))); return
        if rel == "/api/kit":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            self._json(200, rs(q("SELECT k.*,m.name mat_name,m.code mat_code FROM tech_kit k JOIN materials m ON m.id=k.material_id"))); return

        self._send(404, "Not found")

    def do_POST(self):
        p = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) and BP else p.path
        rel = rel or "/"
        data = _body(self)

        # login (no auth required)
        if rel == "/api/login":
            un = (data.get("username","") or "").strip()
            pw = data.get("password","") or ""
            u = r2d(q1("SELECT * FROM users WHERE username=? AND active=1", (un,)))
            if not u or u["pw_hash"] != _hash(pw):
                self._send(200, _login_page("Usuario o contraseña incorrectos")); return
            tok = _new_sess(u)
            self.send_response(302)
            self.send_header("Location", f"{BP}/")
            self.send_header("Set-Cookie", f"nd_sess={tok}; Path={BP or '/'}; HttpOnly")
            self.end_headers(); return

        sess = _get_sess(self)
        if not sess: self._json(401, {"error":"Unauthorized"}); return

        # projects
        if rel == "/api/projects":
            n = (data.get("name","") or "").strip()
            c = (data.get("client","") or "").strip()
            if not n or not c: self._json(400, {"error":"Nombre y cliente requeridos"}); return
            pid = run("""INSERT INTO projects
                (name,client,description,status,priority,address,reference,
                 contact_name,contact_phone,estimated_hours,start_date,due_date,
                 assigned_to,created_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (n,c,data.get("description",""),data.get("status","active"),
                 data.get("priority","normal"),data.get("address",""),
                 data.get("reference",""),data.get("contact_name",""),
                 data.get("contact_phone",""),float(data.get("estimated_hours") or 0),
                 data.get("start_date",""),data.get("due_date",""),
                 data.get("assigned_to") or None, sess["id"]))
            self._json(201, {"id":pid}); return

        # tasks
        m = re.match(r"^/api/projects/(\d+)/tasks$", rel)
        if m:
            pid = int(m.group(1))
            t = (data.get("title","") or "").strip()
            if not t: self._json(400, {"error":"Título requerido"}); return
            tid = run("""INSERT INTO tasks
                (project_id,title,description,status,priority,due_date,created_by,updated_at)
                VALUES(?,?,?,?,?,?,?,datetime('now'))""",
                (pid,t,data.get("description",""),data.get("status","pending"),
                 data.get("priority","normal"),data.get("due_date",""),sess["id"]))
            run("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (pid,))
            self._json(201, {"id":tid}); return

        # task toggle
        m = re.match(r"^/api/tasks/(\d+)/toggle$", rel)
        if m:
            tid = int(m.group(1))
            st = data.get("status","pending")
            comp = str(_date.today()) if st == "done" else ""
            run("UPDATE tasks SET status=?,completed_date=?,updated_at=datetime('now') WHERE id=?",
                (st, comp, tid))
            task = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if task: run("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (task["project_id"],))
            self._json(200, {"ok":True}); return

        # checklist add
        m = re.match(r"^/api/tasks/(\d+)/checklist$", rel)
        if m:
            tid = int(m.group(1))
            label = (data.get("label","") or "").strip()
            if not label: self._json(400, {"error":"Label requerido"}); return
            max_pos = q1("SELECT COALESCE(MAX(pos),0) FROM task_checklist WHERE task_id=?", (tid,))
            cid = run("INSERT INTO task_checklist (task_id,label,done,pos) VALUES(?,?,0,?)",
                      (tid, label, (max_pos[0] if max_pos else 0)+1))
            self._json(201, {"id":cid}); return

        # project log
        m = re.match(r"^/api/projects/(\d+)/log$", rel)
        if m:
            pid = int(m.group(1))
            body = (data.get("body","") or "").strip()
            if not body: self._json(400, {"error":"Texto requerido"}); return
            hours = float(data.get("hours") or 0)
            lid = run("INSERT INTO project_logs (project_id,user_id,body,hours) VALUES(?,?,?,?)",
                      (pid, sess["id"], body, hours))
            run("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (pid,))
            self._json(201, {"id":lid}); return

        # materials
        if rel == "/api/materials":
            code = (data.get("code","") or "").strip()
            name = (data.get("name","") or "").strip()
            if not code or not name: self._json(400, {"error":"Código y nombre requeridos"}); return
            if q1("SELECT id FROM materials WHERE code=?", (code,)):
                self._json(400, {"error":f"Código '{code}' ya existe"}); return
            mid = run("""INSERT INTO materials
                (code,name,description,unit,stock_warehouse,stock_field,stock_min,category,updated_at)
                VALUES(?,?,?,?,?,?,?,?,datetime('now'))""",
                (code,name,data.get("description",""),data.get("unit","ud"),
                 int(data.get("stock_warehouse") or 0),int(data.get("stock_field") or 0),
                 int(data.get("stock_min") or 0),data.get("category","")))
            self._json(201, {"id":mid}); return

        # stock adjust
        m = re.match(r"^/api/materials/(\d+)/adjust$", rel)
        if m:
            mid = int(m.group(1))
            qty = int(data.get("qty") or 0)
            if qty == 0: self._json(400, {"error":"Cantidad 0"}); return
            mat = r2d(q1("SELECT * FROM materials WHERE id=?", (mid,)))
            if not mat: self._json(404, {"error":"Not found"}); return
            new_wh = mat["stock_warehouse"] + qty
            if new_wh < 0: self._json(400, {"error":"Stock insuficiente"}); return
            run("UPDATE materials SET stock_warehouse=?,updated_at=datetime('now') WHERE id=?", (new_wh, mid))
            direction = "in" if qty > 0 else "out"
            _stock_move(mid, abs(qty), direction, "adjust", 0, sess["id"], data.get("notes",""))
            self._json(200, {"ok":True,"new_stock":new_wh}); return

        # assignments
        m = re.match(r"^/api/projects/(\d+)/assignments$", rel)
        if m:
            pid = int(m.group(1))
            mid = data.get("material_id")
            if not mid: self._json(400, {"error":"Material requerido"}); return
            aid = run("""INSERT INTO assignments
                (project_id,material_id,qty_requested,qty_assigned,qty_consumed,
                 qty_returned,status,notes,created_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (pid,int(mid),int(data.get("qty_requested") or 0),
                 int(data.get("qty_assigned") or 0),int(data.get("qty_consumed") or 0),
                 int(data.get("qty_returned") or 0),data.get("status","requested"),
                 data.get("notes",""),sess["id"]))
            self._json(201, {"id":aid}); return

        # tech kit add
        if rel == "/api/kit":
            uid = int(data.get("user_id") or 0)
            mid = int(data.get("material_id") or 0)
            qty = int(data.get("qty") or 0)
            if not uid or not mid or qty < 1:
                self._json(400, {"error":"Datos incompletos"}); return
            mat = r2d(q1("SELECT * FROM materials WHERE id=?", (mid,)))
            if not mat: self._json(404, {"error":"Material no encontrado"}); return
            if mat["stock_warehouse"] < qty:
                self._json(400, {"error":f"Stock insuficiente ({mat['stock_warehouse']} disponibles)"}); return
            # upsert kit
            existing = r2d(q1("SELECT * FROM tech_kit WHERE user_id=? AND material_id=?", (uid, mid)))
            if existing:
                run("UPDATE tech_kit SET qty=qty+?,notes=?,updated_at=datetime('now') WHERE id=?",
                    (qty, data.get("notes",""), existing["id"]))
            else:
                run("INSERT INTO tech_kit (user_id,material_id,qty,notes) VALUES(?,?,?,?)",
                    (uid, mid, qty, data.get("notes","")))
            run("UPDATE materials SET stock_warehouse=stock_warehouse-?,updated_at=datetime('now') WHERE id=?",
                (qty, mid))
            _stock_move(mid, qty, "out", "kit", uid, sess["id"], f"Asignado al kit de usuario {uid}")
            self._json(201, {"ok":True}); return

        # kit return
        m = re.match(r"^/api/kit/(\d+)/return$", rel)
        if m:
            kid = int(m.group(1))
            qty = int(data.get("qty") or 0)
            ki = r2d(q1("SELECT * FROM tech_kit WHERE id=?", (kid,)))
            if not ki: self._json(404, {"error":"Not found"}); return
            if qty > ki["qty"]: self._json(400, {"error":"Cantidad mayor que la del kit"}); return
            run("UPDATE tech_kit SET qty=qty-?,updated_at=datetime('now') WHERE id=?", (qty, kid))
            run("UPDATE materials SET stock_warehouse=stock_warehouse+?,updated_at=datetime('now') WHERE id=?",
                (qty, ki["material_id"]))
            _stock_move(ki["material_id"], qty, "in", "kit_return", ki["user_id"], sess["id"],
                        f"Devuelto del kit usuario {ki['user_id']}")
            self._json(200, {"ok":True}); return

        # users
        if rel == "/api/users":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            un = (data.get("username","") or "").strip()
            dn = (data.get("display_name","") or "").strip()
            pw = (data.get("password","") or "").strip()
            if not un or not dn or not pw: self._json(400, {"error":"Datos incompletos"}); return
            if q1("SELECT id FROM users WHERE username=?", (un,)):
                self._json(400, {"error":"Usuario ya existe"}); return
            uid = run("INSERT INTO users (username,pw_hash,display_name,role,active) VALUES(?,?,?,?,?)",
                      (un,_hash(pw),dn,data.get("role","technician"),
                       1 if data.get("active",1) else 0))
            self._json(201, {"id":uid}); return

        self._json(404, {"error":"Not found"})

    def do_PUT(self):
        p = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) and BP else p.path
        data = _body(self)
        sess = _get_sess(self)
        if not sess: self._json(401, {"error":"Unauthorized"}); return

        m = re.match(r"^/api/projects/(\d+)$", rel)
        if m:
            pid = int(m.group(1))
            run("""UPDATE projects SET name=?,client=?,description=?,status=?,priority=?,
                address=?,reference=?,contact_name=?,contact_phone=?,estimated_hours=?,
                start_date=?,due_date=?,assigned_to=?,updated_at=datetime('now') WHERE id=?""",
                (data.get("name",""),data.get("client",""),data.get("description",""),
                 data.get("status","active"),data.get("priority","normal"),
                 data.get("address",""),data.get("reference",""),data.get("contact_name",""),
                 data.get("contact_phone",""),float(data.get("estimated_hours") or 0),
                 data.get("start_date",""),data.get("due_date",""),
                 data.get("assigned_to") or None, pid))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/tasks/(\d+)$", rel)
        if m:
            tid = int(m.group(1))
            task = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if not task: self._json(404, {"error":"Not found"}); return
            comp = str(_date.today()) if data.get("status") == "done" else ""
            run("""UPDATE tasks SET title=?,description=?,status=?,priority=?,
                due_date=?,completed_date=?,updated_at=datetime('now') WHERE id=?""",
                (data.get("title",""),data.get("description",""),data.get("status","pending"),
                 data.get("priority","normal"),data.get("due_date",""),comp,tid))
            run("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (task["project_id"],))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/checklist/(\d+)$", rel)
        if m:
            cid = int(m.group(1))
            done = 1 if data.get("done") else 0
            run("UPDATE task_checklist SET done=? WHERE id=?", (done, cid))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/materials/(\d+)$", rel)
        if m:
            mid = int(m.group(1))
            code = (data.get("code","") or "").strip()
            if q1("SELECT id FROM materials WHERE code=? AND id!=?", (code, mid)):
                self._json(400, {"error":f"Código '{code}' ya existe"}); return
            run("""UPDATE materials SET code=?,name=?,description=?,unit=?,
                stock_warehouse=?,stock_field=?,stock_min=?,category=?,
                updated_at=datetime('now') WHERE id=?""",
                (code,data.get("name",""),data.get("description",""),data.get("unit","ud"),
                 int(data.get("stock_warehouse") or 0),int(data.get("stock_field") or 0),
                 int(data.get("stock_min") or 0),data.get("category",""),mid))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/assignments/(\d+)$", rel)
        if m:
            aid = int(m.group(1))
            run("""UPDATE assignments SET qty_requested=?,qty_assigned=?,qty_consumed=?,
                qty_returned=?,status=?,notes=?,updated_at=datetime('now') WHERE id=?""",
                (int(data.get("qty_requested") or 0),int(data.get("qty_assigned") or 0),
                 int(data.get("qty_consumed") or 0),int(data.get("qty_returned") or 0),
                 data.get("status","requested"),data.get("notes",""),aid))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/users/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            uid = int(m.group(1))
            run("UPDATE users SET display_name=?,username=?,role=?,active=? WHERE id=?",
                (data.get("display_name",""),data.get("username",""),
                 data.get("role","technician"),1 if data.get("active",1) else 0,uid))
            if data.get("password"):
                run("UPDATE users SET pw_hash=? WHERE id=?", (_hash(data["password"]),uid))
            self._json(200, {"ok":True}); return

        self._json(404, {"error":"Not found"})

    def do_DELETE(self):
        p = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) and BP else p.path
        sess = _get_sess(self)
        if not sess: self._json(401, {"error":"Unauthorized"}); return

        m = re.match(r"^/api/projects/(\d+)$", rel)
        if m:
            run("DELETE FROM projects WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/tasks/(\d+)$", rel)
        if m:
            run("DELETE FROM tasks WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/checklist/(\d+)$", rel)
        if m:
            run("DELETE FROM task_checklist WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/materials/(\d+)$", rel)
        if m:
            mid = int(m.group(1))
            if q1("SELECT id FROM assignments WHERE material_id=? LIMIT 1", (mid,)):
                self._json(400, {"error":"Material en uso en proyectos"}); return
            if q1("SELECT id FROM tech_kit WHERE material_id=? AND qty>0 LIMIT 1", (mid,)):
                self._json(400, {"error":"Material en kit de técnicos"}); return
            run("DELETE FROM materials WHERE id=?", (mid,))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/users/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            uid = int(m.group(1))
            if uid == sess["id"]: self._json(400, {"error":"No puedes eliminarte a ti mismo"}); return
            run("DELETE FROM users WHERE id=?", (uid,))
            self._json(200, {"ok":True}); return

        self._json(404, {"error":"Not found"})

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"NuvoDesk v2 → http://localhost:{PORT}{BP}/  (admin/admin)")
    server.serve_forever()
