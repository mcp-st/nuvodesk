#!/usr/bin/env python3
"""NuvoDesk v3 — Nuvolink field project & materials management."""

import os, json, sqlite3, hashlib, secrets, threading, re, calendar as _cal, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote_plus
from datetime import datetime, date as _date, timedelta

PORT     = int(os.environ.get("PORT", 8014))
BP       = os.environ.get("BASE_PATH", "").rstrip("/")
DATA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH   = os.path.join(DATA_DIR, "nuvodesk.db")
FILES_DIR = os.path.join(DATA_DIR, "files")
os.makedirs(DATA_DIR,  exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

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
CREATE TABLE IF NOT EXISTS project_members (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_date TEXT DEFAULT '',
    end_date   TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, user_id)
);
CREATE TABLE IF NOT EXISTS schedule_slots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    slot_date  TEXT NOT NULL,
    hour_start INTEGER NOT NULL DEFAULT 8,
    hour_end   INTEGER NOT NULL DEFAULT 9,
    notes      TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS project_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mimetype      TEXT DEFAULT '',
    size_bytes    INTEGER DEFAULT 0,
    uploaded_by   INTEGER REFERENCES users(id),
    notes         TEXT DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS time_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    entry_type  TEXT NOT NULL DEFAULT 'work',
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS wo_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS wo_extras (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    quantity    REAL NOT NULL DEFAULT 1,
    unit        TEXT NOT NULL DEFAULT 'ud',
    notes       TEXT DEFAULT '',
    added_by    INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS equipment_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    brand         TEXT DEFAULT '',
    model         TEXT NOT NULL,
    serial_number TEXT DEFAULT '',
    quantity      INTEGER NOT NULL DEFAULT 1,
    notes         TEXT DEFAULT '',
    added_by      INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

MIGRATIONS = [
    "ALTER TABLE projects ADD COLUMN reference TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN contact_name TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN contact_phone TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN estimated_hours REAL DEFAULT 0",
    "ALTER TABLE projects ADD COLUMN work_type TEXT DEFAULT 'proyecto'",
    "ALTER TABLE projects ADD COLUMN wo_status TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN closed_at TEXT DEFAULT ''",
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

def _fmt_size(b):
    if b < 1024: return f"{b} B"
    if b < 1048576: return f"{b//1024} KB"
    return f"{b/1048576:.1f} MB"

def _parse_multipart(h):
    ct  = h.headers.get('Content-Type','')
    cl  = int(h.headers.get('Content-Length',0))
    body = h.rfile.read(cl)
    boundary = ''
    for part in ct.split(';'):
        s = part.strip()
        if s.startswith('boundary='):
            boundary = s[9:].strip('"')
    if not boundary:
        return {}, {}
    delim = ('--' + boundary).encode()
    fields, files = {}, {}
    for raw in body.split(delim)[1:]:
        if raw.strip() in (b'--', b'--\r\n', b''):
            continue
        if b'\r\n\r\n' in raw:
            hdr_raw, content = raw.split(b'\r\n\r\n', 1)
        elif b'\n\n' in raw:
            hdr_raw, content = raw.split(b'\n\n', 1)
        else:
            continue
        if content.endswith(b'\r\n'):
            content = content[:-2]
        name, fname, mime_part = '', None, ''
        for line in hdr_raw.decode('utf-8','replace').splitlines():
            if ':' not in line:
                continue
            k, _, v = line.partition(':')
            k = k.strip().lower()
            if k == 'content-disposition':
                for item in v.split(';'):
                    item = item.strip()
                    if item.startswith('name='):
                        name = item[5:].strip('"')
                    elif item.startswith('filename='):
                        fname = item[9:].strip('"')
            elif k == 'content-type':
                mime_part = v.strip()
        if fname is not None:
            files[name] = {'filename': fname, 'data': content, 'mime': mime_part}
        else:
            try:
                fields[name] = content.decode('utf-8')
            except Exception:
                fields[name] = ''
    return fields, files

def _stock_move(material_id, qty, direction, source, ref_id, user_id, notes=""):
    run("INSERT INTO stock_movements (material_id,qty,direction,source,ref_id,user_id,notes) VALUES (?,?,?,?,?,?,?)",
        (material_id, qty, direction, source, ref_id, user_id, notes))

PROJ_COLORS = ["#2563eb","#16a34a","#d97706","#dc2626","#7c3aed","#0d9488",
               "#db2777","#ea580c","#65a30d","#0284c7"]
def _pcolor(pid): return PROJ_COLORS[int(pid) % len(PROJ_COLORS)]

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

WORK_TYPES = {
    'averia':        {'name': 'Avería',        'color': '#dc2626', 'icon': '⚡'},
    'instalacion':   {'name': 'Instalación',   'color': '#2563eb', 'icon': '🔧'},
    'mantenimiento': {'name': 'Mantenimiento', 'color': '#d97706', 'icon': '🔨'},
    'inspeccion':    {'name': 'Inspección',    'color': '#7c3aed', 'icon': '🔍'},
    'proyecto':      {'name': 'Proyecto',      'color': '#0d9488', 'icon': '📋'},
}

def _fmt_duration(secs):
    if not secs or secs < 0: return "0h 00m"
    return f"{int(secs//3600)}h {int((secs%3600)//60):02d}m"

def _wt_badge(wt):
    info = WORK_TYPES.get(wt or 'proyecto', WORK_TYPES['proyecto'])
    c = info['color']
    return f'<span class="badge" style="background:{c}22;color:{c}">{info["icon"]} {info["name"]}</span>'

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
  --bg:#eef2f7;--bg2:#fff;--bg3:#f8fafc;--bg4:#f0f5fb;
  --text:#1a2536;--muted:#64748b;--border:#dce4ee;
  --blue:#2563eb;--blue-dim:rgba(37,99,235,.09);
  --green:#16a34a;--green-dim:rgba(22,163,74,.1);
  --amber:#d97706;--amber-dim:rgba(217,119,6,.09);
  --red:#dc2626;--red-dim:rgba(220,38,38,.09);
  --violet:#7c3aed;--violet-dim:rgba(124,58,237,.09);
  --teal:#0d9488;--teal-dim:rgba(13,148,136,.09);
  --side-bg:#0f1f35;--side-text:#94aec8;--sidebar-w:228px;
  --radius:10px;--shadow:0 1px 3px rgba(0,0,0,.06),0 1px 2px rgba(0,0,0,.04);
  --shadow-md:0 4px 12px rgba(0,0,0,.09),0 2px 4px rgba(0,0,0,.05);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;
  background:var(--bg);color:var(--text);display:flex;min-height:100vh}
a{color:var(--blue);text-decoration:none}
button{font-family:inherit;cursor:pointer}

/* ── sidebar ── */
#sidebar{width:var(--sidebar-w);background:var(--side-bg);color:var(--side-text);
  display:flex;flex-direction:column;min-height:100vh;
  position:fixed;top:0;left:0;z-index:200;transition:transform .22s ease;flex-shrink:0}
/* logo */
.nd-logo{padding:15px 13px 13px;border-bottom:1px solid rgba(255,255,255,.07);
  display:flex;align-items:center;gap:10px;overflow:hidden;flex-shrink:0}
.nd-logo-mark{width:33px;height:33px;background:linear-gradient(135deg,#4db6ac,#26a69a);
  border-radius:8px;display:flex;align-items:center;justify-content:center;
  font-size:1.05rem;font-weight:900;color:#fff;flex-shrink:0}
.nd-logo-text{overflow:hidden;min-width:0}
.nd-logo-name{font-size:1rem;font-weight:800;color:#fff;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;line-height:1.2;letter-spacing:-.2px}
.nd-logo-sub{font-size:.52rem;color:#4db6ac;letter-spacing:1.8px;text-transform:uppercase;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;display:block}
/* sidebar search */
.sb-search{padding:9px 11px 9px;border-bottom:1px solid rgba(255,255,255,.07);position:relative}
.sb-search-inner{position:relative;display:flex;align-items:center}
.sb-search-inner::before{content:'⌕';position:absolute;left:9px;color:#64748b;
  font-size:1rem;pointer-events:none}
.sb-search-inner input{width:100%;padding:6px 10px 6px 27px;border-radius:18px;border:none;
  background:rgba(255,255,255,.08);color:#e2eaf3;font-size:.8rem;outline:none;
  transition:background .15s;font-family:inherit}
.sb-search-inner input::placeholder{color:#4a6077}
.sb-search-inner input:focus{background:rgba(255,255,255,.13)}
.search-drop{position:absolute;left:11px;right:11px;top:calc(100% + 3px);background:#fff;
  border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.25);z-index:400;
  max-height:300px;overflow-y:auto;display:none}
.search-drop.open{display:block}
.search-item{display:block;padding:9px 13px;text-decoration:none;
  border-bottom:1px solid #f0f4f8;transition:background .1s;cursor:pointer}
.search-item:last-child{border-bottom:none}
.search-item:hover{background:#f4f8ff}
.search-item-type{font-size:.63rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.8px;font-weight:700}
.search-item-title{font-weight:600;color:#1a2536;margin-top:1px;font-size:.86rem}
.search-item-sub{font-size:.75rem;color:#64748b}
/* nav */
#sidebar nav{flex:1;padding:6px 0;overflow-y:auto}
#sidebar nav a{display:flex;align-items:center;gap:10px;padding:9px 14px 9px 16px;
  color:var(--side-text);font-size:.86rem;font-weight:500;
  border-left:3px solid transparent;transition:.15s;margin:1px 8px 1px 0;border-radius:0 7px 7px 0}
#sidebar nav a:hover{background:rgba(255,255,255,.07);color:#c8d8ec}
#sidebar nav a.active{background:rgba(77,182,172,.12);color:#4db6ac;border-left-color:#4db6ac}
#sidebar nav a .ic{width:20px;text-align:center;font-size:.95rem;flex-shrink:0}
#sidebar .user-area{padding:12px 14px;border-top:1px solid rgba(255,255,255,.07);font-size:.8rem}
#sidebar .user-area strong{color:#e2eaf3;display:block;margin-bottom:2px;font-size:.84rem}
#sidebar .user-area a{color:#4a6077;font-size:.75rem;transition:color .15s}
#sidebar .user-area a:hover{color:#94aec8}

/* ── overlay ── */
#overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:199;backdrop-filter:blur(2px)}
#overlay.open{display:block}

/* ── main ── */
#main{margin-left:var(--sidebar-w);flex:1;padding:28px 32px;min-width:0}

/* ── bottom nav (mobile only) ── */
#bottom-nav{display:none}

/* ── headings ── */
h1{font-size:1.35rem;font-weight:700;color:var(--text);margin-bottom:20px;letter-spacing:-.3px}
h2{font-size:1.05rem;font-weight:700;margin-bottom:14px}
h3{font-size:.92rem;font-weight:700;margin-bottom:8px}

/* ── cards ── */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
  padding:22px;margin-bottom:18px;box-shadow:var(--shadow)}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:14px;margin-bottom:22px}
.kpi{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
  padding:18px 20px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.kpi::after{content:'';position:absolute;top:0;left:0;bottom:0;width:3px;background:var(--blue)}
.kpi.g::after{background:var(--green)}
.kpi.a::after{background:var(--amber)}
.kpi.r::after{background:var(--red)}
.kpi .val{font-size:2rem;font-weight:800;line-height:1;letter-spacing:-.5px}
.kpi .lbl{font-size:.7rem;color:var(--muted);margin-top:5px;text-transform:uppercase;letter-spacing:.5px;font-weight:600}

/* ── table ── */
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.7rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.6px;padding:9px 14px;
  border-bottom:2px solid var(--border);background:var(--bg3);white-space:nowrap}
td{padding:11px 14px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafcff}

/* ── buttons ── */
.btn{display:inline-flex;align-items:center;gap:5px;padding:7px 15px;
  border-radius:8px;font-size:.83rem;font-weight:600;border:none;transition:all .15s}
.btn:active{transform:scale(.97)}
.btn:hover{opacity:.87}
.btn-primary{background:var(--blue);color:#fff;box-shadow:0 1px 4px rgba(37,99,235,.2)}
.btn-primary:hover{box-shadow:0 3px 10px rgba(37,99,235,.3);transform:translateY(-1px)}
.btn-primary:active{transform:scale(.97) translateY(0)}
.btn-success{background:var(--green);color:#fff}
.btn-danger{background:var(--red);color:#fff}
.btn-amber{background:var(--amber);color:#fff}
.btn-ghost{background:transparent;color:var(--blue);border:1.5px solid var(--blue)}
.btn-ghost:hover{background:var(--blue-dim)}
.btn-sm{padding:5px 11px;font-size:.78rem}
.btn-icon{padding:5px 8px;font-size:.9rem;line-height:1;border-radius:6px}

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
.modal-bg{display:none;position:fixed;inset:0;background:rgba(5,15,35,.55);
  z-index:500;align-items:center;justify-content:center;padding:16px}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:14px;padding:28px;width:min(580px,100%);
  max-height:92vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.2)}
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
.alert{padding:11px 16px;border-radius:8px;margin-bottom:14px;font-size:.88rem;
  display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap}
.alert-red{background:var(--red-dim);color:var(--red);border:1px solid rgba(220,38,38,.2)}
.alert-amber{background:var(--amber-dim);color:var(--amber);border:1px solid rgba(217,119,6,.2)}
.alert-green{background:var(--green-dim);color:var(--green);border:1px solid rgba(22,163,74,.2)}

/* ── member avatars ── */
.avatar-row{display:flex;gap:3px;flex-wrap:wrap;margin-top:6px}
.avatar{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:.6rem;font-weight:700;color:#fff;flex-shrink:0;
  border:2px solid #fff;cursor:default}
.avatar-sm{width:20px;height:20px;font-size:.5rem;border-width:1.5px}

/* ── calendar ── */
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-bottom:20px}
.cal-dow{text-align:center;font-size:.68rem;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.5px;padding:4px 0}
.cal-day{background:var(--bg2);border:1px solid var(--border);border-radius:7px;
  min-height:80px;padding:5px;font-size:.78rem;position:relative;overflow:hidden;
  display:block;text-decoration:none;color:var(--text);transition:border-color .15s}
.cal-day:hover{border-color:var(--blue)}
.cal-day.today{border-color:var(--blue);background:#f0f5ff}
.cal-day.other-month{background:var(--bg3);opacity:.55;pointer-events:none}
.cal-day-num{font-weight:700;font-size:.75rem;color:var(--muted);margin-bottom:3px}
.cal-day.today .cal-day-num{color:var(--blue)}
.cal-chip{display:block;padding:2px 5px;border-radius:4px;font-size:.65rem;
  font-weight:600;color:#fff;margin-bottom:2px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;cursor:default}

/* ── matrix (calendar list) ── */
.matrix-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:16px}
.matrix{border-collapse:collapse;white-space:nowrap;font-size:.72rem}
.matrix th{padding:5px 8px;border:1px solid var(--border);background:var(--bg3);
  font-weight:700;text-align:center;position:sticky;left:0;z-index:2}
.matrix th.tech-col{text-align:left;min-width:120px;left:0;z-index:3}
.matrix td{padding:2px 3px;border:1px solid var(--border);min-width:28px;
  text-align:center;vertical-align:middle}
.matrix-cell{display:block;padding:1px 4px;border-radius:3px;color:#fff;
  font-weight:600;font-size:.6rem;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;max-width:48px}
.matrix td.today-col{background:#f0f5ff}

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
.progress{background:#e2e8f0;border-radius:4px;height:5px;overflow:hidden}
.progress-bar{height:100%;border-radius:4px;background:var(--blue);transition:width .4s ease}

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
  .modal{padding:18px;border-radius:10px}
  .tabs{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .tab-btn{white-space:nowrap;padding:8px 12px;font-size:.82rem}
  .kanban{grid-template-columns:repeat(4,80vw)!important;overflow-x:auto;
    scroll-snap-type:x mandatory;padding-bottom:8px;gap:10px!important}
  .kanban-col{scroll-snap-align:start}
  .proj-cards{grid-template-columns:repeat(auto-fill,minmax(260px,300px))!important}
}
@media(min-width:769px){
  #menu-btn{display:none!important}
}
#menu-btn{position:fixed;top:10px;left:10px;z-index:210;
  background:var(--side-bg);color:#fff;border:none;border-radius:7px;
  width:38px;height:38px;font-size:1.1rem;display:flex;align-items:center;justify-content:center;
  box-shadow:0 2px 8px rgba(0,0,0,.2)}

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
.task-card{background:#fff;border:1px solid var(--border);border-radius:8px;
  padding:11px 13px;margin-bottom:8px;cursor:grab;box-shadow:var(--shadow);
  user-select:none;transition:box-shadow .15s,transform .12s;position:relative}
.task-card:hover{box-shadow:var(--shadow-md);transform:translateY(-1px)}
.task-card.dragging{opacity:.4;transform:rotate(1.5deg);box-shadow:0 8px 24px rgba(0,0,0,.18);cursor:grabbing}
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

/* ── day view (schedule) ── */
.day-matrix{width:100%;border-collapse:collapse;font-size:.78rem}
.day-matrix th{padding:5px 8px;background:var(--bg3);border:1px solid var(--border);
  font-weight:700;text-align:center;white-space:nowrap;position:sticky;top:0;z-index:2}
.day-matrix th.hour-col{text-align:right;color:var(--muted);min-width:52px;
  font-weight:600;font-size:.72rem;position:sticky;left:0;z-index:3;background:var(--bg3)}
.day-matrix td{border:1px solid var(--border);padding:0;height:38px;
  min-width:110px;vertical-align:top;position:relative}
.day-matrix td.hour-label{text-align:right;padding:5px 8px;color:var(--muted);
  font-size:.72rem;background:var(--bg3);position:sticky;left:0;z-index:1;white-space:nowrap}
.day-matrix td.now-row{background:#fefce8}
.slot-block{display:flex;align-items:flex-start;gap:4px;padding:3px 5px;
  border-radius:4px;font-size:.68rem;font-weight:600;color:#fff;margin:2px;
  line-height:1.3;position:relative}
.slot-block .slot-del{position:absolute;top:1px;right:2px;background:rgba(0,0,0,.25);
  border:none;color:#fff;border-radius:2px;font-size:.6rem;padding:0 3px;
  cursor:pointer;opacity:0;transition:opacity .15s}
.slot-block:hover .slot-del{opacity:1}
.day-nav{display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap}

/* ── files ── */
.file-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
  gap:12px;margin-top:14px}
.file-card{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);
  overflow:hidden;position:relative;transition:box-shadow .15s}
.file-card:hover{box-shadow:var(--shadow-md)}
.file-thumb{width:100%;height:100px;object-fit:cover;display:block}
.file-icon{width:100%;height:100px;display:flex;align-items:center;justify-content:center;
  font-size:2.2rem;background:var(--bg4)}
.file-info{padding:6px 8px;font-size:.72rem}
.file-info .file-name{font-weight:600;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;color:var(--text);margin-bottom:2px}
.file-info .file-meta{color:var(--muted)}
.file-del{position:absolute;top:4px;right:4px;background:rgba(0,0,0,.5);color:#fff;
  border:none;border-radius:4px;width:20px;height:20px;font-size:.7rem;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  opacity:0;transition:opacity .15s}
.file-card:hover .file-del{opacity:1}
.upload-area{border:2px dashed var(--border);border-radius:var(--radius);
  padding:24px;text-align:center;margin-bottom:14px;cursor:pointer;
  transition:border-color .2s,background .2s}
.upload-area:hover,.upload-area.drag-over{border-color:var(--blue);background:var(--blue-dim)}
.upload-area input[type=file]{display:none}

/* ── timer ── */
.timer-banner{display:flex;align-items:center;gap:16px;padding:14px 20px;
  background:linear-gradient(135deg,#14532d,#166534);color:#fff;
  border-radius:var(--radius);margin-bottom:16px;flex-wrap:wrap}
.timer-banner .timer-lbl{font-size:.72rem;opacity:.75;text-transform:uppercase;
  letter-spacing:.8px;margin-bottom:2px}
.timer-banner .timer-time{font-size:1.6rem;font-weight:800;font-family:monospace;
  letter-spacing:.5px;line-height:1}
.timer-btn-start{background:#16a34a;color:#fff;border:none;border-radius:8px;
  padding:11px 22px;font-size:.9rem;font-weight:700;cursor:pointer;
  box-shadow:0 2px 8px rgba(22,163,74,.3);transition:all .15s;
  display:inline-flex;align-items:center;gap:7px}
.timer-btn-start:hover{background:#15803d;transform:translateY(-1px)}
.timer-btn-stop{background:#dc2626;color:#fff;border:none;border-radius:8px;
  padding:11px 22px;font-size:.9rem;font-weight:700;cursor:pointer;
  box-shadow:0 2px 8px rgba(220,38,38,.3);transition:all .15s;
  display:inline-flex;align-items:center;gap:7px}
.timer-btn-stop:hover{background:#b91c1c;transform:translateY(-1px)}
.time-summary-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));
  gap:12px;margin-bottom:20px}
.time-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 18px;box-shadow:var(--shadow)}
.time-card .tc-name{font-weight:700;font-size:.86rem;margin-bottom:3px;overflow:hidden;
  white-space:nowrap;text-overflow:ellipsis}
.time-card .tc-hours{font-size:1.5rem;font-weight:800;color:var(--blue);line-height:1.1}
.time-card .tc-detail{font-size:.71rem;color:var(--muted);margin-top:3px}

/* ── comment thread ── */
.comment-thread{list-style:none;margin-bottom:0}
.comment-thread li{display:flex;gap:11px;padding-bottom:13px}
.comment-bubble{flex:1;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius);padding:10px 13px}
.comment-meta{font-size:.72rem;color:var(--muted);margin-bottom:5px;
  display:flex;align-items:center;gap:6px}
.comment-body{line-height:1.55;white-space:pre-wrap;word-break:break-word;font-size:.87rem}
.comment-own .comment-bubble{background:#eff6ff;border-color:#bfdbfe}
.comment-add{background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius);padding:14px}
.comment-add textarea{margin-bottom:10px}

/* ── inline add form ── */
.inline-add{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 16px;margin-bottom:16px}
.inline-add .row{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
.inline-add .row .field{flex:1;min-width:110px;margin:0}
.inline-add .row button{flex-shrink:0;align-self:flex-end}

/* ── workload grid ── */
.wl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:20px}
.wl-grid{display:grid;min-width:700px}
.wl-hd{background:var(--bg3);border:1px solid var(--border);padding:7px 10px;
  font-size:.7rem;font-weight:700;text-align:center;text-transform:uppercase;letter-spacing:.5px}
.wl-name{background:var(--bg3);border:1px solid var(--border);padding:8px 10px;
  font-size:.82rem;font-weight:700;display:flex;align-items:center;min-width:140px}
.wl-cell{border:1px solid var(--border);padding:4px;min-height:56px;background:var(--bg2)}
.wl-cell.wl-today{background:#eff6ff}
.wl-entry{font-size:.64rem;font-weight:700;padding:2px 5px;border-radius:4px;
  color:#fff;margin-bottom:2px;line-height:1.35;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
"""

# ── shell ─────────────────────────────────────────────────────────────────────
def _shell(page, user, content, extra_head=""):
    bp = BP
    nav = [
        ("dashboard", f"{bp}/",           "⊞",  "Dashboard"),
        ("projects",  f"{bp}/projects",   "📋", "Proyectos"),
        ("workload",  f"{bp}/workload",   "📊", "Cargas"),
        ("calendar",  f"{bp}/calendar",   "🗓", "Calendario"),
        ("inventory", f"{bp}/inventory",  "📦", "Inventario"),
        ("kit",       f"{bp}/kit",        "🎒", "Kit campo"),
        ("users",     f"{bp}/users",      "👥", "Usuarios"),
        ("download",  f"{bp}/download",   "📲", "App móvil"),
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
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="NuvoDesk">
<meta name="theme-color" content="#1e40af">
<link rel="manifest" href="{bp}/manifest.webmanifest">
<title>NuvoDesk</title>
<style>{_css()}</style>
{extra_head}
</head>
<body>
<button id="menu-btn" onclick="toggleSidebar()" aria-label="Menú">☰</button>
<div id="overlay" onclick="closeSidebar()"></div>
<div id="sidebar">
  <div class="nd-logo">
    <div class="nd-logo-mark">N</div>
    <div class="nd-logo-text">
      <div class="nd-logo-name">NuvoDesk</div>
      <span class="nd-logo-sub">Nuvolink · Telecoms</span>
    </div>
  </div>
  <div class="sb-search">
    <div class="sb-search-inner">
      <input id="search-inp" type="search" placeholder="Buscar proyectos, tareas..." autocomplete="off">
    </div>
    <div id="search-results" class="search-drop"></div>
  </div>
  <nav>{sidebar_links}</nav>
  <div class="user-area">
    <strong>{_esc(user.get('display_name',''))}</strong>
    {_esc(role_lbl)} &nbsp;&middot;&nbsp; <a href="{bp}/logout">Salir</a>
  </div>
</div>
<div id="main">{content}</div>
<nav id="bottom-nav">{bottom_links}</nav>
<script>
var bp={json.dumps(BP)};
function toggleSidebar(){{
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('overlay').classList.toggle('open');
}}
function closeSidebar(){{
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('overlay').classList.remove('open');
}}
document.querySelectorAll('#sidebar nav a').forEach(function(a){{
  a.addEventListener('click', function(){{
    if(window.innerWidth<=768) closeSidebar();
  }});
}});
var _st=null;
document.getElementById('search-inp').addEventListener('input',function(){{
  clearTimeout(_st);
  var q=this.value.trim();
  var drop=document.getElementById('search-results');
  if(q.length<2){{drop.classList.remove('open');return;}}
  _st=setTimeout(function(){{
    fetch(bp+'/api/search?q='+encodeURIComponent(q))
      .then(function(r){{return r.json();}})
      .then(function(d){{_renderSearch(d);}});
  }},250);
}});
function _renderSearch(results){{
  var el=document.getElementById('search-results');
  if(!results.length){{
    el.innerHTML='<div class="search-item" style="color:#94a3b8;cursor:default">Sin resultados</div>';
    el.classList.add('open');return;
  }}
  el.innerHTML=results.map(function(r){{
    var url=bp+(r.type==='proyecto'?'/projects/'+r.id:
                r.type==='tarea'?'/projects/'+r.pid:'/inventory');
    var t=(r.title||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
    var s=(r.sub||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
    return '<a class="search-item" href="'+url+'">'
      +'<div class="search-item-type">'+r.type+'</div>'
      +'<div class="search-item-title">'+t+'</div>'
      +(s?'<div class="search-item-sub">'+s+'</div>':'')
      +'</a>';
  }}).join('');
  el.classList.add('open');
}}
document.addEventListener('click',function(e){{
  if(!e.target.closest('.sb-search'))
    document.getElementById('search-results').classList.remove('open');
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
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') task_d,
        (SELECT COUNT(*) FROM project_members pm WHERE pm.project_id=p.id) member_count
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
        mc = p.get('member_count', 0)
        members_html = (f'<span style="font-size:.75rem;color:var(--muted)">👥 {mc}</span>' if mc else "")
        safe_p = {k: v for k, v in dict(p).items() if isinstance(v, (str, int, float, type(None)))}
        wt_html = _wt_badge(p.get('work_type') or 'proyecto')
        cards_html += (
            f'<a class="proj-card" href="{BP}/projects/{p["id"]}">'
            f'<div class="proj-card-strip" style="background:{sc}"></div>'
            f'<div class="proj-card-body">'
            f'<div class="proj-card-name">{_esc(p["name"])}</div>'
            f'<div class="proj-card-client">{_esc(p["client"])}</div>'
            f'<div class="proj-card-tags">'
            f'{wt_html}'
            f'{_badge(p["status"])}'
            f'<span style="color:{pc};font-size:.75rem;font-weight:700">▲ {plabel}</span>'
            f'{ref_chip}</div>'
            f'{prog_html}'
            f'</div>'
            f'<div class="proj-card-foot">'
            f'<span>{due_html}</span>'
            f'<span style="display:flex;align-items:center;gap:6px">{members_html}{tech_html}</span>'
            f'<button onclick="event.preventDefault();event.stopPropagation();editProject({json.dumps(safe_p)})" '
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
        safe_p2 = {k: v for k, v in dict(p).items() if isinstance(v, (str, int, float, type(None)))}
        rows += (f'<tr><td><a href="{BP}/projects/{p["id"]}" class="fw7">{_esc(p["name"])}</a>'
            f'{ref_html}<br><span class="muted" style="font-size:.75rem">{_esc(p["client"])}</span></td>'
            f'<td>{_badge(p["status"])}</td><td class="col-m-hide">{_pbadge(p["priority"])}</td>'
            f'<td class="muted col-m-hide">{_esc(p["tech"] or "—")}</td>'
            f'<td class="muted col-m-hide">{_esc((p["due_date"] or "—")[:10])}</td>'
            f'<td class="col-m-hide">{prog}</td>'
            f'<td><button class="btn btn-ghost btn-icon" onclick="editProject({json.dumps(safe_p2)})">✏️</button>'
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
  <input type="hidden" id="f-id">
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
  <div class="form-row cols3">
    <div><label>Tipo de trabajo</label><select id="f-wtype">
      <option value="proyecto">📋 Proyecto</option>
      <option value="instalacion">🔧 Instalación</option>
      <option value="averia">⚡ Avería</option>
      <option value="mantenimiento">🔨 Mantenimiento</option>
      <option value="inspeccion">🔍 Inspección</option>
    </select></div>
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
  document.getElementById('f-wtype').value='proyecto';
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
  document.getElementById('f-wtype').value=p.work_type||'proyecto';
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
    work_type:document.getElementById('f-wtype').value,
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

# ── file grid helper ─────────────────────────────────────────────────────────
def _build_file_grid(pfiles, pid):
    if not pfiles:
        return '<p class="muted" style="text-align:center;padding:24px;grid-column:1/-1">Sin archivos — arrastra aquí o usa el área de carga</p>'
    imgs = {'image/jpeg','image/png','image/gif','image/webp','image/svg+xml'}
    cards = ""
    for f in pfiles:
        url = f'{BP}/api/projects/{pid}/files/{f["filename"]}'
        is_img = f['mimetype'] in imgs or f['mimetype'].startswith('image/')
        icon = '🖼' if is_img else ('📄' if 'pdf' in f['mimetype'] else
               '📊' if 'sheet' in f['mimetype'] or 'excel' in f['mimetype'] else
               '📝' if 'word' in f['mimetype'] or 'doc' in f['mimetype'] else '📎')
        preview = (f'<a href="{url}" target="_blank"><img src="{url}" class="file-thumb" loading="lazy"></a>'
                   if is_img else
                   f'<a href="{url}" download="{_esc(f["original_name"])}" class="file-icon">{icon}</a>')
        cards += (
            f'<div class="file-card">'
            f'{preview}'
            f'<button class="file-del" onclick="delFile({f["id"]})" title="Eliminar">✕</button>'
            f'<div class="file-info">'
            f'<div class="file-name" title="{_esc(f["original_name"])}">{_esc(f["original_name"])}</div>'
            f'<div class="file-meta">{_fmt_size(f["size_bytes"])} · {_esc(f["created_at"][:10])}</div>'
            f'</div></div>')
    return cards

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

    members = rs(q("""SELECT pm.*,u.display_name uname,u.role urole
        FROM project_members pm JOIN users u ON u.id=pm.user_id
        WHERE pm.project_id=? ORDER BY pm.start_date,u.display_name""", (pid,)))

    all_users = rs(q("SELECT id,display_name,role FROM users WHERE active=1 ORDER BY display_name"))
    user_opts = "".join(
        f'<option value="{u["id"]}">{_esc(u["display_name"])}</option>' for u in all_users)

    pfiles = rs(q("""SELECT * FROM project_files WHERE project_id=? ORDER BY created_at DESC""", (pid,)))

    # ── new: time entries, comments, extras, equipment ──
    time_entries_all = rs(q("""SELECT te.*,u.display_name uname
        FROM time_entries te JOIN users u ON u.id=te.user_id
        WHERE te.project_id=? ORDER BY te.started_at DESC LIMIT 100""", (pid,)))

    active_timer = r2d(q1("""SELECT * FROM time_entries
        WHERE project_id=? AND user_id=? AND ended_at IS NULL""",
        (pid, user['id'])))

    time_summary_rows = rs(q("""SELECT u.display_name uname,
        COUNT(*) entries,
        COUNT(DISTINCT date(te.started_at)) days,
        COALESCE(SUM(CASE WHEN te.ended_at IS NOT NULL
            THEN (julianday(te.ended_at)-julianday(te.started_at))*86400 ELSE 0 END),0) total_secs
        FROM time_entries te JOIN users u ON u.id=te.user_id
        WHERE te.project_id=? AND te.ended_at IS NOT NULL
        GROUP BY u.id ORDER BY total_secs DESC""", (pid,)))

    comments = rs(q("""SELECT wc.*,u.display_name uname
        FROM wo_comments wc JOIN users u ON u.id=wc.user_id
        WHERE wc.project_id=? ORDER BY wc.created_at ASC""", (pid,)))

    extras = rs(q("""SELECT we.*,u.display_name uname
        FROM wo_extras we LEFT JOIN users u ON u.id=we.added_by
        WHERE we.project_id=? ORDER BY we.created_at DESC""", (pid,)))

    equipment = rs(q("""SELECT ei.*,u.display_name uname
        FROM equipment_items ei LEFT JOIN users u ON u.id=ei.added_by
        WHERE ei.project_id=? ORDER BY ei.created_at DESC""", (pid,)))

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

    # ── equipo tab content ──
    member_rows = ""
    for mb in members:
        role_lbl = {"admin":"Admin","technician":"Técnico","backoffice":"Backoffice"}.get(mb['urole'], mb['urole'])
        initials_m = "".join(w[0].upper() for w in mb['uname'].split()[:2])
        col = _pcolor(mb['user_id'])
        date_range = ""
        if mb.get('start_date') or mb.get('end_date'):
            date_range = f'{(mb.get("start_date") or "")[:10]} → {(mb.get("end_date") or "")[:10]}'
        member_rows += (
            f'<tr>'
            f'<td style="width:36px"><div class="avatar" style="background:{col}">{_esc(initials_m)}</div></td>'
            f'<td><span class="fw7">{_esc(mb["uname"])}</span>'
            f'<br><span class="muted" style="font-size:.75rem">{_esc(role_lbl)}</span></td>'
            f'<td class="muted col-m-hide" style="font-size:.8rem">{_esc(date_range or "Todo el proyecto")}</td>'
            f'<td class="muted col-m-hide" style="font-size:.8rem">{_esc(mb.get("notes",""))}</td>'
            f'<td><button class="btn btn-danger btn-icon" onclick="removeMember({mb["id"]})">✕</button></td>'
            f'</tr>')

    # member avatars for header
    member_avatars = "".join(
        f'<div class="avatar" style="background:{_pcolor(mb["user_id"])}" title="{_esc(mb["uname"])}">'
        f'{"".join(w[0].upper() for w in mb["uname"].split()[:2])}</div>'
        for mb in members[:6])
    if len(members) > 6:
        member_avatars += f'<div class="avatar" style="background:#94a3b8">+{len(members)-6}</div>'

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

    # ── build time tab HTML ──
    time_summary_html = ""
    for ts in time_summary_rows:
        dur = _fmt_duration(ts['total_secs'])
        time_summary_html += (f'<div class="time-card">'
            f'<div class="tc-name">{_esc(ts["uname"])}</div>'
            f'<div class="tc-hours">{dur}</div>'
            f'<div class="tc-detail">{ts["days"]} días · {ts["entries"]} registros</div>'
            f'</div>')

    te_rows = ""
    for te in time_entries_all:
        started = (te['started_at'] or '')[:16]
        if te['ended_at']:
            try:
                from datetime import datetime as _dt2
                dur = _fmt_duration((_dt2.fromisoformat(te['ended_at'])-_dt2.fromisoformat(te['started_at'])).total_seconds())
            except Exception:
                dur = '—'
        else:
            dur = '<span style="color:var(--green);font-weight:700">● En curso</span>'
        type_lbl = {'work':'Trabajo','travel':'Desplazamiento','wait':'Espera'}.get(te.get('entry_type','work'), te.get('entry_type',''))
        te_id = te['id']
        del_btn = '' if te['ended_at'] is None else f'<button class="btn btn-danger btn-icon" onclick="delTimeEntry({te_id})">✕</button>'
        te_rows += (f'<tr>'
            f'<td class="muted" style="font-size:.75rem;white-space:nowrap">{_esc(started)}</td>'
            f'<td>{_esc(te["uname"])}</td>'
            f'<td><span class="chip" style="font-size:.7rem">{_esc(type_lbl)}</span></td>'
            f'<td style="font-weight:700">{dur}</td>'
            f'<td class="muted col-m-hide" style="font-size:.8rem">{_esc(te.get("notes","") or "")}</td>'
            f'<td>{del_btn}</td></tr>')

    if active_timer:
        timer_start_html = '<div class="alert alert-green" style="margin-bottom:16px">⏱ Tienes una jornada activa en este proyecto — para el temporizador para guardarla.</div>'
    else:
        timer_start_html = f"""<div style="display:flex;align-items:flex-end;gap:12px;margin-bottom:20px;flex-wrap:wrap">
  <div class="field" style="margin:0">
    <label>Tipo</label>
    <select id="te-type" style="width:auto">
      <option value="work">🔧 Trabajo</option>
      <option value="travel">🚗 Desplazamiento</option>
      <option value="wait">⏳ Espera</option>
    </select>
  </div>
  <div class="field" style="margin:0;flex:1;min-width:160px">
    <label>Notas (opcional)</label>
    <input id="te-notes" placeholder="Ej: instalación rack, configuración...">
  </div>
  <button class="timer-btn-start" onclick="startTimer()">▶ Iniciar jornada</button>
</div>"""

    time_tab_html = f"""{timer_start_html}
<div class="time-summary-grid">{time_summary_html or '<p class="muted" style="grid-column:1/-1;text-align:center;padding:20px">Sin registros de tiempo todavía</p>'}</div>
<div class="card">
  <h3 style="margin-bottom:12px">Registro de jornadas</h3>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Inicio</th><th>Técnico</th><th>Tipo</th><th>Duración</th>
    <th class="col-m-hide">Notas</th><th></th>
  </tr></thead><tbody>{te_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:16px'>Sin registros</td></tr>"}</tbody></table></div>
</div>"""

    # ── build extras tab HTML ──
    extra_rows = ""
    for ex in extras:
        extra_rows += (f'<tr>'
            f'<td>{_esc(ex["description"])}</td>'
            f'<td style="text-align:center">{ex["quantity"]}</td>'
            f'<td>{_esc(ex["unit"])}</td>'
            f'<td class="muted col-m-hide" style="font-size:.8rem">{_esc(ex.get("notes","") or "")}</td>'
            f'<td class="muted col-m-hide" style="font-size:.75rem">{_esc(ex.get("uname","") or "")}</td>'
            f'<td><button class="btn btn-danger btn-icon" onclick="delExtra({ex["id"]})">✕</button></td></tr>')

    eq_rows = ""
    for eq in equipment:
        eq_rows += (f'<tr>'
            f'<td>{_esc(eq.get("brand","") or "")}</td>'
            f'<td>{_esc(eq["model"])}</td>'
            f'<td class="muted col-m-hide" style="font-size:.8rem">{_esc(eq.get("serial_number","") or "")}</td>'
            f'<td style="text-align:center">{eq["quantity"]}</td>'
            f'<td class="muted col-m-hide" style="font-size:.8rem">{_esc(eq.get("notes","") or "")}</td>'
            f'<td><button class="btn btn-danger btn-icon" onclick="delEquipment({eq["id"]})">✕</button></td></tr>')

    extras_tab_html = f"""
<div class="card">
  <h3 style="margin-bottom:4px">Extras / Materiales fuera de scope</h3>
  <p class="muted" style="font-size:.8rem;margin-bottom:12px">Materiales o trabajos no incluidos en el alcance original</p>
  <div class="inline-add" id="extra-add">
    <div class="row">
      <div class="field"><label>Descripción</label><input id="ex-desc" placeholder="Ej: Cable UTP extra 15m"></div>
      <div class="field" style="flex:0 0 90px"><label>Cantidad</label><input type="number" id="ex-qty" value="1" min="0" step="0.01"></div>
      <div class="field" style="flex:0 0 80px"><label>Unidad</label><input id="ex-unit" value="ud"></div>
      <div class="field"><label>Notas</label><input id="ex-notes" placeholder="Motivo, detalle..."></div>
      <button class="btn btn-primary btn-sm" onclick="addExtra()">+ Añadir</button>
    </div>
  </div>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Descripción</th><th style="text-align:center">Cant.</th><th>Ud</th>
    <th class="col-m-hide">Notas</th><th class="col-m-hide">Técnico</th><th></th>
  </tr></thead><tbody>{extra_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:16px'>Sin extras registrados</td></tr>"}</tbody></table></div>
</div>

<div class="card">
  <h3 style="margin-bottom:4px">Equipos instalados</h3>
  <p class="muted" style="font-size:.8rem;margin-bottom:12px">Inventario de equipamiento instalado en el proyecto</p>
  <div class="inline-add">
    <div class="row">
      <div class="field" style="flex:0 0 120px"><label>Marca</label><input id="eq-brand" placeholder="Cisco"></div>
      <div class="field"><label>Modelo</label><input id="eq-model" placeholder="Catalyst 9200L"></div>
      <div class="field"><label>Nº Serie</label><input id="eq-serial" placeholder="FCW2144L0XY"></div>
      <div class="field" style="flex:0 0 80px"><label>Cantidad</label><input type="number" id="eq-qty" value="1" min="1"></div>
      <div class="field"><label>Notas</label><input id="eq-notes" placeholder="Rack 1 U3..."></div>
      <button class="btn btn-primary btn-sm" onclick="addEquipment()">+ Añadir</button>
    </div>
  </div>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Marca</th><th>Modelo</th><th class="col-m-hide">Nº Serie</th>
    <th style="text-align:center">Cant.</th><th class="col-m-hide">Notas</th><th></th>
  </tr></thead><tbody>{eq_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:16px'>Sin equipos registrados</td></tr>"}</tbody></table></div>
</div>"""

    # ── build comments tab HTML ──
    comment_items = ""
    for cm in comments:
        initials_c = "".join(w[0].upper() for w in cm['uname'].split()[:2])
        col_c = _pcolor(cm['user_id'])
        is_own = cm['user_id'] == user['id']
        cm_id = cm['id']
        del_cm = ""
        if is_own or user.get('role') == 'admin':
            del_cm = f' <button style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:.8rem" onclick="delComment({cm_id})">✕</button>'
        own_cls = " comment-own" if is_own else ""
        comment_items += (f'<li class="{own_cls}">'
            f'<div class="avatar" style="background:{col_c};flex-shrink:0">{_esc(initials_c)}</div>'
            f'<div class="comment-bubble">'
            f'<div class="comment-meta"><span class="fw7">{_esc(cm["uname"])}</span>'
            f' &middot; {_esc(cm["created_at"][:16])}{del_cm}</div>'
            f'<div class="comment-body">{_esc(cm["body"])}</div>'
            f'</div></li>')

    comments_tab_html = f"""
{"<ul class='comment-thread'>"+comment_items+"</ul>" if comment_items else "<p class='muted' style='text-align:center;padding:24px'>Sin comentarios todavía — sé el primero</p>"}
<div class="comment-add card">
  <label style="margin-bottom:6px;display:block">Añadir comentario</label>
  <textarea id="cm-body" rows="3" placeholder="Descripción del trabajo, incidencia, novedad..."></textarea>
  <button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="addComment()">Enviar</button>
</div>"""

    # ── active timer banner ──
    if active_timer:
        started_iso = (active_timer.get('started_at') or '').replace(' ', 'T')
        timer_banner_html = f"""
<div class="timer-banner">
  <div style="flex:1">
    <div class="timer-lbl">⏱ Jornada activa</div>
    <div class="timer-time" id="timer-elapsed">—</div>
  </div>
  <div>
    <div style="font-size:.74rem;opacity:.75;margin-bottom:6px">Inicio: {_esc((active_timer.get('started_at') or '')[:16])}</div>
    <button class="timer-btn-stop" onclick="stopTimer()">⏹ Parar jornada</button>
  </div>
</div>
<script>
(function(){{
  var start=new Date("{started_iso}");
  function tick(){{
    var el=document.getElementById('timer-elapsed');
    if(!el) return;
    var diff=Math.floor((Date.now()-start.getTime())/1000);
    var h=Math.floor(diff/3600),m=Math.floor((diff%3600)/60),s=diff%60;
    el.textContent=(h>0?h+'h ':'')+String(m).padStart(2,'0')+'m '+String(s).padStart(2,'0')+'s';
  }}
  tick(); setInterval(tick,1000);
}})();
</script>"""
    else:
        timer_banner_html = ""

    safe_proj = {k: v for k, v in p.items() if isinstance(v, (str, int, float, type(None)))}
    content = f"""
<div style="margin-bottom:8px"><a href="{BP}/projects" class="muted" style="font-size:.85rem">← Proyectos</a></div>
<div class="toolbar">
  <div>
    <h1 style="margin-bottom:4px">{_esc(p["name"])}</h1>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:4px">
      {_wt_badge(p.get('work_type') or 'proyecto')}
      <span class="muted" style="font-size:.88rem">{_esc(p["client"])}</span>
      {('&nbsp;<span class="chip">#'+_esc(p["reference"])+'</span>') if p.get("reference") else ""}
      &nbsp;{_badge(p["status"])}
      &nbsp;<span style="color:{pcolor};font-weight:600;font-size:.8rem">▲ {plabel}</span>
    </div>
    {('<div class="avatar-row" style="margin-top:8px">'+member_avatars+'</div>') if member_avatars else ""}
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <a href="{BP}/projects/{pid}/report" target="_blank" class="btn btn-ghost btn-sm">🖨 Informe</a>
    <button class="btn btn-ghost btn-sm" onclick="editProject({json.dumps(safe_proj)})">✏️ Editar</button>
  </div>
</div>
{desc_html}
{timer_banner_html}

<div class="tabs" style="overflow-x:auto">
  <button class="tab-btn active" onclick="showTab('tareas',this)">Tareas ({len(tasks)})</button>
  <button class="tab-btn" onclick="showTab('tiempo',this)">⏱ Tiempo</button>
  <button class="tab-btn" onclick="showTab('seguimiento',this)">💬 Seguimiento ({len(comments)})</button>
  <button class="tab-btn" onclick="showTab('extras',this)">🔌 Extras ({len(extras)+len(equipment)})</button>
  <button class="tab-btn" onclick="showTab('materiales',this)">Materiales ({len(assignments)})</button>
  <button class="tab-btn" onclick="showTab('diario',this)">Diario ({len(logs)})</button>
  <button class="tab-btn" onclick="showTab('equipo',this)">👥 Equipo ({len(members)})</button>
  <button class="tab-btn" onclick="showTab('archivos',this)">📁 Archivos ({len(pfiles)})</button>
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

<!-- TAB EQUIPO -->
<div id="tab-equipo" class="tab-pane">
<div class="toolbar">
  <h2>Equipo del proyecto</h2>
  <button class="btn btn-primary btn-sm" onclick="openAddMember()">+ Añadir persona</button>
</div>
<div class="card">
  <div class="tbl-wrap"><table><thead><tr>
    <th style="width:36px"></th><th>Técnico</th>
    <th class="col-m-hide">Período</th><th class="col-m-hide">Notas</th><th></th>
  </tr></thead><tbody>
    {member_rows or "<tr><td colspan='5' class='muted' style='text-align:center;padding:20px'>Sin personas asignadas al proyecto</td></tr>"}
  </tbody></table></div>
</div>
<p class="muted" style="font-size:.82rem;padding:0 2px">
  Las personas aquí asignadas aparecen en el calendario de movimientos de personal.
</p>
</div>

<!-- TAB TIEMPO -->
<div id="tab-tiempo" class="tab-pane">
{time_tab_html}
</div>

<!-- TAB SEGUIMIENTO -->
<div id="tab-seguimiento" class="tab-pane">
{comments_tab_html}
</div>

<!-- TAB EXTRAS -->
<div id="tab-extras" class="tab-pane">
{extras_tab_html}
</div>

<!-- TAB INFO -->
<div id="tab-info" class="tab-pane">
<div class="card">
  <table><tbody>{info_rows or "<tr><td class='muted'>Sin datos adicionales</td></tr>"}</tbody></table>
</div>
</div>

<!-- MODAL añadir miembro -->
<div class="modal-bg" id="member-modal">
<div class="modal" style="max-width:460px">
  <h2>Añadir al equipo</h2>
  <div class="form-row single">
    <div><label>Técnico</label><select id="mb-user">{user_opts}</select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha inicio</label><input type="date" id="mb-start"></div>
    <div><label>Fecha fin</label><input type="date" id="mb-end"></div>
  </div>
  <div class="form-row single">
    <div><label>Notas</label><input id="mb-notes" placeholder="Rol en el proyecto, turno..."></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeMemberModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="doAddMember()">Añadir</button>
  </div>
</div></div>

<!-- TAB ARCHIVOS -->
<div id="tab-archivos" class="tab-pane">
<div class="toolbar"><h2>Archivos del proyecto</h2></div>

<div class="upload-area" id="upload-area" onclick="document.getElementById('file-input').click()"
  ondragover="event.preventDefault();this.classList.add('drag-over')"
  ondragleave="this.classList.remove('drag-over')"
  ondrop="event.preventDefault();this.classList.remove('drag-over');handleFiles(event.dataTransfer.files)">
  <input type="file" id="file-input" multiple onchange="handleFiles(this.files)">
  <div style="font-size:1.8rem;margin-bottom:6px">📎</div>
  <div class="fw7" style="font-size:.9rem">Arrastra archivos aquí o haz clic para seleccionar</div>
  <div class="muted" style="font-size:.78rem;margin-top:4px">Imágenes, PDFs, documentos — sin límite de tipo</div>
</div>
<div id="upload-status"></div>

<div class="file-grid" id="file-grid">
{_build_file_grid(pfiles, pid)}
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
  <div class="form-row cols3">
    <div><label>Tipo de trabajo</label><select id="f-wtype">
      <option value="proyecto">📋 Proyecto</option>
      <option value="instalacion">🔧 Instalación</option>
      <option value="averia">⚡ Avería</option>
      <option value="mantenimiento">🔨 Mantenimiento</option>
      <option value="inspeccion">🔍 Inspección</option>
    </select></div>
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
  document.getElementById('f-wtype').value=p.work_type||'proyecto';
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
      work_type:document.getElementById('f-wtype').value,
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

// ── members ──
function openAddMember(){{document.getElementById('member-modal').classList.add('open');}}
function closeMemberModal(){{document.getElementById('member-modal').classList.remove('open');}}
document.getElementById('member-modal').onclick=function(e){{if(e.target===this)closeMemberModal();}};
function doAddMember(){{
  var d={{user_id:document.getElementById('mb-user').value,
    start_date:document.getElementById('mb-start').value,
    end_date:document.getElementById('mb-end').value,
    notes:document.getElementById('mb-notes').value}};
  fetch(bp+'/api/projects/'+pid+'/members',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function removeMember(id){{
  if(!confirm('¿Quitar del equipo?')) return;
  fetch(bp+'/api/project_members/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}

// ── files ──
function handleFiles(files){{
  if(!files||!files.length) return;
  var status=document.getElementById('upload-status');
  status.innerHTML='<div class="alert alert-amber">Subiendo '+files.length+' archivo(s)...</div>';
  var promises=Array.from(files).map(function(file){{
    var fd=new FormData();
    fd.append('file',file);
    return fetch(bp+'/api/projects/'+pid+'/files',{{method:'POST',body:fd}})
      .then(function(r){{return r.json();}});
  }});
  Promise.all(promises).then(function(){{
    location.reload();
  }}).catch(function(e){{
    status.innerHTML='<div class="alert alert-red">Error al subir: '+e.message+'</div>';
  }});
}}
function delFile(id){{
  if(!confirm('¿Eliminar este archivo?')) return;
  fetch(bp+'/api/project_files/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}

// ── timer ──
function startTimer(){{
  var type=document.getElementById('te-type')?document.getElementById('te-type').value:'work';
  var notes=document.getElementById('te-notes')?document.getElementById('te-notes').value:'';
  fetch(bp+'/api/projects/'+pid+'/time/start',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{entry_type:type,notes:notes}})}})
    .then(function(r){{
      if(r.ok) location.reload();
      else r.json().then(function(j){{alert(j.error||'Error al iniciar jornada');}});
    }});
}}
function stopTimer(){{
  fetch(bp+'/api/projects/'+pid+'/time/stop',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:'{{}}'}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function delTimeEntry(id){{
  if(!confirm('¿Eliminar este registro de tiempo?')) return;
  fetch(bp+'/api/time_entries/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}

// ── extras ──
function addExtra(){{
  var desc=document.getElementById('ex-desc').value.trim();
  if(!desc){{alert('Escribe una descripción');return;}}
  fetch(bp+'/api/projects/'+pid+'/extras',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{description:desc,
      quantity:parseFloat(document.getElementById('ex-qty').value)||1,
      unit:document.getElementById('ex-unit').value||'ud',
      notes:document.getElementById('ex-notes').value}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function delExtra(id){{
  if(!confirm('¿Eliminar este extra?')) return;
  fetch(bp+'/api/wo_extras/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}

// ── equipment ──
function addEquipment(){{
  var model=document.getElementById('eq-model').value.trim();
  if(!model){{alert('Escribe el modelo del equipo');return;}}
  fetch(bp+'/api/projects/'+pid+'/equipment',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{brand:document.getElementById('eq-brand').value,
      model:model,serial_number:document.getElementById('eq-serial').value,
      quantity:parseInt(document.getElementById('eq-qty').value)||1,
      notes:document.getElementById('eq-notes').value}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function delEquipment(id){{
  if(!confirm('¿Eliminar este equipo?')) return;
  fetch(bp+'/api/equipment_items/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}

// ── comments ──
function addComment(){{
  var body=document.getElementById('cm-body').value.trim();
  if(!body) return;
  fetch(bp+'/api/projects/'+pid+'/comments',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{body:body}})}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
function delComment(id){{
  if(!confirm('¿Eliminar comentario?')) return;
  fetch(bp+'/api/wo_comments/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
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
            mname_safe = _esc(ki["mat_name"]).replace("'", "&#39;")
            item_rows += (f'<tr><td><span class="chip">{_esc(ki["mat_code"])}</span></td>'
                f'<td>{_esc(ki["mat_name"])}</td>'
                f'<td style="text-align:center;font-weight:700">{ki["qty"]}</td>'
                f'<td class="muted">{_esc(ki["mat_unit"])}</td>'
                f'<td class="muted" style="font-size:.75rem">{_esc(ki["notes"] or "")}</td>'
                f'<td><button class="btn btn-danger btn-icon" '
                f"onclick=\"returnFromKit({ki['id']},{ki['qty']},'{mname_safe}',{t['id']})\">↩</button></td></tr>")

        empty_msg = '<p class="muted" style="padding:12px 0;font-size:.85rem">Kit vacío</p>'
        kit_table = (f'<div class="tbl-wrap"><table><thead><tr><th>Cód</th><th>Material</th>'
            f'<th style="text-align:center">Qty</th><th>Ud</th><th>Notas</th><th></th></tr></thead>'
            f'<tbody>{item_rows}</tbody></table></div>') if kit_items else empty_msg

        tid = t['id']
        dname_safe = _esc(t['display_name']).replace("'", "&#39;")
        cards += f"""<div class="kit-card">
  <h3>👤 {_esc(t['display_name'])} <span class="role-badge">{_esc(role_lbl)}</span>
    <span class="muted" style="font-size:.75rem;font-weight:400;margin-left:auto">{t['items']} items · {t['total_qty']} uds</span>
  </h3>
  {kit_table}
  <div style="margin-top:10px">
    <button class="btn btn-primary btn-sm" onclick="openAddKit({tid},'{dname_safe}')">+ Añadir al kit</button>
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


# ── project report ────────────────────────────────────────────────────────────
def _project_report(user, pid):
    p = r2d(q1("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to WHERE p.id=?""", (pid,)))
    if not p: return None
    tasks = rs(q("SELECT * FROM tasks WHERE project_id=? ORDER BY status,priority DESC", (pid,)))
    assignments = rs(q("""SELECT a.*,m.name mat_name,m.code mat_code,m.unit mat_unit
        FROM assignments a JOIN materials m ON m.id=a.material_id
        WHERE a.project_id=? ORDER BY m.name""", (pid,)))
    logs = rs(q("""SELECT l.*,u.display_name uname
        FROM project_logs l JOIN users u ON u.id=l.user_id
        WHERE l.project_id=? ORDER BY l.created_at""", (pid,)))
    time_summary_r = rs(q("""SELECT u.display_name uname,
        COUNT(DISTINCT date(te.started_at)) days,
        COALESCE(SUM(CASE WHEN te.ended_at IS NOT NULL
            THEN (julianday(te.ended_at)-julianday(te.started_at))*86400 ELSE 0 END),0) total_secs
        FROM time_entries te JOIN users u ON u.id=te.user_id
        WHERE te.project_id=? AND te.ended_at IS NOT NULL
        GROUP BY u.id ORDER BY total_secs DESC""", (pid,)))
    extras_r = rs(q("""SELECT we.*,u.display_name uname
        FROM wo_extras we LEFT JOIN users u ON u.id=we.added_by
        WHERE we.project_id=? ORDER BY we.created_at""", (pid,)))
    equipment_r = rs(q("""SELECT ei.*,u.display_name uname
        FROM equipment_items ei LEFT JOIN users u ON u.id=ei.added_by
        WHERE ei.project_id=? ORDER BY ei.created_at""", (pid,)))
    hours_total = q1("SELECT COALESCE(SUM(hours),0) FROM project_logs WHERE project_id=?", (pid,))
    h_logged = hours_total[0] if hours_total else 0
    h_est = p.get("estimated_hours") or 0
    task_done = sum(1 for t in tasks if t['status']=='done')
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    st_label = STATUS_LABEL.get(p['status'], p['status'])
    pri_label = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(p['priority'],p['priority'])

    t_rows = ""
    for s, slbl in [("blocked","🔴 Bloqueado"),("in_progress","🔵 En curso"),
                    ("pending","⚪ Pendiente"),("done","✅ Hecho")]:
        for t in [x for x in tasks if x['status']==s]:
            pril = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(t['priority'],'')
            desc_part = f'<br><small style="color:#64748b">{_esc(t["description"])}</small>' if t.get("description") else ""
            t_rows += (f'<tr><td>{_esc(t["title"])}{desc_part}</td>'
                f'<td>{slbl}</td><td>{pril}</td>'
                f'<td>{_esc((t["due_date"] or "—")[:10])}</td></tr>')

    m_rows = "".join(
        f'<tr><td><code>{_esc(a["mat_code"])}</code> {_esc(a["mat_name"])}</td>'
        f'<td style="text-align:center">{a["qty_requested"]}</td>'
        f'<td style="text-align:center">{a["qty_assigned"]}</td>'
        f'<td style="text-align:center">{a["qty_consumed"]}</td>'
        f'<td style="text-align:center">{a["qty_returned"]}</td>'
        f'<td>{STATUS_LABEL.get(a["status"],a["status"])}</td>'
        f'<td>{_esc(a["mat_unit"])}</td></tr>' for a in assignments)

    log_html = ""
    for l in logs:
        h_str = f' · {l["hours"]}h' if l["hours"] else ""
        log_html += (f'<div style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #e2e8f0">'
            f'<div style="font-size:.78rem;color:#64748b;margin-bottom:4px">'
            f'<strong>{_esc(l["uname"])}</strong> — {_esc(l["created_at"][:16])}{_esc(h_str)}</div>'
            f'<div style="line-height:1.55;white-space:pre-wrap;font-size:.9rem">{_esc(l["body"])}</div></div>')

    wt_info = WORK_TYPES.get(p.get('work_type') or 'proyecto', WORK_TYPES['proyecto'])
    total_time_secs = sum(ts['total_secs'] for ts in time_summary_r)
    meta = [("Tipo de trabajo", f'{wt_info["icon"]} {wt_info["name"]}'),
            ("Cliente",p.get("client","")),("Referencia",p.get("reference","")),
            ("Dirección",p.get("address","")),("Técnico",p.get("tech","")),
            ("Contacto obra",p.get("contact_name","")),("Teléfono",p.get("contact_phone","")),
            ("Inicio",(p.get("start_date") or "")[:10]),("Límite",(p.get("due_date") or "")[:10]),
            ("Estado",st_label),("Prioridad",pri_label),
            ("Horas estimadas",f'{h_est}h' if h_est else ""),
            ("Tiempo total registrado", _fmt_duration(total_time_secs) if total_time_secs else "—"),
            ("Horas diario",f'{h_logged}h'),
            ("Tareas completadas",f'{task_done}/{len(tasks)}')]
    meta_html = "".join(
        f'<div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid #f0f4f8;font-size:.88rem">'
        f'<span style="min-width:160px;color:#64748b;font-weight:600">{_esc(k)}</span>'
        f'<span>{_esc(str(v))}</span></div>'
        for k,v in meta if v)

    tasks_section = ('<p style="color:#64748b">Sin tareas registradas</p>' if not tasks else
        f'<div class="tbl-wrap"><table style="font-size:.87rem"><thead><tr>'
        f'<th>Tarea</th><th>Estado</th><th>Prioridad</th><th>Vencimiento</th>'
        f'</tr></thead><tbody>{t_rows}</tbody></table></div>')
    mats_section = ('<p style="color:#64748b">Sin materiales asignados</p>' if not assignments else
        f'<div class="tbl-wrap"><table style="font-size:.87rem"><thead><tr>'
        f'<th>Material</th><th style="text-align:center">Solic.</th>'
        f'<th style="text-align:center">Asgn.</th><th style="text-align:center">Cons.</th>'
        f'<th style="text-align:center">Dev.</th><th>Estado</th><th>Ud</th>'
        f'</tr></thead><tbody>{m_rows}</tbody></table></div>')
    logs_section = ('<p style="color:#64748b">Sin entradas en el diario</p>' if not logs else
        f'<div>{log_html}</div>')

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe — {_esc(p["name"])}</title>
<style>
{_css()}
body{{display:block;background:#f0f4f8}}
.rpage{{max-width:860px;margin:0 auto;padding:32px;background:#fff;box-shadow:0 0 40px rgba(0,0,0,.08)}}
.rhead{{display:flex;justify-content:space-between;align-items:flex-start;
  margin-bottom:28px;padding-bottom:20px;border-bottom:3px solid #0f1f35}}
.rhead h1{{font-size:1.4rem;margin-bottom:4px}}
.rlogo{{font-weight:800;font-size:1rem;color:#0f1f35;text-align:right}}
.rlogo span{{display:block;font-size:.58rem;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-top:2px}}
.rsec{{margin-bottom:26px}}
.rsec h2{{font-size:.95rem;font-weight:700;color:#1a2536;margin-bottom:10px;
  padding-bottom:6px;border-bottom:1.5px solid #dce4ee;text-transform:uppercase;letter-spacing:.5px}}
@media print{{
  body{{background:#fff!important}}
  .no-print{{display:none!important}}
  .rpage{{padding:0;max-width:100%;box-shadow:none}}
  @page{{margin:1.5cm}}
}}
</style>
</head>
<body>
<div class="no-print" style="background:#0f1f35;padding:10px 20px;display:flex;align-items:center;justify-content:space-between">
  <a href="{BP}/projects/{pid}" style="color:#4db6ac;font-size:.88rem">← Volver al proyecto</a>
  <button onclick="window.print()" style="background:#4db6ac;color:#fff;border:none;
    padding:6px 14px;border-radius:6px;cursor:pointer;font-size:.83rem;font-weight:600">
    🖨 Imprimir / PDF</button>
</div>
<div class="rpage">
  <div class="rhead">
    <div>
      <h1>{_esc(p["name"])}</h1>
      <div style="color:#64748b;font-size:.9rem">{_esc(p.get("description",""))}</div>
    </div>
    <div class="rlogo">NuvoDesk<span>Nuvolink · Telecoms</span>
      <div style="font-size:.7rem;color:#94a3b8;margin-top:5px">Generado: {now_str}</div>
    </div>
  </div>
  <div class="rsec">
    <h2>Información del proyecto</h2>
    {meta_html}
  </div>
  <div class="rsec">
    <h2>Tareas ({len(tasks)})</h2>
    {tasks_section}
  </div>
  <div class="rsec">
    <h2>Materiales ({len(assignments)})</h2>
    {mats_section}
  </div>
  <div class="rsec">
    <h2>Diario de obra ({len(logs)} entradas · {h_logged}h)</h2>
    {logs_section}
  </div>
  {'<div class="rsec"><h2>Resumen de tiempos por técnico</h2><table style="font-size:.87rem;width:100%;border-collapse:collapse"><thead><tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Técnico</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Días</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Tiempo total</th></tr></thead><tbody>' + "".join(f"<tr><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(ts['uname'])}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8'>{ts['days']}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8;font-weight:700'>{_fmt_duration(ts['total_secs'])}</td></tr>" for ts in time_summary_r) + '</tbody></table></div>' if time_summary_r else ''}
  {'<div class="rsec"><h2>Extras / Materiales fuera de scope (' + str(len(extras_r)) + ')</h2><table style="font-size:.87rem;width:100%;border-collapse:collapse"><thead><tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Descripción</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Cant.</th><th style="padding:6px 10px;border-bottom:2px solid #dce4ee">Ud</th><th style="padding:6px 10px;border-bottom:2px solid #dce4ee">Notas</th></tr></thead><tbody>' + "".join(f"<tr><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(ex['description'])}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8'>{ex['quantity']}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(ex['unit'])}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8;color:#64748b'>{_esc(ex.get('notes','') or '')}</td></tr>" for ex in extras_r) + '</tbody></table></div>' if extras_r else ''}
  {'<div class="rsec"><h2>Equipos instalados (' + str(len(equipment_r)) + ')</h2><table style="font-size:.87rem;width:100%;border-collapse:collapse"><thead><tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Marca</th><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Modelo</th><th style="padding:6px 10px;border-bottom:2px solid #dce4ee">Nº Serie</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Cant.</th></tr></thead><tbody>' + "".join(f"<tr><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(eq.get('brand','') or '')}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(eq['model'])}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8;font-family:monospace;font-size:.82rem'>{_esc(eq.get('serial_number','') or '')}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8'>{eq['quantity']}</td></tr>" for eq in equipment_r) + '</tbody></table></div>' if equipment_r else ''}
</div>
</body></html>"""

# ── calendar ─────────────────────────────────────────────────────────────────
def _calendar_page(user, year, month):
    today = _date.today()
    # clamp month
    if month < 1: year -= 1; month = 12
    if month > 12: year += 1; month = 1
    first = _date(year, month, 1)
    _, days_in_month = _cal.monthrange(year, month)
    last = _date(year, month, days_in_month)

    # prev/next
    prev_y, prev_m = (year, month-1) if month > 1 else (year-1, 12)
    next_y, next_m = (year, month+1) if month < 12 else (year+1, 1)

    # load assignments: project_members with date ranges
    raw_members = rs(q("""
        SELECT pm.id, pm.project_id, pm.user_id, pm.start_date, pm.end_date,
               u.display_name uname, p.name pname, p.status pstatus
        FROM project_members pm
        JOIN users u ON u.id=pm.user_id
        JOIN projects p ON p.id=pm.project_id
        WHERE p.status NOT IN ('cancelled')
    """))

    # expand each member into days within this month
    # day_map: day_str → list of {uid, uname, pid, pname}
    day_map = {str(first + timedelta(days=i)): [] for i in range(days_in_month)}

    for mb in raw_members:
        s_str = mb['start_date'] or str(first)
        e_str = mb['end_date'] or str(last)
        try: s = _date.fromisoformat(s_str)
        except: s = first
        try: e = _date.fromisoformat(e_str)
        except: e = last
        s = max(s, first)
        e = min(e, last)
        if s > e: continue
        cur = s
        while cur <= e:
            k = str(cur)
            if k in day_map:
                day_map[k].append({"uid": mb['user_id'], "uname": mb['uname'],
                                   "pid": mb['project_id'], "pname": mb['pname']})
            cur += timedelta(days=1)

    # ── all active users ──
    all_users = rs(q("SELECT id,display_name FROM users WHERE active=1 AND role!='backoffice' ORDER BY display_name"))
    user_opts = "".join(f'<option value="{u["id"]}">{_esc(u["display_name"])}</option>' for u in all_users)

    # ── active projects ──
    all_projs = rs(q("SELECT id,name FROM projects WHERE status IN ('active','paused') ORDER BY name"))
    proj_opts = "".join(f'<option value="{p["id"]}">{_esc(p["name"])}</option>' for p in all_projs)

    # ── calendar grid ──
    dow_labels = "".join(f'<div class="cal-dow">{d}</div>' for d in ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"])

    # pad start
    first_dow = first.weekday()  # 0=Mon
    cells = ['<div class="cal-day other-month"></div>'] * first_dow

    for i in range(days_in_month):
        day = first + timedelta(days=i)
        day_str = str(day)
        is_today = (day == today)
        today_cls = " today" if is_today else ""
        chips = ""
        seen = set()
        for ent in day_map[day_str]:
            k = (ent['uid'], ent['pid'])
            if k in seen: continue
            seen.add(k)
            col = _pcolor(ent['pid'])
            initials = "".join(w[0].upper() for w in ent['uname'].split()[:2])
            chips += (f'<span class="cal-chip" style="background:{col}" '
                      f'title="{_esc(ent["uname"])} → {_esc(ent["pname"])}">'
                      f'{_esc(initials)} {_esc(ent["pname"][:12])}</span>')
        cells.append(f'<a href="{BP}/calendar/{day_str}" class="cal-day{today_cls}"><div class="cal-day-num">{day.day}</div>{chips}</a>')

    # pad end to complete the last week
    while len(cells) % 7 != 0:
        cells.append('<div class="cal-day other-month"></div>')

    grid_html = dow_labels + "".join(cells)

    # ── matrix view: technicians × days ──
    # rows = technicians, cols = each day of month
    # Only show technicians with at least one assignment this month
    tech_ids = sorted({ent['uid'] for dl in day_map.values() for ent in dl})
    tech_names = {mb['user_id']: mb['uname'] for mb in raw_members}
    for u in all_users:
        tech_names[u['id']] = u['display_name']

    matrix_html = ""
    if tech_ids:
        day_headers = "".join(
            f'<th class={"today-col" if str(first+timedelta(days=i))==str(today) else ""}>{(first+timedelta(days=i)).day}</th>'
            for i in range(days_in_month))
        matrix_html = f'<div class="matrix-wrap"><table class="matrix"><thead><tr><th class="tech-col">Técnico</th>{day_headers}</tr></thead><tbody>'
        for uid in tech_ids:
            uname = tech_names.get(uid, str(uid))
            initials = "".join(w[0].upper() for w in uname.split()[:2])
            col = _pcolor(uid)
            row = f'<td><div class="avatar avatar-sm" style="background:{col};margin:auto">{_esc(initials)}</div> <span style="font-size:.75rem">{_esc(uname)}</span></td>'
            for i in range(days_in_month):
                day_str = str(first + timedelta(days=i))
                is_tc = (first + timedelta(days=i) == today)
                entries = [e for e in day_map[day_str] if e['uid'] == uid]
                if entries:
                    e0 = entries[0]
                    col_p = _pcolor(e0['pid'])
                    cell = f'<span class="matrix-cell" style="background:{col_p}" title="{_esc(e0["pname"])}">{_esc(e0["pname"][:6])}</span>'
                else:
                    cell = ""
                td_cls = ' class="today-col"' if is_tc else ""
                row += f'<td{td_cls}>{cell}</td>'
            matrix_html += f'<tr>{row}</tr>'
        matrix_html += '</tbody></table></div>'
    else:
        matrix_html = '<p class="muted" style="text-align:center;padding:24px">Sin asignaciones este mes</p>'

    month_names = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                   "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    month_label = f"{month_names[month-1]} {year}"

    content = f"""
<div class="toolbar">
  <h1>🗓 Calendario de personal</h1>
  <button class="btn btn-primary" onclick="document.getElementById('assign-modal').classList.add('open')">+ Asignación</button>
</div>

<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px">
  <div style="display:flex;align-items:center;gap:10px">
    <a href="{BP}/calendar?year={prev_y}&month={prev_m}" class="btn btn-ghost btn-sm">← {month_names[prev_m-1]}</a>
    <h2 style="margin:0;min-width:160px;text-align:center">{month_label}</h2>
    <a href="{BP}/calendar?year={next_y}&month={next_m}" class="btn btn-ghost btn-sm">{month_names[next_m-1]} →</a>
  </div>
  <a href="{BP}/calendar?year={today.year}&month={today.month}" class="btn btn-ghost btn-sm">Hoy</a>
</div>

<div class="card" style="padding:16px">
  <h2 style="margin-bottom:12px">Vista mensual</h2>
  <div class="cal-grid">{grid_html}</div>
</div>

<div class="card" style="padding:16px">
  <h2 style="margin-bottom:12px">Carga por técnico — {month_label}</h2>
  {matrix_html}
</div>

<!-- MODAL nueva asignación -->
<div class="modal-bg" id="assign-modal">
<div class="modal" style="max-width:480px">
  <h2>Nueva asignación de personal</h2>
  <div class="form-row single">
    <div><label>Técnico</label><select id="ca-user">{user_opts}</select></div>
  </div>
  <div class="form-row single">
    <div><label>Proyecto</label><select id="ca-proj">{proj_opts}</select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha inicio</label><input type="date" id="ca-start" value="{first}"></div>
    <div><label>Fecha fin</label><input type="date" id="ca-end" value="{last}"></div>
  </div>
  <div class="form-row single">
    <div><label>Notas</label><input id="ca-notes" placeholder="Turno, rol específico..."></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('assign-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doCreateAssign()">Guardar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
document.getElementById('assign-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function doCreateAssign(){{
  var pid=document.getElementById('ca-proj').value;
  var d={{user_id:document.getElementById('ca-user').value,
    start_date:document.getElementById('ca-start').value,
    end_date:document.getElementById('ca-end').value,
    notes:document.getElementById('ca-notes').value}};
  fetch(bp+'/api/projects/'+pid+'/members',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
</script>"""
    return _shell("calendar", user, content)

# ── calendar day detail ────────────────────────────────────────────────────────
def _calendar_day(user, day_str):
    try:
        day = _date.fromisoformat(day_str)
    except ValueError:
        return None

    today = _date.today()
    prev_day = str(day - timedelta(days=1))
    next_day = str(day + timedelta(days=1))

    month_names = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                   "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    dow_names   = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    day_label   = f"{dow_names[day.weekday()]} {day.day} de {month_names[day.month-1]} {day.year}"

    # load slots for this day
    slots = rs(q("""SELECT ss.*,u.display_name uname,p.name pname
        FROM schedule_slots ss
        JOIN users u ON u.id=ss.user_id
        JOIN projects p ON p.id=ss.project_id
        WHERE ss.slot_date=?
        ORDER BY ss.hour_start, u.display_name""", (day_str,)))

    # all active technicians (columns)
    techs = rs(q("SELECT id,display_name FROM users WHERE active=1 AND role IN ('admin','technician') ORDER BY display_name"))
    # active projects for modal
    projs = rs(q("SELECT id,name FROM projects WHERE status IN ('active','paused') ORDER BY name"))

    tech_opts = "".join(f'<option value="{t["id"]}">{_esc(t["display_name"])}</option>' for t in techs)
    proj_opts = "".join(f'<option value="{p["id"]}">{_esc(p["name"])}</option>' for p in projs)
    hour_opts_start = "".join(f'<option value="{h}">{"0"+str(h) if h<10 else h}:00</option>' for h in range(6,20))
    hour_opts_end   = "".join(f'<option value="{h}" {"selected" if h==9 else ""}>{"0"+str(h) if h<10 else h}:00</option>' for h in range(7,21))

    # build matrix: hours 6..20 × techs
    now_hour = datetime.now().hour if day == today else -1
    tech_ids = [t['id'] for t in techs]

    # slot lookup: (tech_id, hour) → slot
    slot_map = {}
    for s in slots:
        for h in range(s['hour_start'], s['hour_end']):
            key = (s['user_id'], h)
            if key not in slot_map:
                slot_map[key] = s

    # Generate matrix HTML
    # Header row
    th_techs = "".join(
        f'<th><div class="avatar avatar-sm" style="background:{_pcolor(t["id"])};margin:0 auto 3px">'
        f'{"".join(w[0].upper() for w in t["display_name"].split()[:2])}</div>'
        f'<div style="font-size:.65rem">{_esc(t["display_name"].split()[0])}</div></th>'
        for t in techs)

    rows_html = ""
    for h in range(6, 21):
        now_cls = ' class="now-row"' if h == now_hour else ''
        cells = ""
        for tid in tech_ids:
            s = slot_map.get((tid, h))
            if s:
                col = _pcolor(s['project_id'])
                pshort = _esc(s['pname'][:14])
                if s['hour_start'] == h:
                    end_str = f'{s["hour_end"]:02d}:00'
                    cells += (f'<td{now_cls}><div class="slot-block" style="background:{col}">'
                              f'{pshort}'
                              f'<br><span style="opacity:.8;font-size:.6rem">→ {end_str}</span>'
                              f'<button class="slot-del" onclick="delSlot({s["id"]})">✕</button>'
                              f'</div></td>')
                else:
                    cells += (f'<td{now_cls}><div class="slot-block" style="background:{col};opacity:.7">'
                              f'<span style="opacity:.6">·</span></div></td>')
            else:
                cells += f'<td{now_cls}></td>'
        hstr = f'{"0" if h<10 else ""}{h}:00'
        rows_html += f'<tr><td class="hour-label">{hstr}</td>{cells}</tr>'

    # slots list (sidebar summary)
    slot_list = ""
    for s in slots:
        col = _pcolor(s['project_id'])
        initials = "".join(w[0].upper() for w in s['uname'].split()[:2])
        slot_list += (
            f'<div style="display:flex;align-items:center;gap:8px;padding:8px 0;'
            f'border-bottom:1px solid var(--border)">'
            f'<div class="avatar" style="background:{col}">{_esc(initials)}</div>'
            f'<div style="flex:1">'
            f'<div class="fw7" style="font-size:.85rem">{_esc(s["uname"])}</div>'
            f'<div style="font-size:.75rem;color:var(--muted)">{s["hour_start"]:02d}:00 → {s["hour_end"]:02d}:00 · {_esc(s["pname"])}</div>'
            f'{("<div style=font-size:.72rem;color:var(--muted)>"+_esc(s["notes"])+"</div>") if s.get("notes") else ""}'
            f'</div>'
            f'<button class="btn btn-danger btn-icon" style="font-size:.7rem" onclick="delSlot({s["id"]})">✕</button>'
            f'</div>')

    if not slot_list:
        slot_list = '<p class="muted" style="padding:12px 0;font-size:.85rem;text-align:center">Sin franjas asignadas</p>'

    content = f"""
<div class="day-nav">
  <a href="{BP}/calendar/{prev_day}" class="btn btn-ghost btn-sm">← {prev_day}</a>
  <div style="flex:1;text-align:center">
    <h1 style="margin:0">{day_label}</h1>
    <a href="{BP}/calendar?year={day.year}&month={day.month}" class="muted" style="font-size:.8rem">
      ← Volver al mes
    </a>
  </div>
  <a href="{BP}/calendar/{next_day}" class="btn btn-ghost btn-sm">{next_day} →</a>
</div>

<div style="display:grid;grid-template-columns:1fr 280px;gap:18px;align-items:start">

<div class="card" style="padding:0;overflow:hidden">
  <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
    <h2 style="margin:0">Horario hora a hora</h2>
    <button class="btn btn-primary btn-sm" onclick="document.getElementById('slot-modal').classList.add('open')">+ Franja horaria</button>
  </div>
  <div style="overflow-x:auto">
  <table class="day-matrix">
    <thead><tr><th class="hour-col">Hora</th>{th_techs}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  </div>
</div>

<div>
  <div class="card">
    <h2>Resumen del día</h2>
    {slot_list}
    <div style="margin-top:12px">
      <button class="btn btn-primary btn-sm" style="width:100%" onclick="document.getElementById('slot-modal').classList.add('open')">+ Añadir franja</button>
    </div>
  </div>
</div>

</div>

<!-- MODAL nueva franja -->
<div class="modal-bg" id="slot-modal">
<div class="modal" style="max-width:460px">
  <h2>Nueva franja horaria</h2>
  <div class="form-row single"><div><label>Técnico</label><select id="sl-user">{tech_opts}</select></div></div>
  <div class="form-row single"><div><label>Proyecto</label><select id="sl-proj">{proj_opts}</select></div></div>
  <div class="form-row">
    <div><label>Hora inicio</label><select id="sl-start">{hour_opts_start}</select></div>
    <div><label>Hora fin</label><select id="sl-end">{hour_opts_end}</select></div>
  </div>
  <div class="form-row single"><div><label>Notas (opcional)</label>
    <input id="sl-notes" placeholder="Reunión, desplazamiento, tarea..."></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('slot-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doAddSlot()">Guardar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
var slotDate="{day_str}";
document.getElementById('slot-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function doAddSlot(){{
  var hs=parseInt(document.getElementById('sl-start').value);
  var he=parseInt(document.getElementById('sl-end').value);
  if(he<=hs){{alert('La hora fin debe ser posterior a la hora inicio');return;}}
  fetch(bp+'/api/schedule_slots',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{user_id:document.getElementById('sl-user').value,
      project_id:document.getElementById('sl-proj').value,
      slot_date:slotDate,hour_start:hs,hour_end:he,
      notes:document.getElementById('sl-notes').value}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function delSlot(id){{
  if(!confirm('¿Eliminar esta franja?')) return;
  fetch(bp+'/api/schedule_slots/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
// pre-select hour based on current time
(function(){{
  var now=new Date();
  var h=now.getHours();
  var sel=document.getElementById('sl-start');
  for(var i=0;i<sel.options.length;i++){{
    if(parseInt(sel.options[i].value)===h){{sel.selectedIndex=i;break;}}
  }}
  var sel2=document.getElementById('sl-end');
  for(var i=0;i<sel2.options.length;i++){{
    if(parseInt(sel2.options[i].value)===h+1){{sel2.selectedIndex=i;break;}}
  }}
}})();
</script>"""
    return _shell("calendar", user, content)

# ── workload view ────────────────────────────────────────────────────────────
def _workload_page(user, week_str=""):
    today = _date.today()
    if week_str:
        try:
            ref = _date.fromisoformat(week_str)
        except ValueError:
            ref = today
    else:
        ref = today
    # Monday of the selected week
    mon = ref - timedelta(days=ref.weekday())
    days = [mon + timedelta(days=i) for i in range(7)]
    prev_mon = str(mon - timedelta(days=7))
    next_mon = str(mon + timedelta(days=7))
    dow_names = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]

    techs = rs(q("SELECT id,display_name FROM users WHERE active=1 AND role IN ('technician','admin','backoffice') ORDER BY display_name"))
    if not techs:
        techs = rs(q("SELECT id,display_name FROM users WHERE active=1 ORDER BY display_name"))

    day_strs = [str(d) for d in days]
    entries = rs(q(f"""SELECT te.user_id, date(te.started_at) entry_date,
        p.id pid, p.name pname, p.work_type,
        SUM(CASE WHEN te.ended_at IS NOT NULL
            THEN (julianday(te.ended_at)-julianday(te.started_at))*3600 ELSE 0 END) total_h
        FROM time_entries te JOIN projects p ON p.id=te.project_id
        WHERE date(te.started_at) >= ? AND date(te.started_at) <= ?
        GROUP BY te.user_id, date(te.started_at), p.id
        ORDER BY te.user_id, entry_date""",
        (day_strs[0], day_strs[6])))

    by_user_day: dict = {}
    for e in entries:
        key = (e['user_id'], e['entry_date'])
        by_user_day.setdefault(key, []).append(e)

    # header row
    hd_html = '<div class="wl-name wl-hd" style="font-size:.7rem">Técnico</div>'
    for i, d in enumerate(days):
        is_today = d == today
        style = "background:#dbeafe;color:#1d4ed8" if is_today else ""
        hd_html += f'<div class="wl-hd" style="{style}">{dow_names[i]}<br><span style="font-weight:400">{d.day}/{d.month}</span></div>'

    grid_cols = "160px " + " ".join(["1fr"]*7)
    rows_html = ""
    for tech in techs:
        row = f'<div class="wl-name">{_esc(tech["display_name"])}</div>'
        for d in days:
            is_today = d == today
            day_entries = by_user_day.get((tech['id'], str(d)), [])
            cell_content = ""
            for e in day_entries:
                wt = e.get('work_type') or 'proyecto'
                wt_info = WORK_TYPES.get(wt, WORK_TYPES['proyecto'])
                c = wt_info['color']
                h = int(e['total_h'] // 60) if e['total_h'] else 0
                m = int(e['total_h'] % 60) if e['total_h'] else 0
                dur = f"{h}h{m:02d}m" if e['total_h'] else "—"
                pname = e['pname']
                cell_content += (f'<a href="{BP}/projects/{e["pid"]}" '
                    f'class="wl-entry" style="background:{c}" '
                    f'title="{_esc(pname)}">{_esc(pname[:16])} {dur}</a>')
            today_cls = " wl-today" if is_today else ""
            row += f'<div class="wl-cell{today_cls}">{cell_content}</div>'
        rows_html += row

    week_label = f"{days[0].day}/{days[0].month} – {days[6].day}/{days[6].month}/{days[6].year}"
    content = f"""
<div class="toolbar">
  <h1>📊 Cargas de trabajo</h1>
</div>
<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap">
  <a href="{BP}/workload?week={prev_mon}" class="btn btn-ghost btn-sm">← Semana anterior</a>
  <span class="fw7" style="min-width:180px;text-align:center">{week_label}</span>
  <a href="{BP}/workload?week={next_mon}" class="btn btn-ghost btn-sm">Semana siguiente →</a>
  <a href="{BP}/workload" class="btn btn-ghost btn-sm">Hoy</a>
</div>
<div class="card" style="padding:0;overflow:hidden">
  <div class="wl-wrap">
    <div class="wl-grid" style="grid-template-columns:{grid_cols}">
      {hd_html}
      {rows_html}
    </div>
  </div>
</div>
<p class="muted" style="font-size:.78rem;margin-top:8px">
  Muestra jornadas registradas (temporizador) por técnico y día. Sin registros = celda vacía.
</p>"""
    return _shell("workload", user, content)

# ── download page ─────────────────────────────────────────────────────────────
def _download_page(user):
    bp = BP
    apk_size = ""
    apk_path = os.path.join(os.path.dirname(__file__), "data/files/nuvodesk.apk")
    if os.path.exists(apk_path):
        apk_size = f" ({_fmt_size(os.path.getsize(apk_path))})"

    content = f"""
<div class="page-hd">
  <h1>📲 Descargar App</h1>
  <p class="muted">Instala NuvoDesk en tu dispositivo móvil</p>
</div>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;max-width:900px">

  <!-- Android -->
  <div class="card" style="border-top:4px solid #3ddc84">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="font-size:2.5rem">🤖</div>
      <div>
        <div style="font-weight:700;font-size:1.15rem">Android</div>
        <div class="muted" style="font-size:.82rem">Versión 1.0 · mínimo Android 7.0</div>
      </div>
    </div>
    <p style="font-size:.88rem;color:var(--fg);margin-bottom:16px">
      Aplicación nativa WebView que carga NuvoDesk directamente.
      Las sesiones y cookies se mantienen entre aperturas.
    </p>
    <a href="{bp}/data/files/nuvodesk.apk" class="btn btn-primary"
       style="display:inline-flex;gap:8px;text-decoration:none;margin-bottom:12px">
      ⬇ Descargar APK{apk_size}
    </a>
    <div style="background:#f8fafc;border-radius:8px;padding:14px;font-size:.82rem;color:var(--muted)">
      <strong style="color:var(--fg);display:block;margin-bottom:6px">📋 Instrucciones de instalación</strong>
      <ol style="margin:0;padding-left:18px;line-height:1.8">
        <li>Descarga el archivo APK</li>
        <li>En Ajustes → Seguridad → activa <em>«Fuentes desconocidas»</em></li>
        <li>Abre el APK descargado y pulsa Instalar</li>
        <li>La app aparecerá en tu pantalla de inicio</li>
      </ol>
    </div>
  </div>

  <!-- iOS / PWA -->
  <div class="card" style="border-top:4px solid #007aff">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="font-size:2.5rem">🍎</div>
      <div>
        <div style="font-weight:700;font-size:1.15rem">iPhone / iPad</div>
        <div class="muted" style="font-size:.82rem">PWA · iOS 16.4+ recomendado</div>
      </div>
    </div>
    <p style="font-size:.88rem;color:var(--fg);margin-bottom:16px">
      En iOS no se pueden distribuir APK. Usa la función
      <strong>«Añadir a pantalla de inicio»</strong> de Safari para
      instalarla como app nativa (PWA).
    </p>
    <div style="background:#f0f7ff;border-radius:8px;padding:14px;font-size:.82rem;color:var(--fg)">
      <strong style="display:block;margin-bottom:8px">📋 Instalar en iPhone / iPad</strong>
      <ol style="margin:0;padding-left:18px;line-height:2">
        <li>Abre <strong>Safari</strong> y ve a <code>dev.nupro.es/nuvodesk</code></li>
        <li>Pulsa el icono de compartir <strong>⬆</strong> (barra inferior)</li>
        <li>Selecciona <strong>«Añadir a pantalla de inicio»</strong></li>
        <li>Confirma el nombre y pulsa <strong>Añadir</strong></li>
      </ol>
      <div style="margin-top:10px;padding:8px;background:#fff3cd;border-radius:6px;font-size:.78rem">
        ⚠️ Usa siempre Safari — otros navegadores no permiten instalar PWA en iOS
      </div>
    </div>
  </div>

  <!-- Android PWA -->
  <div class="card" style="border-top:4px solid #4285f4">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="font-size:2.5rem">🌐</div>
      <div>
        <div style="font-weight:700;font-size:1.15rem">PWA (todos los dispositivos)</div>
        <div class="muted" style="font-size:.82rem">Sin instalación · siempre actualizado</div>
      </div>
    </div>
    <p style="font-size:.88rem;color:var(--fg);margin-bottom:16px">
      Usa NuvoDesk desde el navegador como si fuera una app.
      Chrome en Android muestra automáticamente el banner de instalación.
    </p>
    <div style="background:#f8fafc;border-radius:8px;padding:14px;font-size:.82rem;color:var(--muted)">
      <strong style="color:var(--fg);display:block;margin-bottom:6px">📋 Instalar en Android (Chrome)</strong>
      <ol style="margin:0;padding-left:18px;line-height:1.8">
        <li>Abre Chrome y visita NuvoDesk</li>
        <li>Pulsa el menú <strong>⋮</strong> (tres puntos)</li>
        <li>Selecciona <strong>«Añadir a pantalla de inicio»</strong></li>
        <li>La app quedará instalada sin descargar nada</li>
      </ol>
    </div>
  </div>

</div>

<div class="card" style="max-width:900px;margin-top:4px;background:#f0fff4;border:1px solid #86efac">
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-size:1.4rem">✅</span>
    <div style="font-size:.85rem">
      <strong>Versión actual:</strong> NuvoDesk 1.0 · APK debug build ·
      La sesión se comparte con el navegador (mismas cookies HTTPS).
    </div>
  </div>
</div>
"""
    return _shell("download", user, content)


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

    def _send(self, code, body, ct="text/html; charset=utf-8", extra_headers=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _upload_file(self, sess, project_id):
        try:
            fields, files = _parse_multipart(self)
            if not files:
                self._json(400, {"error":"No se recibió ningún archivo"}); return
            uploaded = []
            proj_dir = os.path.join(FILES_DIR, str(project_id))
            os.makedirs(proj_dir, exist_ok=True)
            for _field, fobj in files.items():
                orig = fobj['filename'] or 'archivo'
                safe = re.sub(r'[^\w\.\-]', '_', orig)[:180]
                stored = f"{secrets.token_hex(8)}_{safe}"
                path = os.path.join(proj_dir, stored)
                with open(path, 'wb') as fp:
                    fp.write(fobj['data'])
                mime = fobj.get('mime','') or mimetypes.guess_type(orig)[0] or 'application/octet-stream'
                notes = fields.get('notes','')
                fid = run("""INSERT INTO project_files
                    (project_id,filename,original_name,mimetype,size_bytes,uploaded_by,notes)
                    VALUES(?,?,?,?,?,?,?)""",
                    (project_id, stored, orig, mime, len(fobj['data']), sess['id'], notes))
                uploaded.append({'id': fid, 'name': orig})
            self._json(201, {'files': uploaded})
        except Exception as ex:
            self._json(500, {"error": str(ex)})

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

        # Public static assets
        if rel == "/manifest.webmanifest":
            manifest = json.dumps({
                "name": "NuvoDesk",
                "short_name": "NuvoDesk",
                "description": "Gestión de proyectos de campo — Nuvolink",
                "start_url": f"{BP}/",
                "display": "standalone",
                "background_color": "#ffffff",
                "theme_color": "#1e40af",
                "icons": [
                    {"src": f"{BP}/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": f"{BP}/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
                ]
            })
            self._send(200, manifest, "application/manifest+json"); return
        if rel == "/sw.js":
            sw = """self.addEventListener('fetch',function(e){});"""
            self._send(200, sw, "application/javascript"); return

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
        if rel == "/calendar":
            yr = int(qs.get("year",[_date.today().year])[0])
            mo = int(qs.get("month",[_date.today().month])[0])
            self._send(200, _calendar_page(sess, yr, mo)); return
        m = re.match(r"^/calendar/(\d{4}-\d{2}-\d{2})$", rel)
        if m:
            html = _calendar_day(sess, m.group(1))
            self._send(200 if html else 404, html or "Not found"); return
        if rel == "/users":
            if sess.get("role") != "admin": self._redirect(f"{BP}/"); return
            self._send(200, _users_page(sess)); return
        if rel == "/workload":
            wk = qs.get("week",[""])[0]
            self._send(200, _workload_page(sess, wk)); return
        if rel == "/download":
            self._send(200, _download_page(sess)); return

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
        m = re.match(r"^/api/projects/(\d+)/members$", rel)
        if m:
            self._json(200, rs(q("""SELECT pm.*,u.display_name uname FROM project_members pm
                JOIN users u ON u.id=pm.user_id WHERE pm.project_id=?
                ORDER BY pm.start_date""", (int(m.group(1)),)))); return
        m = re.match(r"^/api/projects/(\d+)/files/(.+)$", rel)
        if m:
            pid_f = int(m.group(1)); fname = m.group(2)
            pf = r2d(q1("SELECT * FROM project_files WHERE project_id=? AND filename=?", (pid_f, fname)))
            if not pf: self._send(404, "Not found"); return
            fpath = os.path.join(FILES_DIR, str(pid_f), fname)
            if not os.path.exists(fpath): self._send(404, "Not found"); return
            with open(fpath,'rb') as fp: fdata = fp.read()
            mime = pf['mimetype'] or mimetypes.guess_type(fname)[0] or 'application/octet-stream'
            is_img = mime.startswith('image/')
            disp = 'inline' if is_img else f'attachment; filename="{pf["original_name"]}"'
            self._send(200, fdata, mime, {"Content-Disposition": disp}); return
        if rel == "/api/kit":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            self._json(200, rs(q("SELECT k.*,m.name mat_name,m.code mat_code FROM tech_kit k JOIN materials m ON m.id=k.material_id"))); return

        if rel == "/api/search":
            q_str = (qs.get("q",[""])[0] or "").strip()
            if len(q_str) < 2:
                self._json(200, []); return
            like = f"%{q_str}%"
            results = []
            for proj in rs(q("SELECT id,name,client,reference FROM projects WHERE name LIKE ? OR client LIKE ? OR reference LIKE ? LIMIT 5", (like,like,like))):
                results.append({"type":"proyecto","id":proj["id"],"title":proj["name"],"sub":proj["client"]})
            for t in rs(q("SELECT t.id,t.title,p.id pid,p.name pname FROM tasks t JOIN projects p ON p.id=t.project_id WHERE t.title LIKE ? LIMIT 5", (like,))):
                results.append({"type":"tarea","id":t["id"],"pid":t["pid"],"title":t["title"],"sub":t["pname"]})
            for mat in rs(q("SELECT id,code,name FROM materials WHERE name LIKE ? OR code LIKE ? LIMIT 4", (like,like))):
                results.append({"type":"material","id":mat["id"],"title":mat["name"],"sub":mat["code"]})
            self._json(200, results); return

        m = re.match(r"^/projects/(\d+)/report$", rel)
        if m:
            html = _project_report(sess, int(m.group(1)))
            self._send(200 if html else 404, html or "Not found"); return

        if rel == "/data/files/nuvodesk.apk":
            apk_path = os.path.join(os.path.dirname(__file__), "data/files/nuvodesk.apk")
            if not os.path.exists(apk_path):
                self._send(404, "APK not found"); return
            with open(apk_path, 'rb') as f:
                apk_data = f.read()
            self._send(200, apk_data, "application/vnd.android.package-archive",
                       {"Content-Disposition": 'attachment; filename="nuvodesk.apk"'}); return

        self._send(404, "Not found")

    def do_POST(self):
        p = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) and BP else p.path
        rel = rel or "/"
        req_ct = self.headers.get('Content-Type','')

        # login — parse body before auth check
        if rel == "/api/login":
            data = _body(self)
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

        # file upload (multipart — must be handled before _body() consumes the stream)
        if 'multipart/form-data' in req_ct:
            mf = re.match(r"^/api/projects/(\d+)/files$", rel)
            if mf:
                self._upload_file(sess, int(mf.group(1))); return
            self._json(404, {"error":"Not found"}); return

        data = _body(self)

        # schedule slots
        if rel == "/api/schedule_slots":
            uid = int(data.get("user_id") or 0)
            prj = int(data.get("project_id") or 0)
            sd  = (data.get("slot_date","") or "").strip()
            hs  = int(data.get("hour_start") or 0)
            he  = int(data.get("hour_end") or 0)
            if not uid or not prj or not sd or he <= hs:
                self._json(400, {"error":"Datos inválidos"}); return
            sid = run("""INSERT INTO schedule_slots
                (user_id,project_id,slot_date,hour_start,hour_end,notes)
                VALUES(?,?,?,?,?,?)""",
                (uid, prj, sd, hs, he, data.get("notes","")))
            self._json(201, {"id":sid}); return

        # projects
        if rel == "/api/projects":
            n = (data.get("name","") or "").strip()
            c = (data.get("client","") or "").strip()
            if not n or not c: self._json(400, {"error":"Nombre y cliente requeridos"}); return
            wt = data.get("work_type","proyecto") or "proyecto"
            pid = run("""INSERT INTO projects
                (name,client,description,status,priority,address,reference,
                 contact_name,contact_phone,estimated_hours,start_date,due_date,
                 assigned_to,created_by,work_type,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (n,c,data.get("description",""),data.get("status","active"),
                 data.get("priority","normal"),data.get("address",""),
                 data.get("reference",""),data.get("contact_name",""),
                 data.get("contact_phone",""),float(data.get("estimated_hours") or 0),
                 data.get("start_date",""),data.get("due_date",""),
                 data.get("assigned_to") or None, sess["id"], wt))
            self._json(201, {"id":pid}); return

        # time tracking
        m = re.match(r"^/api/projects/(\d+)/time/start$", rel)
        if m:
            pid = int(m.group(1))
            open_entry = r2d(q1("SELECT id FROM time_entries WHERE user_id=? AND ended_at IS NULL", (sess["id"],)))
            if open_entry:
                self._json(400, {"error":"Ya tienes una jornada activa — párala primero"}); return
            eid = run("""INSERT INTO time_entries (project_id,user_id,started_at,entry_type,notes)
                VALUES(?,?,datetime('now'),?,?)""",
                (pid, sess["id"], data.get("entry_type","work"), data.get("notes","")))
            self._json(201, {"id":eid}); return

        m = re.match(r"^/api/projects/(\d+)/time/stop$", rel)
        if m:
            pid = int(m.group(1))
            open_entry = r2d(q1("SELECT id FROM time_entries WHERE project_id=? AND user_id=? AND ended_at IS NULL",
                (pid, sess["id"])))
            if not open_entry:
                self._json(400, {"error":"No hay jornada activa en este proyecto"}); return
            run("UPDATE time_entries SET ended_at=datetime('now') WHERE id=?", (open_entry["id"],))
            self._json(200, {"ok":True}); return

        # extras
        m = re.match(r"^/api/projects/(\d+)/extras$", rel)
        if m:
            pid = int(m.group(1))
            desc = (data.get("description","") or "").strip()
            if not desc: self._json(400, {"error":"Descripción requerida"}); return
            eid = run("""INSERT INTO wo_extras (project_id,description,quantity,unit,notes,added_by)
                VALUES(?,?,?,?,?,?)""",
                (pid, desc, float(data.get("quantity") or 1),
                 data.get("unit","ud"), data.get("notes",""), sess["id"]))
            self._json(201, {"id":eid}); return

        # equipment
        m = re.match(r"^/api/projects/(\d+)/equipment$", rel)
        if m:
            pid = int(m.group(1))
            model = (data.get("model","") or "").strip()
            if not model: self._json(400, {"error":"Modelo requerido"}); return
            eid = run("""INSERT INTO equipment_items
                (project_id,brand,model,serial_number,quantity,notes,added_by)
                VALUES(?,?,?,?,?,?,?)""",
                (pid, data.get("brand",""), model, data.get("serial_number",""),
                 int(data.get("quantity") or 1), data.get("notes",""), sess["id"]))
            self._json(201, {"id":eid}); return

        # comments
        m = re.match(r"^/api/projects/(\d+)/comments$", rel)
        if m:
            pid = int(m.group(1))
            body = (data.get("body","") or "").strip()
            if not body: self._json(400, {"error":"Texto requerido"}); return
            cid = run("INSERT INTO wo_comments (project_id,user_id,body) VALUES(?,?,?)",
                (pid, sess["id"], body))
            self._json(201, {"id":cid}); return

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

        # project members
        m = re.match(r"^/api/projects/(\d+)/members$", rel)
        if m:
            pid = int(m.group(1))
            uid = int(data.get("user_id") or 0)
            if not uid: self._json(400, {"error":"Usuario requerido"}); return
            try:
                mid = run("""INSERT OR REPLACE INTO project_members
                    (project_id,user_id,start_date,end_date,notes)
                    VALUES(?,?,?,?,?)""",
                    (pid, uid, data.get("start_date",""), data.get("end_date",""),
                     data.get("notes","")))
                self._json(201, {"id":mid}); return
            except Exception as ex:
                self._json(400, {"error":str(ex)}); return

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
                start_date=?,due_date=?,assigned_to=?,work_type=?,updated_at=datetime('now') WHERE id=?""",
                (data.get("name",""),data.get("client",""),data.get("description",""),
                 data.get("status","active"),data.get("priority","normal"),
                 data.get("address",""),data.get("reference",""),data.get("contact_name",""),
                 data.get("contact_phone",""),float(data.get("estimated_hours") or 0),
                 data.get("start_date",""),data.get("due_date",""),
                 data.get("assigned_to") or None,
                 data.get("work_type","proyecto") or "proyecto", pid))
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

        m = re.match(r"^/api/project_members/(\d+)$", rel)
        if m:
            run("DELETE FROM project_members WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/users/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            uid = int(m.group(1))
            if uid == sess["id"]: self._json(400, {"error":"No puedes eliminarte a ti mismo"}); return
            run("DELETE FROM users WHERE id=?", (uid,))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/schedule_slots/(\d+)$", rel)
        if m:
            run("DELETE FROM schedule_slots WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/project_files/(\d+)$", rel)
        if m:
            pf = r2d(q1("SELECT * FROM project_files WHERE id=?", (int(m.group(1)),)))
            if pf:
                fpath = os.path.join(FILES_DIR, str(pf['project_id']), pf['filename'])
                try: os.remove(fpath)
                except: pass
                run("DELETE FROM project_files WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/time_entries/(\d+)$", rel)
        if m:
            eid = int(m.group(1))
            te = r2d(q1("SELECT * FROM time_entries WHERE id=?", (eid,)))
            if te and (te['user_id'] == sess['id'] or sess.get('role') == 'admin'):
                run("DELETE FROM time_entries WHERE id=?", (eid,))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/wo_extras/(\d+)$", rel)
        if m:
            run("DELETE FROM wo_extras WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/equipment_items/(\d+)$", rel)
        if m:
            run("DELETE FROM equipment_items WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/wo_comments/(\d+)$", rel)
        if m:
            cm = r2d(q1("SELECT * FROM wo_comments WHERE id=?", (int(m.group(1)),)))
            if cm and (cm['user_id'] == sess['id'] or sess.get('role') == 'admin'):
                run("DELETE FROM wo_comments WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        self._json(404, {"error":"Not found"})

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"NuvoDesk v2 → http://localhost:{PORT}{BP}/  (admin/admin)")
    server.serve_forever()
