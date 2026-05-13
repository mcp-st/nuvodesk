#!/usr/bin/env python3
"""NuvoDesk — Nuvolink field project & materials management."""

import os, json, sqlite3, hashlib, secrets, threading, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote_plus

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

def _sess_token(h) -> str:
    for part in h.headers.get("Cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() == "nd_sess":
            return v.strip()
    return ""

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

def runmany(sql, data):
    with _dblock:
        db().executemany(sql, data)
        db().commit()

def rs(rows) -> list:
    return [dict(r) for r in rows] if rows else []

def r2d(row) -> dict | None:
    return dict(row) if row else None

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
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    client         TEXT NOT NULL,
    description    TEXT DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'active',
    priority       TEXT NOT NULL DEFAULT 'normal',
    address        TEXT DEFAULT '',
    start_date     TEXT DEFAULT '',
    due_date       TEXT DEFAULT '',
    completed_date TEXT DEFAULT '',
    assigned_to    INTEGER REFERENCES users(id),
    created_by     INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
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
"""

def init_db():
    with _dblock:
        db().executescript(SCHEMA)
        db().commit()
        if db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            db().execute(
                "INSERT INTO users (username,pw_hash,display_name,role) VALUES (?,?,?,?)",
                ("admin", _hash("admin"), "Administrador", "admin"))
            db().commit()

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _esc(s) -> str:
    if s is None: return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

STATUS_LABEL = {
    "active": "Activo", "paused": "Pausado", "completed": "Completado",
    "cancelled": "Cancelado", "pending": "Pendiente", "in_progress": "En curso",
    "done": "Hecho", "blocked": "Bloqueado",
    "requested": "Solicitado", "assigned": "Asignado",
    "consumed": "Consumido", "returned": "Devuelto", "partial": "Parcial"
}
STATUS_COLOR = {
    "active": "#15803d", "paused": "#b45309", "completed": "#1558c2",
    "cancelled": "#6b7280", "pending": "#64748b", "in_progress": "#1558c2",
    "done": "#15803d", "blocked": "#dc2626",
    "requested": "#b45309", "assigned": "#1558c2",
    "consumed": "#15803d", "returned": "#6d28d9", "partial": "#b45309"
}
PRIORITY_COLOR = {"low": "#64748b", "normal": "#1558c2", "high": "#b45309", "urgent": "#dc2626"}

def _badge(status, text=None):
    t = text or STATUS_LABEL.get(status, status)
    c = STATUS_COLOR.get(status, "#64748b")
    return f'<span style="background:{c}22;color:{c};padding:2px 8px;border-radius:12px;font-size:.78rem;font-weight:600">{_esc(t)}</span>'

def _pbadge(priority):
    t = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(priority, priority)
    c = PRIORITY_COLOR.get(priority, "#64748b")
    return f'<span style="color:{c};font-size:.78rem;font-weight:600">▲ {t}</span>'

# ── CSS & shell ───────────────────────────────────────────────────────────────

def _css():
    return """
:root{
  --bg:#f0f4f8;--bg2:#fff;--bg3:#f8fafc;--bg4:#eef2f7;
  --text:#1a2536;--muted:#64748b;--border:#dce4ee;
  --blue:#1558c2;--blue-dim:rgba(21,88,194,.08);
  --green:#15803d;--green-dim:rgba(21,128,61,.1);
  --amber:#b45309;--amber-dim:rgba(180,83,9,.08);
  --red:#dc2626;--red-dim:rgba(220,38,38,.08);
  --violet:#6d28d9;
  --side-bg:#192e4a;--side-text:#c8d8ec;--sidebar-w:220px;
  --radius:8px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;
  background:var(--bg);color:var(--text);display:flex;min-height:100vh}
a{color:var(--blue);text-decoration:none}
/* sidebar */
#sidebar{width:var(--sidebar-w);background:var(--side-bg);color:var(--side-text);
  display:flex;flex-direction:column;min-height:100vh;position:fixed;top:0;left:0;z-index:100}
#sidebar .logo{padding:20px 16px 12px;font-size:1.15rem;font-weight:700;
  color:#fff;letter-spacing:.3px;border-bottom:1px solid rgba(255,255,255,.08)}
#sidebar .logo span{color:#4db6ac;font-size:.7rem;display:block;font-weight:400;letter-spacing:1px;margin-top:2px}
#sidebar nav{flex:1;padding:12px 0}
#sidebar nav a{display:flex;align-items:center;gap:10px;padding:10px 18px;
  color:var(--side-text);font-size:.88rem;transition:background .15s,color .15s}
#sidebar nav a:hover,#sidebar nav a.active{background:rgba(255,255,255,.1);color:#fff}
#sidebar nav a .ic{width:18px;text-align:center;font-size:1rem}
#sidebar .user-area{padding:14px 16px;border-top:1px solid rgba(255,255,255,.08);
  font-size:.8rem;color:var(--side-text)}
#sidebar .user-area strong{color:#fff;display:block}
#sidebar .user-area a{color:#94a3b8;font-size:.75rem}
/* main */
#main{margin-left:var(--sidebar-w);flex:1;padding:28px 32px;max-width:1300px}
h1{font-size:1.4rem;font-weight:700;color:var(--text);margin-bottom:20px}
h2{font-size:1.1rem;font-weight:700;margin-bottom:14px;color:var(--text)}
h3{font-size:.95rem;font-weight:700;margin-bottom:10px}
/* cards */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:20px}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.kpi{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px}
.kpi .val{font-size:2rem;font-weight:700;line-height:1}
.kpi .lbl{font-size:.78rem;color:var(--muted);margin-top:4px}
/* table */
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.75rem;font-weight:600;color:var(--muted);
   text-transform:uppercase;letter-spacing:.5px;padding:8px 12px;
   border-bottom:2px solid var(--border);background:var(--bg3)}
td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--bg3)}
/* buttons */
.btn{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:6px;
  font-size:.83rem;font-weight:600;cursor:pointer;border:none;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:var(--blue);color:#fff}
.btn-success{background:var(--green);color:#fff}
.btn-danger{background:var(--red);color:#fff}
.btn-ghost{background:transparent;color:var(--blue);border:1px solid var(--blue)}
.btn-sm{padding:4px 10px;font-size:.78rem}
/* form */
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.form-row.single{grid-template-columns:1fr}
label{display:block;font-size:.8rem;font-weight:600;color:var(--muted);margin-bottom:4px}
input,select,textarea{width:100%;padding:8px 10px;border:1px solid var(--border);
  border-radius:6px;font-size:.88rem;background:var(--bg3);color:var(--text);outline:none}
input:focus,select:focus,textarea:focus{border-color:var(--blue);background:#fff}
textarea{resize:vertical;min-height:70px}
/* modal */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:500;
  align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:10px;padding:28px;width:min(560px,95vw);
  max-height:90vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,.18)}
.modal h2{margin-bottom:18px}
.modal-foot{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}
/* toolbar */
.toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap;gap:10px}
.toolbar-left{display:flex;align-items:center;gap:10px}
/* alerts */
.alert{padding:10px 14px;border-radius:6px;margin-bottom:16px;font-size:.88rem}
.alert-red{background:var(--red-dim);color:var(--red);border-left:3px solid var(--red)}
.alert-amber{background:var(--amber-dim);color:var(--amber);border-left:3px solid var(--amber)}
/* misc */
.muted{color:var(--muted)}
.chip{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75rem;font-weight:600;
  background:var(--blue-dim);color:var(--blue)}
/* mobile */
@media(max-width:768px){
  #sidebar{transform:translateX(-100%);transition:transform .25s}
  #sidebar.open{transform:translateX(0)}
  #main{margin-left:0;padding:16px}
  .form-row{grid-template-columns:1fr}
  #menu-btn{display:flex}
}
#menu-btn{display:none;position:fixed;top:12px;left:12px;z-index:200;
  background:var(--side-bg);color:#fff;border:none;border-radius:6px;
  padding:8px 10px;font-size:1.1rem;cursor:pointer}
"""

def _shell(page, user, content):
    bp = BP
    nav_items = [
        ("dashboard",   f"{bp}/",              "⊞",  "Dashboard"),
        ("projects",    f"{bp}/projects",       "📋", "Proyectos"),
        ("inventory",   f"{bp}/inventory",      "📦", "Inventario"),
        ("users",       f"{bp}/users",          "👥", "Usuarios"),
    ]
    nav_html = ""
    for key, url, ic, label in nav_items:
        if key == "users" and user.get("role") != "admin":
            continue
        cls = " class=\"active\"" if page == key else ""
        nav_html += f'<a href="{url}"{cls}><span class="ic">{ic}</span>{label}</a>\n'

    role_labels = {"admin": "Administrador", "technician": "Técnico", "backoffice": "Backoffice"}
    role_lbl = role_labels.get(user.get("role",""), user.get("role",""))

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NuvoDesk</title>
<meta name="theme-color" content="#192e4a">
<style>{_css()}</style>
</head>
<body>
<button id="menu-btn" onclick="document.getElementById('sidebar').classList.toggle('open')">☰</button>
<div id="sidebar">
  <div class="logo">NuvoDesk<span>NUVOLINK</span></div>
  <nav>{nav_html}</nav>
  <div class="user-area">
    <strong>{_esc(user.get('display_name',''))}</strong>
    {_esc(role_lbl)} &mdash; <a href="{bp}/logout">Salir</a>
  </div>
</div>
<div id="main">
{content}
</div>
<script>
document.querySelectorAll('#main').forEach(()=>{{
  document.getElementById('sidebar').addEventListener('click', function(e){{
    if(window.innerWidth<=768) this.classList.remove('open');
  }});
}});
</script>
</body>
</html>"""

# ── login page ────────────────────────────────────────────────────────────────

def _login_page(err=""):
    err_html = f'<div class="alert alert-red">{_esc(err)}</div>' if err else ""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NuvoDesk — Login</title>
<style>
{_css()}
body{{display:flex;align-items:center;justify-content:center;min-height:100vh;
  background:var(--bg);}}
.login-box{{background:#fff;border:1px solid var(--border);border-radius:10px;
  padding:36px 32px;width:min(360px,94vw);box-shadow:0 4px 24px rgba(0,0,0,.08)}}
.login-box h1{{text-align:center;margin-bottom:6px;font-size:1.3rem}}
.login-box .sub{{text-align:center;color:var(--muted);font-size:.82rem;margin-bottom:24px}}
.login-box label{{margin-bottom:4px}}
.login-box .field{{margin-bottom:14px}}
.login-box .btn{{width:100%;justify-content:center;padding:10px}}
</style>
</head>
<body>
<div class="login-box">
  <h1>NuvoDesk</h1>
  <p class="sub">Nuvolink — gestión de proyectos</p>
  {err_html}
  <form method="POST" action="{BP}/api/login">
    <div class="field"><label>Usuario</label><input name="username" autofocus autocomplete="username"></div>
    <div class="field"><label>Contraseña</label><input type="password" name="password" autocomplete="current-password"></div>
    <button type="submit" class="btn btn-primary">Entrar</button>
  </form>
</div>
</body>
</html>"""

# ── dashboard page ────────────────────────────────────────────────────────────

def _dashboard(user):
    proj_stats = r2d(q1("""
        SELECT
          COUNT(*) total,
          SUM(CASE WHEN status='active'    THEN 1 ELSE 0 END) active,
          SUM(CASE WHEN status='paused'    THEN 1 ELSE 0 END) paused,
          SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) done
        FROM projects
    """))
    task_stats = r2d(q1("""
        SELECT
          COUNT(*) total,
          SUM(CASE WHEN status='pending'     THEN 1 ELSE 0 END) pending,
          SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) in_progress,
          SUM(CASE WHEN status='done'        THEN 1 ELSE 0 END) done,
          SUM(CASE WHEN status='blocked'     THEN 1 ELSE 0 END) blocked
        FROM tasks
    """))
    low_stock = rs(q("""
        SELECT * FROM materials WHERE stock_warehouse <= stock_min AND stock_min > 0
        ORDER BY (stock_warehouse - stock_min) ASC LIMIT 6
    """))
    recent_proj = rs(q("""
        SELECT p.*, u.display_name as tech_name
        FROM projects p LEFT JOIN users u ON u.id=p.assigned_to
        ORDER BY p.updated_at DESC LIMIT 8
    """))
    overdue = rs(q("""
        SELECT t.*, p.name as project_name
        FROM tasks t JOIN projects p ON p.id=t.project_id
        WHERE t.status NOT IN ('done','cancelled') AND t.due_date != ''
          AND t.due_date < date('now')
        ORDER BY t.due_date ASC LIMIT 8
    """))

    ps = proj_stats or {}
    ts = task_stats or {}

    kpis = f"""
<div class="card-grid">
  <div class="kpi"><div class="val">{ps.get('total',0)}</div><div class="lbl">Proyectos totales</div></div>
  <div class="kpi"><div class="val" style="color:var(--green)">{ps.get('active',0)}</div><div class="lbl">Proyectos activos</div></div>
  <div class="kpi"><div class="val" style="color:var(--amber)">{ps.get('paused',0)}</div><div class="lbl">Pausados</div></div>
  <div class="kpi"><div class="val" style="color:var(--blue)">{ps.get('done',0)}</div><div class="lbl">Completados</div></div>
  <div class="kpi"><div class="val">{ts.get('total',0)}</div><div class="lbl">Tareas totales</div></div>
  <div class="kpi"><div class="val" style="color:var(--red)">{ts.get('blocked',0)}</div><div class="lbl">Tareas bloqueadas</div></div>
</div>"""

    # low stock alert
    low_html = ""
    if low_stock:
        rows = "".join(f"""<tr>
          <td><a href="{BP}/inventory">{_esc(m['code'])}</a></td>
          <td>{_esc(m['name'])}</td>
          <td style="color:var(--red);font-weight:700">{m['stock_warehouse']}</td>
          <td>{m['stock_min']}</td>
          <td>{_esc(m['unit'])}</td>
        </tr>""" for m in low_stock)
        low_html = f"""
<div class="card" style="border-left:4px solid var(--amber)">
  <h2>⚠️ Stock crítico</h2>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Código</th><th>Material</th><th>Stock almacén</th><th>Mínimo</th><th>Ud</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>"""

    # overdue tasks
    od_html = ""
    if overdue:
        rows = "".join(f"""<tr>
          <td><a href="{BP}/projects/{t['project_id']}">{_esc(t['project_name'])}</a></td>
          <td>{_esc(t['title'])}</td>
          <td style="color:var(--red)">{_esc(t['due_date'])}</td>
          <td>{_badge(t['status'])}</td>
        </tr>""" for t in overdue)
        od_html = f"""
<div class="card" style="border-left:4px solid var(--red)">
  <h2>🕒 Tareas vencidas</h2>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Proyecto</th><th>Tarea</th><th>Vencimiento</th><th>Estado</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>"""

    # recent projects
    rp_rows = "".join(f"""<tr>
      <td><a href="{BP}/projects/{p['id']}">{_esc(p['name'])}</a></td>
      <td>{_esc(p['client'])}</td>
      <td>{_badge(p['status'])}</td>
      <td>{_pbadge(p['priority'])}</td>
      <td class="muted">{_esc(p['tech_name'] or '—')}</td>
      <td class="muted">{_esc((p['due_date'] or '—')[:10])}</td>
    </tr>""" for p in recent_proj)

    rp_html = f"""
<div class="card">
  <div class="toolbar">
    <h2>Proyectos recientes</h2>
    <a href="{BP}/projects" class="btn btn-ghost btn-sm">Ver todos</a>
  </div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Proyecto</th><th>Cliente</th><th>Estado</th><th>Prioridad</th><th>Técnico</th><th>Vencimiento</th></tr></thead>
    <tbody>{rp_rows}</tbody>
  </table></div>
</div>"""

    content = f"<h1>Dashboard</h1>{kpis}{low_html}{od_html}{rp_html}"
    return _shell("dashboard", user, content)

# ── projects list page ────────────────────────────────────────────────────────

def _projects_page(user, filter_status=""):
    where = "WHERE p.status=?" if filter_status else ""
    params = (filter_status,) if filter_status else ()
    projects = rs(q(f"""
        SELECT p.*, u.display_name as tech_name,
          (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id) task_total,
          (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') task_done
        FROM projects p LEFT JOIN users u ON u.id=p.assigned_to
        {where}
        ORDER BY
          CASE p.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
          p.updated_at DESC
    """, params))

    techs = rs(q("SELECT id, display_name FROM users WHERE active=1 ORDER BY display_name"))
    tech_opts = "".join(f'<option value="{t["id"]}">{_esc(t["display_name"])}</option>' for t in techs)

    filter_btns = "".join(
        f'<a href="{BP}/projects{"?status="+s if s else ""}" class="btn btn-sm {"btn-primary" if filter_status==s else "btn-ghost"}">{l}</a>'
        for s, l in [("","Todos"),("active","Activos"),("paused","Pausados"),("completed","Completados"),("cancelled","Cancelados")]
    )

    rows = ""
    for p in projects:
        pct = int(p['task_done']/p['task_total']*100) if p['task_total'] else 0
        prog = f'<div style="background:#e2e8f0;border-radius:4px;height:6px;width:80px"><div style="background:var(--blue);width:{pct}%;height:100%;border-radius:4px"></div></div><span class="muted" style="font-size:.75rem">{pct}%</span>'
        rows += f"""<tr>
          <td><a href="{BP}/projects/{p['id']}" style="font-weight:600">{_esc(p['name'])}</a><br>
              <span class="muted" style="font-size:.78rem">{_esc(p['client'])}</span></td>
          <td>{_badge(p['status'])}</td>
          <td>{_pbadge(p['priority'])}</td>
          <td class="muted">{_esc(p['tech_name'] or '—')}</td>
          <td class="muted">{_esc((p['due_date'] or '—')[:10])}</td>
          <td>{prog}</td>
          <td>
            <button class="btn btn-ghost btn-sm" onclick="editProject({json.dumps(dict(p))})">✏️</button>
            <a href="{BP}/projects/{p['id']}" class="btn btn-ghost btn-sm">Ver</a>
          </td>
        </tr>"""

    content = f"""
<div class="toolbar">
  <h1>Proyectos</h1>
  <button class="btn btn-primary" onclick="openNew()">+ Nuevo proyecto</button>
</div>
<div class="toolbar-left" style="margin-bottom:16px">{filter_btns}</div>
<div class="card">
  <div class="tbl-wrap"><table>
    <thead><tr><th>Proyecto / Cliente</th><th>Estado</th><th>Prioridad</th><th>Técnico</th><th>Vencimiento</th><th>Avance tareas</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>

<!-- Modal create/edit -->
<div class="modal-bg" id="proj-modal">
<div class="modal">
  <h2 id="modal-title">Nuevo proyecto</h2>
  <form id="proj-form">
    <input type="hidden" id="proj-id">
    <div class="form-row">
      <div><label>Nombre</label><input id="f-name" required></div>
      <div><label>Cliente</label><input id="f-client" required></div>
    </div>
    <div class="form-row single">
      <div><label>Descripción</label><textarea id="f-desc"></textarea></div>
    </div>
    <div class="form-row">
      <div><label>Estado</label>
        <select id="f-status">
          <option value="active">Activo</option><option value="paused">Pausado</option>
          <option value="completed">Completado</option><option value="cancelled">Cancelado</option>
        </select>
      </div>
      <div><label>Prioridad</label>
        <select id="f-priority">
          <option value="low">Baja</option><option value="normal">Normal</option>
          <option value="high">Alta</option><option value="urgent">Urgente</option>
        </select>
      </div>
    </div>
    <div class="form-row single">
      <div><label>Dirección / Localización</label><input id="f-address"></div>
    </div>
    <div class="form-row">
      <div><label>Fecha inicio</label><input type="date" id="f-start"></div>
      <div><label>Fecha límite</label><input type="date" id="f-due"></div>
    </div>
    <div class="form-row">
      <div><label>Técnico responsable</label>
        <select id="f-tech"><option value="">Sin asignar</option>{tech_opts}</select>
      </div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="closeModal()">Cancelar</button>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </div>
  </form>
</div>
</div>

<script>
var bp = {json.dumps(BP)};
function openNew(){{
  document.getElementById('modal-title').textContent='Nuevo proyecto';
  document.getElementById('proj-id').value='';
  ['name','client','desc','address'].forEach(function(f){{document.getElementById('f-'+f).value=''}});
  ['start','due'].forEach(function(f){{document.getElementById('f-'+f).value=''}});
  document.getElementById('f-status').value='active';
  document.getElementById('f-priority').value='normal';
  document.getElementById('f-tech').value='';
  document.getElementById('proj-modal').classList.add('open');
}}
function editProject(p){{
  document.getElementById('modal-title').textContent='Editar proyecto';
  document.getElementById('proj-id').value=p.id;
  document.getElementById('f-name').value=p.name||'';
  document.getElementById('f-client').value=p.client||'';
  document.getElementById('f-desc').value=p.description||'';
  document.getElementById('f-address').value=p.address||'';
  document.getElementById('f-start').value=p.start_date||'';
  document.getElementById('f-due').value=p.due_date||'';
  document.getElementById('f-status').value=p.status||'active';
  document.getElementById('f-priority').value=p.priority||'normal';
  document.getElementById('f-tech').value=p.assigned_to||'';
  document.getElementById('proj-modal').classList.add('open');
}}
function closeModal(){{document.getElementById('proj-modal').classList.remove('open');}}
document.getElementById('proj-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('proj-id').value;
  var data={{
    name:document.getElementById('f-name').value,
    client:document.getElementById('f-client').value,
    description:document.getElementById('f-desc').value,
    address:document.getElementById('f-address').value,
    start_date:document.getElementById('f-start').value,
    due_date:document.getElementById('f-due').value,
    status:document.getElementById('f-status').value,
    priority:document.getElementById('f-priority').value,
    assigned_to:document.getElementById('f-tech').value||null
  }};
  var url=id ? bp+'/api/projects/'+id : bp+'/api/projects';
  var method=id ? 'PUT' : 'POST';
  fetch(url,{{method:method,headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})
    .then(function(r){{if(r.ok) location.reload(); else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
document.getElementById('proj-modal').onclick=function(e){{if(e.target===this)closeModal();}};
</script>"""
    return _shell("projects", user, content)

# ── project detail page ───────────────────────────────────────────────────────

def _project_detail(user, pid):
    p = r2d(q1("""
        SELECT p.*, u.display_name as tech_name
        FROM projects p LEFT JOIN users u ON u.id=p.assigned_to
        WHERE p.id=?
    """, (pid,)))
    if not p:
        return None

    tasks = rs(q("""
        SELECT t.*, u.display_name as tech_name
        FROM tasks t LEFT JOIN users u ON u.id=t.assigned_to
        WHERE t.project_id=?
        ORDER BY CASE t.status WHEN 'blocked' THEN 0 WHEN 'in_progress' THEN 1
          WHEN 'pending' THEN 2 ELSE 3 END, t.priority DESC, t.created_at
    """, (pid,)))

    assignments = rs(q("""
        SELECT a.*, m.name as mat_name, m.code as mat_code, m.unit as mat_unit
        FROM assignments a JOIN materials m ON m.id=a.material_id
        WHERE a.project_id=?
        ORDER BY a.created_at DESC
    """, (pid,)))

    techs = rs(q("SELECT id, display_name FROM users WHERE active=1 ORDER BY display_name"))
    mats  = rs(q("SELECT id, code, name, unit, stock_warehouse FROM materials ORDER BY name"))

    tech_opts = "".join(f'<option value="{t["id"]}">{_esc(t["display_name"])}</option>' for t in techs)
    mat_opts  = "".join(f'<option value="{m["id"]}" data-stock="{m["stock_warehouse"]}">[{_esc(m["code"])}] {_esc(m["name"])} ({_esc(m["unit"])})</option>' for m in mats)

    # task rows
    t_rows = ""
    for t in tasks:
        t_rows += f"""<tr>
          <td style="font-weight:600">{_esc(t['title'])}</td>
          <td>{_badge(t['status'])}</td>
          <td>{_pbadge(t['priority'])}</td>
          <td class="muted">{_esc(t['tech_name'] or '—')}</td>
          <td class="muted">{_esc((t['due_date'] or '—')[:10])}</td>
          <td>
            <button class="btn btn-ghost btn-sm" onclick="editTask({json.dumps(dict(t))})">✏️</button>
            <button class="btn btn-danger btn-sm" onclick="delTask({t['id']})">✕</button>
          </td>
        </tr>"""

    # assignment rows
    a_rows = ""
    for a in assignments:
        a_rows += f"""<tr>
          <td>[{_esc(a['mat_code'])}] {_esc(a['mat_name'])}</td>
          <td style="text-align:center">{a['qty_requested']}</td>
          <td style="text-align:center">{a['qty_assigned']}</td>
          <td style="text-align:center">{a['qty_consumed']}</td>
          <td style="text-align:center">{a['qty_returned']}</td>
          <td>{_badge(a['status'])}</td>
          <td class="muted">{_esc(a['mat_unit'])}</td>
          <td>
            <button class="btn btn-ghost btn-sm" onclick="updateAssign({a['id']}, {json.dumps(dict(a))})">⚙️</button>
          </td>
        </tr>"""

    priority_label = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(p['priority'], p['priority'])
    priority_color = PRIORITY_COLOR.get(p['priority'], "#64748b")
    desc_html = f'<div class="card"><p>{_esc(p["description"])}</p></div>' if p.get('description') else ''

    content = f"""
<div style="display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:6px">
  <a href="{BP}/projects" class="muted" style="font-size:.85rem">← Proyectos</a>
</div>
<div class="toolbar">
  <div>
    <h1 style="margin-bottom:4px">{_esc(p['name'])}</h1>
    <span class="muted">{_esc(p['client'])}</span>
    &nbsp;{_badge(p['status'])}
    &nbsp;<span style="color:{priority_color};font-weight:600;font-size:.8rem">▲ {priority_label}</span>
  </div>
  <button class="btn btn-ghost btn-sm" onclick="editProject({json.dumps(p)})">✏️ Editar proyecto</button>
</div>

<div class="card-grid" style="grid-template-columns:repeat(auto-fill,minmax(160px,1fr));margin-bottom:20px">
  <div class="kpi"><div class="val" style="font-size:1rem">{_esc(p['tech_name'] or '—')}</div><div class="lbl">Técnico</div></div>
  <div class="kpi"><div class="val" style="font-size:1rem">{_esc((p['start_date'] or '—')[:10])}</div><div class="lbl">Inicio</div></div>
  <div class="kpi"><div class="val" style="font-size:1rem">{_esc((p['due_date'] or '—')[:10])}</div><div class="lbl">Fecha límite</div></div>
  <div class="kpi"><div class="val" style="font-size:1rem">{_esc(p['address'] or '—')}</div><div class="lbl">Dirección</div></div>
</div>

{desc_html}

<!-- TASKS -->
<div class="card">
  <div class="toolbar">
    <h2>Tareas ({len(tasks)})</h2>
    <button class="btn btn-primary btn-sm" onclick="openNewTask()">+ Tarea</button>
  </div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Título</th><th>Estado</th><th>Prioridad</th><th>Asignada a</th><th>Vencimiento</th><th></th></tr></thead>
    <tbody>{t_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:20px'>Sin tareas</td></tr>"}</tbody>
  </table></div>
</div>

<!-- MATERIALS -->
<div class="card">
  <div class="toolbar">
    <h2>Materiales asignados ({len(assignments)})</h2>
    <button class="btn btn-primary btn-sm" onclick="openNewAssign()">+ Material</button>
  </div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Material</th><th style="text-align:center">Solicitado</th><th style="text-align:center">Asignado</th>
      <th style="text-align:center">Consumido</th><th style="text-align:center">Devuelto</th>
      <th>Estado</th><th>Ud</th><th></th></tr></thead>
    <tbody>{a_rows or "<tr><td colspan='8' class='muted' style='text-align:center;padding:20px'>Sin materiales</td></tr>"}</tbody>
  </table></div>
</div>

<!-- Edit project modal -->
<div class="modal-bg" id="proj-modal">
<div class="modal">
  <h2 id="modal-title-p">Editar proyecto</h2>
  <form id="proj-form">
    <input type="hidden" id="proj-id" value="{p['id']}">
    <div class="form-row">
      <div><label>Nombre</label><input id="f-name"></div>
      <div><label>Cliente</label><input id="f-client"></div>
    </div>
    <div class="form-row single"><div><label>Descripción</label><textarea id="f-desc"></textarea></div></div>
    <div class="form-row">
      <div><label>Estado</label>
        <select id="f-status">
          <option value="active">Activo</option><option value="paused">Pausado</option>
          <option value="completed">Completado</option><option value="cancelled">Cancelado</option>
        </select>
      </div>
      <div><label>Prioridad</label>
        <select id="f-priority">
          <option value="low">Baja</option><option value="normal">Normal</option>
          <option value="high">Alta</option><option value="urgent">Urgente</option>
        </select>
      </div>
    </div>
    <div class="form-row single"><div><label>Dirección</label><input id="f-address"></div></div>
    <div class="form-row">
      <div><label>Inicio</label><input type="date" id="f-start"></div>
      <div><label>Límite</label><input type="date" id="f-due"></div>
    </div>
    <div class="form-row"><div><label>Técnico</label>
      <select id="f-tech"><option value="">Sin asignar</option>{tech_opts}</select>
    </div></div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="closeProjModal()">Cancelar</button>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </div>
  </form>
</div>
</div>

<!-- Task modal -->
<div class="modal-bg" id="task-modal">
<div class="modal">
  <h2 id="task-modal-title">Nueva tarea</h2>
  <form id="task-form">
    <input type="hidden" id="task-id">
    <div class="form-row single"><div><label>Título</label><input id="t-title" required></div></div>
    <div class="form-row single"><div><label>Descripción</label><textarea id="t-desc"></textarea></div></div>
    <div class="form-row">
      <div><label>Estado</label>
        <select id="t-status">
          <option value="pending">Pendiente</option><option value="in_progress">En curso</option>
          <option value="done">Hecho</option><option value="blocked">Bloqueado</option>
        </select>
      </div>
      <div><label>Prioridad</label>
        <select id="t-priority">
          <option value="low">Baja</option><option value="normal">Normal</option>
          <option value="high">Alta</option><option value="urgent">Urgente</option>
        </select>
      </div>
    </div>
    <div class="form-row">
      <div><label>Asignada a</label><select id="t-tech"><option value="">Sin asignar</option>{tech_opts}</select></div>
      <div><label>Fecha límite</label><input type="date" id="t-due"></div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="closeTaskModal()">Cancelar</button>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </div>
  </form>
</div>
</div>

<!-- Assignment modal -->
<div class="modal-bg" id="assign-modal">
<div class="modal">
  <h2 id="assign-modal-title">Asignar material</h2>
  <form id="assign-form">
    <input type="hidden" id="assign-id">
    <div class="form-row single"><div><label>Material</label>
      <select id="a-mat">{mat_opts}</select>
      <span id="a-stock-info" style="font-size:.78rem;color:var(--muted);margin-top:4px;display:block"></span>
    </div></div>
    <div class="form-row">
      <div><label>Cantidad solicitada</label><input type="number" id="a-req" min="0" value="1"></div>
      <div><label>Cantidad asignada</label><input type="number" id="a-asgn" min="0" value="0"></div>
    </div>
    <div class="form-row">
      <div><label>Consumido</label><input type="number" id="a-cons" min="0" value="0"></div>
      <div><label>Devuelto</label><input type="number" id="a-ret" min="0" value="0"></div>
    </div>
    <div class="form-row single"><div><label>Estado</label>
      <select id="a-status">
        <option value="requested">Solicitado</option><option value="assigned">Asignado</option>
        <option value="consumed">Consumido</option><option value="returned">Devuelto</option>
        <option value="partial">Parcial</option>
      </select>
    </div></div>
    <div class="form-row single"><div><label>Notas</label><textarea id="a-notes"></textarea></div></div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="closeAssignModal()">Cancelar</button>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </div>
  </form>
</div>
</div>

<script>
var bp={json.dumps(BP)};
var pid={pid};

// --- project modal ---
function editProject(p){{
  document.getElementById('f-name').value=p.name||'';
  document.getElementById('f-client').value=p.client||'';
  document.getElementById('f-desc').value=p.description||'';
  document.getElementById('f-address').value=p.address||'';
  document.getElementById('f-start').value=p.start_date||'';
  document.getElementById('f-due').value=p.due_date||'';
  document.getElementById('f-status').value=p.status||'active';
  document.getElementById('f-priority').value=p.priority||'normal';
  document.getElementById('f-tech').value=p.assigned_to||'';
  document.getElementById('proj-modal').classList.add('open');
}}
function closeProjModal(){{document.getElementById('proj-modal').classList.remove('open');}}
document.getElementById('proj-modal').onclick=function(e){{if(e.target===this)closeProjModal();}};
document.getElementById('proj-form').onsubmit=function(e){{
  e.preventDefault();
  fetch(bp+'/api/projects/'+pid,{{method:'PUT',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{
      name:document.getElementById('f-name').value,
      client:document.getElementById('f-client').value,
      description:document.getElementById('f-desc').value,
      address:document.getElementById('f-address').value,
      start_date:document.getElementById('f-start').value,
      due_date:document.getElementById('f-due').value,
      status:document.getElementById('f-status').value,
      priority:document.getElementById('f-priority').value,
      assigned_to:document.getElementById('f-tech').value||null
    }})
  }}).then(function(r){{if(r.ok)location.reload();}});
}};

// --- task modal ---
function openNewTask(){{
  document.getElementById('task-modal-title').textContent='Nueva tarea';
  document.getElementById('task-id').value='';
  ['title','desc'].forEach(function(f){{document.getElementById('t-'+f).value='';}});
  document.getElementById('t-status').value='pending';
  document.getElementById('t-priority').value='normal';
  document.getElementById('t-tech').value='';
  document.getElementById('t-due').value='';
  document.getElementById('task-modal').classList.add('open');
}}
function editTask(t){{
  document.getElementById('task-modal-title').textContent='Editar tarea';
  document.getElementById('task-id').value=t.id;
  document.getElementById('t-title').value=t.title||'';
  document.getElementById('t-desc').value=t.description||'';
  document.getElementById('t-status').value=t.status||'pending';
  document.getElementById('t-priority').value=t.priority||'normal';
  document.getElementById('t-tech').value=t.assigned_to||'';
  document.getElementById('t-due').value=t.due_date||'';
  document.getElementById('task-modal').classList.add('open');
}}
function closeTaskModal(){{document.getElementById('task-modal').classList.remove('open');}}
document.getElementById('task-modal').onclick=function(e){{if(e.target===this)closeTaskModal();}};
document.getElementById('task-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('task-id').value;
  var data={{
    title:document.getElementById('t-title').value,
    description:document.getElementById('t-desc').value,
    status:document.getElementById('t-status').value,
    priority:document.getElementById('t-priority').value,
    assigned_to:document.getElementById('t-tech').value||null,
    due_date:document.getElementById('t-due').value
  }};
  if(id){{
    fetch(bp+'/api/tasks/'+id,{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})
      .then(function(r){{if(r.ok)location.reload();}});
  }}else{{
    fetch(bp+'/api/projects/'+pid+'/tasks',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})
      .then(function(r){{if(r.ok)location.reload();}});
  }}
}};
function delTask(id){{
  if(!confirm('¿Eliminar tarea?')) return;
  fetch(bp+'/api/tasks/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
}}

// --- assignment modal ---
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
function updateAssign(id, a){{
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
  var stock=opt ? opt.getAttribute('data-stock') : '?';
  document.getElementById('a-stock-info').textContent='Stock en almacén: '+stock;
}}
document.getElementById('a-mat').onchange=updateStockInfo;
document.getElementById('assign-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('assign-id').value;
  var data={{
    material_id:document.getElementById('a-mat').value,
    qty_requested:parseInt(document.getElementById('a-req').value)||0,
    qty_assigned:parseInt(document.getElementById('a-asgn').value)||0,
    qty_consumed:parseInt(document.getElementById('a-cons').value)||0,
    qty_returned:parseInt(document.getElementById('a-ret').value)||0,
    status:document.getElementById('a-status').value,
    notes:document.getElementById('a-notes').value
  }};
  if(id){{
    fetch(bp+'/api/assignments/'+id,{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})
      .then(function(r){{if(r.ok)location.reload();}});
  }}else{{
    fetch(bp+'/api/projects/'+pid+'/assignments',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})
      .then(function(r){{if(r.ok)location.reload(); else r.json().then(function(j){{alert(j.error||'Error');}});}});
  }}
}};
</script>"""
    return _shell("projects", user, content)

# ── inventory page ────────────────────────────────────────────────────────────

def _inventory_page(user):
    cats = [r[0] for r in q("SELECT DISTINCT category FROM materials WHERE category!='' ORDER BY category")]
    materials = rs(q("""
        SELECT * FROM materials ORDER BY category, name
    """))

    cat_filter_btns = "".join(
        f'<a href="{BP}/inventory?cat={_esc(c)}" class="btn btn-sm btn-ghost">{_esc(c)}</a>'
        for c in cats
    )

    rows = ""
    for m in materials:
        total = m['stock_warehouse'] + m['stock_field']
        critical = m['stock_warehouse'] <= m['stock_min'] and m['stock_min'] > 0
        stock_style = 'color:var(--red);font-weight:700' if critical else ''
        rows += f"""<tr>
          <td><span class="chip">{_esc(m['code'])}</span></td>
          <td style="font-weight:600">{_esc(m['name'])}</td>
          <td class="muted">{_esc(m['category'] or '—')}</td>
          <td style="text-align:center;{stock_style}">{m['stock_warehouse']}</td>
          <td style="text-align:center">{m['stock_field']}</td>
          <td style="text-align:center">{total}</td>
          <td style="text-align:center">{m['stock_min']}</td>
          <td class="muted">{_esc(m['unit'])}</td>
          <td>
            <button class="btn btn-ghost btn-sm" onclick="editMat({json.dumps(dict(m))})">✏️</button>
            <button class="btn btn-danger btn-sm" onclick="delMat({m['id']})">✕</button>
          </td>
        </tr>"""

    content = f"""
<div class="toolbar">
  <h1>Inventario</h1>
  <button class="btn btn-primary" onclick="openNewMat()">+ Material</button>
</div>
<div class="toolbar-left" style="margin-bottom:16px">
  <a href="{BP}/inventory" class="btn btn-sm btn-primary">Todos</a>
  {cat_filter_btns}
</div>
<div class="card">
  <div class="tbl-wrap"><table>
    <thead><tr>
      <th>Código</th><th>Nombre</th><th>Categoría</th>
      <th style="text-align:center">Almacén</th><th style="text-align:center">Campo</th>
      <th style="text-align:center">Total</th><th style="text-align:center">Mínimo</th>
      <th>Ud</th><th></th>
    </tr></thead>
    <tbody>{rows or "<tr><td colspan='9' class='muted' style='text-align:center;padding:20px'>Sin materiales</td></tr>"}</tbody>
  </table></div>
</div>

<div class="modal-bg" id="mat-modal">
<div class="modal">
  <h2 id="mat-modal-title">Nuevo material</h2>
  <form id="mat-form">
    <input type="hidden" id="mat-id">
    <div class="form-row">
      <div><label>Código</label><input id="m-code" required></div>
      <div><label>Nombre</label><input id="m-name" required></div>
    </div>
    <div class="form-row">
      <div><label>Categoría</label><input id="m-cat" list="cat-list">
        <datalist id="cat-list">{" ".join(f"<option>{_esc(c)}</option>" for c in cats)}</datalist>
      </div>
      <div><label>Unidad</label>
        <select id="m-unit">
          <option value="ud">ud</option><option value="m">m</option>
          <option value="m2">m²</option><option value="kg">kg</option>
          <option value="l">l</option><option value="bobina">bobina</option>
          <option value="caja">caja</option><option value="rollo">rollo</option>
        </select>
      </div>
    </div>
    <div class="form-row single"><div><label>Descripción</label><textarea id="m-desc"></textarea></div></div>
    <div class="form-row">
      <div><label>Stock almacén</label><input type="number" id="m-wh" min="0" value="0"></div>
      <div><label>Stock campo</label><input type="number" id="m-fi" min="0" value="0"></div>
    </div>
    <div class="form-row">
      <div><label>Stock mínimo</label><input type="number" id="m-min" min="0" value="0"></div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="closeMatModal()">Cancelar</button>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </div>
  </form>
</div>
</div>

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
  var data={{
    code:document.getElementById('m-code').value,
    name:document.getElementById('m-name').value,
    category:document.getElementById('m-cat').value,
    description:document.getElementById('m-desc').value,
    unit:document.getElementById('m-unit').value,
    stock_warehouse:parseInt(document.getElementById('m-wh').value)||0,
    stock_field:parseInt(document.getElementById('m-fi').value)||0,
    stock_min:parseInt(document.getElementById('m-min').value)||0
  }};
  var url=id ? bp+'/api/materials/'+id : bp+'/api/materials';
  fetch(url,{{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})
    .then(function(r){{if(r.ok)location.reload(); else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
function delMat(id){{
  if(!confirm('¿Eliminar material?')) return;
  fetch(bp+'/api/materials/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload(); else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
</script>"""
    return _shell("inventory", user, content)

# ── users page ────────────────────────────────────────────────────────────────

def _users_page(user):
    users = rs(q("SELECT id,username,display_name,role,active,created_at FROM users ORDER BY display_name"))
    rows = ""
    for u in users:
        role_lbl = {"admin":"Administrador","technician":"Técnico","backoffice":"Backoffice"}.get(u['role'], u['role'])
        active_badge = f'<span style="color:var(--green);font-weight:600">● Activo</span>' if u['active'] else '<span style="color:var(--muted)">○ Inactivo</span>'
        uid_val = u['id']
        del_btn = "" if uid_val == user['id'] else f'<button class="btn btn-danger btn-sm" onclick="delUser({uid_val})">✕</button>'
        rows += f"""<tr>
          <td style="font-weight:600">{_esc(u['display_name'])}</td>
          <td class="muted">{_esc(u['username'])}</td>
          <td>{_esc(role_lbl)}</td>
          <td>{active_badge}</td>
          <td class="muted">{_esc((u['created_at'] or '')[:10])}</td>
          <td>
            <button class="btn btn-ghost btn-sm" onclick="editUser({json.dumps(dict(u))})">✏️</button>
            {del_btn}
          </td>
        </tr>"""

    content = f"""
<div class="toolbar">
  <h1>Usuarios</h1>
  <button class="btn btn-primary" onclick="openNewUser()">+ Usuario</button>
</div>
<div class="card">
  <div class="tbl-wrap"><table>
    <thead><tr><th>Nombre</th><th>Usuario</th><th>Rol</th><th>Estado</th><th>Creado</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>

<div class="modal-bg" id="user-modal">
<div class="modal">
  <h2 id="user-modal-title">Nuevo usuario</h2>
  <form id="user-form">
    <input type="hidden" id="user-id">
    <div class="form-row">
      <div><label>Nombre completo</label><input id="u-display" required></div>
      <div><label>Usuario</label><input id="u-username" required autocomplete="off"></div>
    </div>
    <div class="form-row">
      <div><label>Contraseña <span id="u-pw-hint" class="muted">(dejar en blanco para no cambiar)</span></label>
        <input type="password" id="u-pw" autocomplete="new-password">
      </div>
      <div><label>Rol</label>
        <select id="u-role">
          <option value="technician">Técnico</option>
          <option value="backoffice">Backoffice</option>
          <option value="admin">Administrador</option>
        </select>
      </div>
    </div>
    <div class="form-row"><div><label>Activo</label>
      <select id="u-active"><option value="1">Sí</option><option value="0">No</option></select>
    </div></div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="closeUserModal()">Cancelar</button>
      <button type="submit" class="btn btn-primary">Guardar</button>
    </div>
  </form>
</div>
</div>

<script>
var bp={json.dumps(BP)};
function openNewUser(){{
  document.getElementById('user-modal-title').textContent='Nuevo usuario';
  document.getElementById('user-id').value='';
  document.getElementById('u-display').value='';
  document.getElementById('u-username').value='';
  document.getElementById('u-pw').value='';
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
  var data={{
    display_name:document.getElementById('u-display').value,
    username:document.getElementById('u-username').value,
    role:document.getElementById('u-role').value,
    active:document.getElementById('u-active').value==='1'?1:0
  }};
  var pw=document.getElementById('u-pw').value;
  if(pw) data.password=pw;
  var url=id ? bp+'/api/users/'+id : bp+'/api/users';
  fetch(url,{{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})
    .then(function(r){{if(r.ok)location.reload(); else r.json().then(function(j){{alert(j.error||'Error');}});}});
}};
function delUser(id){{
  if(!confirm('¿Eliminar usuario?')) return;
  fetch(bp+'/api/users/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
}}
</script>"""
    return _shell("users", user, content)

# ── HTTP handler ──────────────────────────────────────────────────────────────

def _body(h) -> dict:
    length = int(h.headers.get("Content-Length", 0))
    if not length:
        return {}
    raw = h.rfile.read(length)
    ct = h.headers.get("Content-Type", "")
    if "json" in ct:
        try:
            return json.loads(raw)
        except Exception:
            return {}
    # form-urlencoded
    parts = {}
    for pair in raw.decode().split("&"):
        k, _, v = pair.partition("=")
        parts[unquote_plus(k)] = unquote_plus(v)
    return parts

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ct="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _json(self, code, data):
        self._send(code, json.dumps(data), "application/json")

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def _require_auth(self):
        sess = _get_sess(self)
        if not sess:
            self._redirect(f"{BP}/login")
            return None
        return sess

    def _require_admin(self):
        sess = self._require_auth()
        if sess and sess.get("role") != "admin":
            self._json(403, {"error": "Acceso denegado"})
            return None
        return sess

    def do_GET(self):
        p = urlparse(self.path)
        path = p.path.rstrip("/") or "/"
        qs   = parse_qs(p.query)

        # strip base path
        rel = path[len(BP):] if path.startswith(BP) else path
        rel = rel or "/"

        # static: manifest
        if rel == "/manifest.json":
            self._send(200, json.dumps({
                "name":"NuvoDesk","short_name":"NuvoDesk","start_url":f"{BP}/",
                "display":"standalone","background_color":"#192e4a","theme_color":"#192e4a",
                "icons":[{"src":f"{BP}/icon.png","sizes":"192x192","type":"image/png"}]
            }), "application/json")
            return

        if rel == "/login":
            self._send(200, _login_page())
            return

        if rel == "/logout":
            _del_sess(self)
            tok = _sess_token(self)
            self.send_response(302)
            self.send_header("Location", f"{BP}/login")
            self.send_header("Set-Cookie", f"nd_sess=; Path={BP or '/'}; Max-Age=0; HttpOnly")
            self.end_headers()
            return

        sess = _get_sess(self)
        if not sess:
            self._redirect(f"{BP}/login")
            return

        if rel in ("/", "/dashboard"):
            self._send(200, _dashboard(sess))
            return

        if rel == "/projects":
            fs = qs.get("status", [""])[0]
            self._send(200, _projects_page(sess, fs))
            return

        m = re.match(r"^/projects/(\d+)$", rel)
        if m:
            pid = int(m.group(1))
            html = _project_detail(sess, pid)
            if html:
                self._send(200, html)
            else:
                self._send(404, "Not found")
            return

        if rel == "/inventory":
            self._send(200, _inventory_page(sess))
            return

        if rel == "/users":
            if sess.get("role") != "admin":
                self._redirect(f"{BP}/")
                return
            self._send(200, _users_page(sess))
            return

        # JSON APIs
        if rel == "/api/projects":
            rows = rs(q("""
                SELECT p.*, u.display_name as tech_name
                FROM projects p LEFT JOIN users u ON u.id=p.assigned_to
                ORDER BY p.updated_at DESC
            """))
            self._json(200, rows)
            return

        m = re.match(r"^/api/projects/(\d+)$", rel)
        if m:
            row = r2d(q1("SELECT * FROM projects WHERE id=?", (int(m.group(1)),)))
            if row: self._json(200, row)
            else:   self._json(404, {"error": "Not found"})
            return

        m = re.match(r"^/api/projects/(\d+)/tasks$", rel)
        if m:
            rows = rs(q("SELECT * FROM tasks WHERE project_id=? ORDER BY created_at", (int(m.group(1)),)))
            self._json(200, rows)
            return

        m = re.match(r"^/api/tasks/(\d+)$", rel)
        if m:
            row = r2d(q1("SELECT * FROM tasks WHERE id=?", (int(m.group(1)),)))
            if row: self._json(200, row)
            else:   self._json(404, {"error": "Not found"})
            return

        if rel == "/api/materials":
            self._json(200, rs(q("SELECT * FROM materials ORDER BY name")))
            return

        m = re.match(r"^/api/materials/(\d+)$", rel)
        if m:
            row = r2d(q1("SELECT * FROM materials WHERE id=?", (int(m.group(1)),)))
            if row: self._json(200, row)
            else:   self._json(404, {"error": "Not found"})
            return

        m = re.match(r"^/api/projects/(\d+)/assignments$", rel)
        if m:
            rows = rs(q("""
                SELECT a.*, m.name as mat_name, m.code as mat_code
                FROM assignments a JOIN materials m ON m.id=a.material_id
                WHERE a.project_id=?
            """, (int(m.group(1)),)))
            self._json(200, rows)
            return

        if rel == "/api/users":
            if sess.get("role") != "admin":
                self._json(403, {"error": "Forbidden"})
                return
            self._json(200, rs(q("SELECT id,username,display_name,role,active FROM users ORDER BY display_name")))
            return

        self._send(404, "Not found")

    def do_POST(self):
        p    = urlparse(self.path)
        rel  = p.path[len(BP):] if p.path.startswith(BP) else p.path
        rel  = rel or "/"
        data = _body(self)

        # ── login ──
        if rel == "/api/login":
            username = data.get("username", "").strip()
            password = data.get("password", "")
            user = r2d(q1("SELECT * FROM users WHERE username=? AND active=1", (username,)))
            if not user or user["pw_hash"] != _hash(password):
                self._send(200, _login_page("Usuario o contraseña incorrectos"))
                return
            tok = _new_sess(user)
            self.send_response(302)
            self.send_header("Location", f"{BP}/")
            self.send_header("Set-Cookie", f"nd_sess={tok}; Path={BP or '/'}; HttpOnly")
            self.end_headers()
            return

        sess = _get_sess(self)
        if not sess:
            self._json(401, {"error": "Unauthorized"})
            return

        # ── projects ──
        if rel == "/api/projects":
            name = (data.get("name") or "").strip()
            client = (data.get("client") or "").strip()
            if not name or not client:
                self._json(400, {"error": "Nombre y cliente requeridos"})
                return
            pid = run("""
                INSERT INTO projects (name,client,description,status,priority,address,
                  start_date,due_date,assigned_to,created_by,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
            """, (name, client, data.get("description",""), data.get("status","active"),
                  data.get("priority","normal"), data.get("address",""),
                  data.get("start_date",""), data.get("due_date",""),
                  data.get("assigned_to") or None, sess["id"]))
            self._json(201, {"id": pid})
            return

        # ── tasks ──
        m = re.match(r"^/api/projects/(\d+)/tasks$", rel)
        if m:
            pid = int(m.group(1))
            title = (data.get("title") or "").strip()
            if not title:
                self._json(400, {"error": "Título requerido"})
                return
            tid = run("""
                INSERT INTO tasks (project_id,title,description,status,priority,
                  assigned_to,due_date,created_by,updated_at)
                VALUES (?,?,?,?,?,?,?,?,datetime('now'))
            """, (pid, title, data.get("description",""), data.get("status","pending"),
                  data.get("priority","normal"), data.get("assigned_to") or None,
                  data.get("due_date",""), sess["id"]))
            run("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (pid,))
            self._json(201, {"id": tid})
            return

        # ── materials ──
        if rel == "/api/materials":
            code = (data.get("code") or "").strip()
            name = (data.get("name") or "").strip()
            if not code or not name:
                self._json(400, {"error": "Código y nombre requeridos"})
                return
            existing = q1("SELECT id FROM materials WHERE code=?", (code,))
            if existing:
                self._json(400, {"error": f"Código '{code}' ya existe"})
                return
            mid = run("""
                INSERT INTO materials (code,name,description,unit,stock_warehouse,
                  stock_field,stock_min,category,updated_at)
                VALUES (?,?,?,?,?,?,?,?,datetime('now'))
            """, (code, name, data.get("description",""), data.get("unit","ud"),
                  int(data.get("stock_warehouse") or 0), int(data.get("stock_field") or 0),
                  int(data.get("stock_min") or 0), data.get("category","")))
            self._json(201, {"id": mid})
            return

        # ── assignments ──
        m = re.match(r"^/api/projects/(\d+)/assignments$", rel)
        if m:
            pid = int(m.group(1))
            mid = data.get("material_id")
            if not mid:
                self._json(400, {"error": "Material requerido"})
                return
            aid = run("""
                INSERT INTO assignments (project_id,material_id,qty_requested,qty_assigned,
                  qty_consumed,qty_returned,status,notes,created_by,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
            """, (pid, int(mid), int(data.get("qty_requested") or 0),
                  int(data.get("qty_assigned") or 0), int(data.get("qty_consumed") or 0),
                  int(data.get("qty_returned") or 0), data.get("status","requested"),
                  data.get("notes",""), sess["id"]))
            self._json(201, {"id": aid})
            return

        # ── users ──
        if rel == "/api/users":
            if sess.get("role") != "admin":
                self._json(403, {"error": "Forbidden"})
                return
            username = (data.get("username") or "").strip()
            display  = (data.get("display_name") or "").strip()
            pw       = data.get("password","").strip()
            if not username or not display or not pw:
                self._json(400, {"error": "Usuario, nombre y contraseña requeridos"})
                return
            if q1("SELECT id FROM users WHERE username=?", (username,)):
                self._json(400, {"error": "Usuario ya existe"})
                return
            uid = run("INSERT INTO users (username,pw_hash,display_name,role,active) VALUES (?,?,?,?,?)",
                      (username, _hash(pw), display, data.get("role","technician"),
                       1 if data.get("active",1) else 0))
            self._json(201, {"id": uid})
            return

        self._json(404, {"error": "Not found"})

    def do_PUT(self):
        p   = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) else p.path
        data = _body(self)

        sess = _get_sess(self)
        if not sess:
            self._json(401, {"error": "Unauthorized"})
            return

        # ── project ──
        m = re.match(r"^/api/projects/(\d+)$", rel)
        if m:
            pid = int(m.group(1))
            run("""UPDATE projects SET name=?,client=?,description=?,status=?,priority=?,
                   address=?,start_date=?,due_date=?,assigned_to=?,updated_at=datetime('now')
                   WHERE id=?""",
                (data.get("name",""), data.get("client",""), data.get("description",""),
                 data.get("status","active"), data.get("priority","normal"),
                 data.get("address",""), data.get("start_date",""), data.get("due_date",""),
                 data.get("assigned_to") or None, pid))
            self._json(200, {"ok": True})
            return

        # ── task ──
        m = re.match(r"^/api/tasks/(\d+)$", rel)
        if m:
            tid = int(m.group(1))
            task = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if not task:
                self._json(404, {"error": "Not found"})
                return
            completed = ""
            if data.get("status") == "done":
                from datetime import date
                completed = str(date.today())
            run("""UPDATE tasks SET title=?,description=?,status=?,priority=?,
                   assigned_to=?,due_date=?,completed_date=?,updated_at=datetime('now')
                   WHERE id=?""",
                (data.get("title",""), data.get("description",""),
                 data.get("status","pending"), data.get("priority","normal"),
                 data.get("assigned_to") or None, data.get("due_date",""),
                 completed, tid))
            run("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (task["project_id"],))
            self._json(200, {"ok": True})
            return

        # ── material ──
        m = re.match(r"^/api/materials/(\d+)$", rel)
        if m:
            mid = int(m.group(1))
            code = (data.get("code") or "").strip()
            existing = q1("SELECT id FROM materials WHERE code=? AND id!=?", (code, mid))
            if existing:
                self._json(400, {"error": f"Código '{code}' ya existe"})
                return
            run("""UPDATE materials SET code=?,name=?,description=?,unit=?,
                   stock_warehouse=?,stock_field=?,stock_min=?,category=?,updated_at=datetime('now')
                   WHERE id=?""",
                (code, data.get("name",""), data.get("description",""),
                 data.get("unit","ud"), int(data.get("stock_warehouse") or 0),
                 int(data.get("stock_field") or 0), int(data.get("stock_min") or 0),
                 data.get("category",""), mid))
            self._json(200, {"ok": True})
            return

        # ── assignment ──
        m = re.match(r"^/api/assignments/(\d+)$", rel)
        if m:
            aid = int(m.group(1))
            run("""UPDATE assignments SET qty_requested=?,qty_assigned=?,qty_consumed=?,
                   qty_returned=?,status=?,notes=?,updated_at=datetime('now') WHERE id=?""",
                (int(data.get("qty_requested") or 0), int(data.get("qty_assigned") or 0),
                 int(data.get("qty_consumed") or 0), int(data.get("qty_returned") or 0),
                 data.get("status","requested"), data.get("notes",""), aid))
            self._json(200, {"ok": True})
            return

        # ── user ──
        m = re.match(r"^/api/users/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin":
                self._json(403, {"error": "Forbidden"})
                return
            uid = int(m.group(1))
            run("""UPDATE users SET display_name=?,username=?,role=?,active=? WHERE id=?""",
                (data.get("display_name",""), data.get("username",""),
                 data.get("role","technician"), 1 if data.get("active",1) else 0, uid))
            if data.get("password"):
                run("UPDATE users SET pw_hash=? WHERE id=?", (_hash(data["password"]), uid))
            self._json(200, {"ok": True})
            return

        self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        p   = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) else p.path

        sess = _get_sess(self)
        if not sess:
            self._json(401, {"error": "Unauthorized"})
            return

        m = re.match(r"^/api/projects/(\d+)$", rel)
        if m:
            run("DELETE FROM projects WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok": True})
            return

        m = re.match(r"^/api/tasks/(\d+)$", rel)
        if m:
            run("DELETE FROM tasks WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok": True})
            return

        m = re.match(r"^/api/materials/(\d+)$", rel)
        if m:
            mid = int(m.group(1))
            used = q1("SELECT id FROM assignments WHERE material_id=? LIMIT 1", (mid,))
            if used:
                self._json(400, {"error": "Material en uso, no se puede eliminar"})
                return
            run("DELETE FROM materials WHERE id=?", (mid,))
            self._json(200, {"ok": True})
            return

        m = re.match(r"^/api/users/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin":
                self._json(403, {"error": "Forbidden"})
                return
            uid = int(m.group(1))
            if uid == sess["id"]:
                self._json(400, {"error": "No puedes eliminar tu propio usuario"})
                return
            run("DELETE FROM users WHERE id=?", (uid,))
            self._json(200, {"ok": True})
            return

        self._json(404, {"error": "Not found"})

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"NuvoDesk → http://localhost:{PORT}{BP}/  (admin/admin)")
    server.serve_forever()
