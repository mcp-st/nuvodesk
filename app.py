#!/usr/bin/env python3
"""NuvoDesk v3 — Nuvolink field project & materials management."""

import os, json, sqlite3, re, calendar as _cal, mimetypes, secrets, base64, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote_plus
from datetime import datetime, date as _date, timedelta

_login_fails: dict = {}   # {username: {"count": int, "locked_until": float}}
_LOCKOUT_THRESHOLD = 5    # intentos fallidos antes de bloquear
_LOCKOUT_SECONDS   = 300  # 5 minutos de bloqueo
_BLOCKED_EXTS = {         # extensiones ejecutables bloqueadas en uploads
    ".php", ".py", ".sh", ".rb", ".pl", ".asp", ".aspx",
    ".jsp", ".cgi", ".exe", ".bat", ".cmd", ".ps1",
    ".htaccess", ".htpasswd",
}

from core.db import (
    PORT, BP, DATA_DIR, DB_PATH, FILES_DIR,
    new_sess as _new_sess, get_sess as _get_sess, del_sess as _del_sess,
    db, q, q1, run, rs, r2d, _dblock,
)
from core.helpers import (
    _hash, _check_pw, _esc, _jattr, _now, _fmt_size,
    _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _badge2, _pbadge, _kpi_card,
    _sla_badge,
)

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
CREATE TABLE IF NOT EXISTS project_kit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    added_by    INTEGER REFERENCES users(id),
    category    TEXT NOT NULL DEFAULT 'other',
    item_name   TEXT NOT NULL,
    quantity    TEXT NOT NULL DEFAULT '1',
    unit        TEXT NOT NULL DEFAULT 'uds',
    notes       TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS task_photos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    uploaded_by   INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    url        TEXT DEFAULT '',
    read       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notif_rules (
    event_key       TEXT PRIMARY KEY,
    label           TEXT NOT NULL DEFAULT '',
    notify_internal INTEGER NOT NULL DEFAULT 1,
    notify_email    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS project_audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    field      TEXT NOT NULL,
    old_value  TEXT DEFAULT '',
    new_value  TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    "ALTER TABLE project_logs ADD COLUMN technicians INTEGER DEFAULT 1",
    "ALTER TABLE projects ADD COLUMN lat REAL DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN lng REAL DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN show_in_planning INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN last_name TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN extension TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN reset_token TEXT DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN reset_token_expiry TEXT DEFAULT NULL",
    """CREATE TABLE IF NOT EXISTS activities (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        activity_date TEXT NOT NULL,
        all_day       INTEGER NOT NULL DEFAULT 0,
        hour_start    INTEGER,
        hour_end      INTEGER,
        type          TEXT NOT NULL DEFAULT 'physical',
        notes         TEXT DEFAULT '',
        created_by    INTEGER REFERENCES users(id),
        created_at    TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS tech_availability (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        avail_date  TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'available',
        notes       TEXT DEFAULT '',
        UNIQUE(user_id, avail_date)
    )""",
    """CREATE TABLE IF NOT EXISTS work_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        log_date    TEXT NOT NULL,
        hours       REAL NOT NULL,
        description TEXT DEFAULT '',
        activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
        created_by  INTEGER REFERENCES users(id),
        created_at  TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS change_requests (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id    INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
        requester_id   INTEGER NOT NULL REFERENCES users(id),
        admin_id       INTEGER NOT NULL REFERENCES users(id),
        type           TEXT NOT NULL,
        message        TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'pending',
        admin_response TEXT DEFAULT '',
        created_at     TEXT DEFAULT (datetime('now')),
        resolved_at    TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS warehouse_locations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        code        TEXT NOT NULL UNIQUE,
        name        TEXT NOT NULL,
        warehouse   TEXT NOT NULL DEFAULT 'Almacén Principal',
        description TEXT DEFAULT '',
        active      INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS stock_by_location (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
        location_id INTEGER NOT NULL REFERENCES warehouse_locations(id),
        qty         INTEGER NOT NULL DEFAULT 0,
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(material_id, location_id)
    )""",
    "ALTER TABLE stock_movements ADD COLUMN location_id INTEGER DEFAULT NULL REFERENCES warehouse_locations(id)",
    # Recurrencia en proyectos
    "ALTER TABLE projects ADD COLUMN recurrence TEXT DEFAULT 'none'",
    "ALTER TABLE projects ADD COLUMN recurrence_parent_id INTEGER DEFAULT NULL",
    # Costes para rentabilidad
    "ALTER TABLE materials ADD COLUMN unit_cost REAL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN labor_rate REAL DEFAULT 0",
    # SLA objetivo por proyecto
    "ALTER TABLE projects ADD COLUMN sla_hours REAL DEFAULT 0",
    # Inventario técnico (material en campo por técnico)
    """CREATE TABLE IF NOT EXISTS tech_inventory (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
        qty         REAL NOT NULL DEFAULT 0,
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user_id, material_id)
    )""",
    # Certificaciones de técnicos
    """CREATE TABLE IF NOT EXISTS user_certifications (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        cert_name   TEXT NOT NULL,
        cert_code   TEXT DEFAULT '',
        issued_date TEXT DEFAULT '',
        expires_date TEXT DEFAULT '',
        notes       TEXT DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    # Gantt: fecha de inicio por tarea
    "ALTER TABLE tasks ADD COLUMN start_date TEXT DEFAULT ''",
    # Comentarios por tarea (hilo de discusión individual)
    """CREATE TABLE IF NOT EXISTS task_comments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        body        TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    # Dependencias entre tareas (A bloquea a B)
    """CREATE TABLE IF NOT EXISTS task_dependencies (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        depends_on INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(task_id, depends_on)
    )""",
    # Plantillas de proyecto reutilizables
    """CREATE TABLE IF NOT EXISTS project_templates (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        description     TEXT DEFAULT '',
        work_type       TEXT DEFAULT 'proyecto',
        estimated_hours REAL DEFAULT 0,
        tasks_json      TEXT DEFAULT '[]',
        created_by      INTEGER REFERENCES users(id),
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
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
        # Seed default location and migrate existing stock_warehouse values
        if db().execute("SELECT COUNT(*) FROM warehouse_locations").fetchone()[0] == 0:
            db().execute(
                "INSERT INTO warehouse_locations (code,name,warehouse,description) VALUES (?,?,?,?)",
                ("SIN-UBICAR", "Sin ubicar", "Almacén Principal",
                 "Ubicación por defecto — stock pendiente de clasificar"))
            db().commit()
        default_loc = db().execute(
            "SELECT id FROM warehouse_locations ORDER BY id LIMIT 1").fetchone()
        if default_loc:
            lid = default_loc[0]
            for mid, wh in db().execute(
                    "SELECT id,stock_warehouse FROM materials WHERE stock_warehouse>0").fetchall():
                db().execute(
                    "INSERT OR IGNORE INTO stock_by_location (material_id,location_id,qty) VALUES (?,?,?)",
                    (mid, lid, wh))
            db().commit()

        if db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            db().execute(
                "INSERT INTO users (username,pw_hash,display_name,role) VALUES (?,?,?,?)",
                ("admin", _hash("admin"), "Administrador", "admin"))
            db().commit()
        _default_rules = [
            ("project_assigned",  "Proyecto asignado a técnico",           1, 0),
            ("project_due_soon",  "Proyecto próximo a vencer",             1, 0),
            ("task_overdue",      "Tarea vencida sin completar",           1, 0),
            ("stock_low",         "Material por debajo del stock mínimo",  1, 0),
            ("project_completed", "Proyecto marcado como completado",      0, 0),
        ]
        for _ek, _lbl, _ni, _ne in _default_rules:
            db().execute(
                "INSERT OR IGNORE INTO notif_rules (event_key,label,notify_internal,notify_email) VALUES(?,?,?,?)",
                (_ek, _lbl, _ni, _ne))
        db().commit()


# ── geocoding helper ──────────────────────────────────────────────────────────
import urllib.request as _ureq, urllib.parse as _uparse

def _geocode_address(address):
    """Returns (lat, lng) floats or (None, None) on failure."""
    try:
        url = ("https://nominatim.openstreetmap.org/search?q="
               + _uparse.quote(address) + "&format=json&limit=1")
        req = _ureq.Request(url, headers={
            "User-Agent": "NuvoDesk/1.0 (mcodony@gmail.com)",
            "Accept": "application/json",
        })
        with _ureq.urlopen(req, timeout=6) as r:
            data = json.loads(r.read())
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None

# ── shell ─────────────────────────────────────────────────────────────────────

from web.layout import _NAV_ICONS, _shell
from core.notify import _notify, send_email, get_setting, set_setting
from web.pages.misc import _login_page, _download_page, _set_password_page
from web.pages.dashboard import _dashboard
from web.pages.projects import _projects_page, _build_kanban, _build_file_grid
from web.pages.field import _field_page
from web.pages.clients import _clients_page, _client_detail
def _project_detail(user, pid):
    p = r2d(q1("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to WHERE p.id=?""", (pid,)))
    if not p: return None

    tasks = rs(q("""SELECT t.*,
        (SELECT COUNT(*) FROM task_checklist c WHERE c.task_id=t.id) cl_t,
        (SELECT COUNT(*) FROM task_checklist c WHERE c.task_id=t.id AND c.done=1) cl_d,
        (SELECT COUNT(*) FROM task_photos tp WHERE tp.task_id=t.id) photo_count,
        (SELECT COUNT(*) FROM task_comments tc WHERE tc.task_id=t.id) comment_count,
        (SELECT GROUP_CONCAT(dt.title,'|') FROM task_dependencies td
         JOIN tasks dt ON dt.id=td.depends_on WHERE td.task_id=t.id) dep_names
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

    all_users = rs(q("SELECT id,display_name,role FROM users WHERE active=1 AND show_in_planning=1 ORDER BY display_name"))
    user_opts = "".join(
        f'<option value="{u["id"]}">{_esc(u["display_name"])}</option>' for u in all_users)

    pfiles = rs(q("""SELECT * FROM project_files WHERE project_id=? ORDER BY created_at DESC""", (pid,)))

    # ── new: work logs, comments, extras, equipment ──
    work_logs_all = rs(q("""SELECT wl.*,u.display_name uname
        FROM work_logs wl JOIN users u ON u.id=wl.user_id
        WHERE wl.project_id=? ORDER BY wl.log_date DESC, wl.created_at DESC LIMIT 100""", (pid,)))

    wl_summary = rs(q("""SELECT u.display_name uname,
        COUNT(*) entries, COUNT(DISTINCT wl.log_date) days,
        COALESCE(SUM(wl.hours),0) total_hours
        FROM work_logs wl JOIN users u ON u.id=wl.user_id
        WHERE wl.project_id=?
        GROUP BY wl.user_id ORDER BY total_hours DESC""", (pid,)))

    comments = rs(q("""SELECT wc.*,u.display_name uname
        FROM wo_comments wc JOIN users u ON u.id=wc.user_id
        WHERE wc.project_id=? ORDER BY wc.created_at ASC""", (pid,)))

    extras = rs(q("""SELECT we.*,u.display_name uname
        FROM wo_extras we LEFT JOIN users u ON u.id=we.added_by
        WHERE we.project_id=? ORDER BY we.created_at DESC""", (pid,)))

    equipment = rs(q("""SELECT ei.*,u.display_name uname
        FROM equipment_items ei LEFT JOIN users u ON u.id=ei.added_by
        WHERE ei.project_id=? ORDER BY ei.created_at DESC""", (pid,)))

    kit_recs = rs(q("""SELECT pk.*,u.display_name uname
        FROM project_kit pk LEFT JOIN users u ON u.id=pk.added_by
        WHERE pk.project_id=? ORDER BY pk.created_at DESC""", (pid,)))
    kit_pending_count = sum(1 for kr in kit_recs if kr.get('status', 'pending') == 'pending')

    mats = rs(q("SELECT id,code,name,unit,stock_warehouse,stock_min FROM materials ORDER BY name"))
    mat_opts = "".join(
        f'<option value="{m["id"]}" data-stock="{m["stock_warehouse"]}" data-stockmin="{m["stock_min"] or 0}">'
        f'[{_esc(m["code"])}] {_esc(m["name"])} ({_esc(m["unit"])})</option>'
        for m in mats)

    # ── task rows ──
    t_rows = ""
    for t in tasks:
        cl_pct = int(t['cl_d']/t['cl_t']*100) if t['cl_t'] else -1
        cl_html = ""
        if t['cl_t'] > 0:
            cl_html = (f'<div class="progress" style="width:50px;display:inline-block;vertical-align:middle;margin-left:6px">'
                       f'<div class="progress-bar" style="width:{cl_pct}%"></div></div>'
                       f'<span class="muted" style="font-size:.7rem"> {t["cl_d"]}/{t["cl_t"]}</span>')
        done_btn_style = 'background:var(--green);color:#fff' if t['status']=='done' else ''
        t_crit = ' class="nd-crit"' if t['status'] == 'blocked' else ''
        cm_count = t.get('comment_count') or 0
        cm_style = 'color:var(--primary);font-weight:600' if cm_count else 'opacity:.4'
        cm_lbl = f'💬{cm_count}' if cm_count else '💬'
        dep_html = ""
        dep_names_raw = t.get('dep_names') or ""
        if dep_names_raw:
            dep_parts = [_esc(d[:35]) for d in dep_names_raw.split('|') if d]
            dep_html = f'<br><span style="font-size:.7rem;color:var(--s-warn)">🔗 {", ".join(dep_parts)}</span>'
        safe_t = {k: v for k, v in dict(t).items() if isinstance(v, (str, int, float, type(None)))}
        t_rows += (f'<tr{t_crit}><td>'
            f'<button class="btn btn-ghost btn-icon" style="{done_btn_style}" '
            f'onclick="toggleTask({t["id"]},{json.dumps(t["status"])})" title="Toggle estado">✓</button></td>'
            f'<td><span class="fw7">{_esc(t["title"])}</span>{cl_html}'
            f'{dep_html}'
            f'{"<br><span class=muted style=font-size:.75rem>"+_esc(t["description"])+"</span>" if t.get("description") else ""}</td>'
            f'<td>{_badge2(t["status"])}</td>'
            f'<td class="col-m-hide">{_pbadge(t["priority"])}</td>'
            f'<td class="muted col-m-hide">{_esc((t["due_date"] or "—")[:10])}</td>'
            f'<td style="white-space:nowrap">'
            f'<button class="btn btn-ghost btn-icon" style="{cm_style};font-size:.78rem" '
            f'onclick="openTaskComments({t["id"]},{json.dumps(t["title"])})" title="Comentarios">{cm_lbl}</button>'
            f'<button class="btn btn-ghost btn-icon" onclick="openChecklist({t["id"]},{json.dumps(t["title"])})" title="Checklist">☑</button>'
            f'<div class="nd-ovfl-wrap" style="display:inline-block">'
            f'<button class="btn btn-ghost btn-icon" onclick="ndOverflow(this)" title="Más opciones">⋯</button>'
            f'<div class="nd-ovfl-drop">'
            f'<button class="nd-ovfl-item" onclick="openTaskComments({t["id"]},{json.dumps(t["title"])})">💬 Comentarios</button>'
            f'<button class="nd-ovfl-item" onclick="openTaskPhotos({t["id"]},{json.dumps(t["title"])})">📷 Fotos</button>'
            f'<button class="nd-ovfl-item" onclick="editTask({json.dumps(safe_t)})">✏️ Editar</button>'
            f'<button class="nd-ovfl-item danger" onclick="delTask({t["id"]})">✕ Eliminar</button>'
            f'</div></div>'
            f'</td></tr>')

    # ── assignment rows ──
    a_rows = ""
    for a in assignments:
        a_rows += (f'<tr><td><span class="chip">{_esc(a["mat_code"])}</span> {_esc(a["mat_name"])}</td>'
            f'<td style="text-align:center">{a["qty_requested"]}</td>'
            f'<td style="text-align:center">{a["qty_assigned"]}</td>'
            f'<td style="text-align:center">{a["qty_consumed"]}</td>'
            f'<td style="text-align:center">{a["qty_returned"]}</td>'
            f'<td>{_badge2(a["status"])}</td>'
            f'<td class="muted col-m-hide">{_esc(a["mat_unit"])}</td>'
            f'<td><button class="btn btn-ghost btn-icon" onclick="updateAssign({a["id"]},{json.dumps(dict(a))})">⚙️</button></td></tr>')

    # ── work log ──
    log_items = ""
    for l in logs:
        initials = "".join(w[0].upper() for w in l['uname'].split()[:2])
        techs = int(l.get('technicians') or 1)
        ph = (l['hours'] or 0) * techs
        if l['hours']:
            h_badge = f'<span class="tl-hours">{l["hours"]}h'
            if techs > 1:
                h_badge += f' × {techs} = <strong>{ph:.1f} ph</strong>'
            h_badge += '</span>'
        else:
            h_badge = ""
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

    desc_html = f'<p style="color:var(--muted);margin-bottom:16px;line-height:1.6">{_esc(p["description"])}</p>' if p.get('description') else ''

    # info tab content
    audit_rows = rs(q("""SELECT pa.*,u.display_name uname FROM project_audit pa
        JOIN users u ON u.id=pa.user_id WHERE pa.project_id=?
        ORDER BY pa.created_at DESC LIMIT 50""", (pid,)))

    _STATUS_LBL = {"active":"Activo","paused":"Pausado","completed":"Completado","cancelled":"Cancelado"}
    _PRI_LBL    = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}
    def _audit_val(field, val):
        if field == "status":   return _STATUS_LBL.get(val, val)
        if field == "priority": return _PRI_LBL.get(val, val)
        if field == "assigned_to":
            if not val or val == "None": return "Sin asignar"
            u = r2d(q1("SELECT display_name FROM users WHERE id=?", (int(val),)))
            return u["display_name"] if u else val
        return val or "—"
    _FIELD_LBL = {"status":"Estado","priority":"Prioridad","assigned_to":"Técnico","due_date":"Fecha límite"}

    audit_html = ""
    if audit_rows:
        items = ""
        for a in audit_rows:
            flbl = _FIELD_LBL.get(a["field"], a["field"])
            items += (f'<li style="padding:8px 0;border-bottom:1px solid var(--border);font-size:.82rem">'
                f'<span class="muted">{_esc(a["created_at"][:16])}</span>'
                f' · <strong>{_esc(a["uname"])}</strong> cambió <em>{flbl}</em>'
                f': <span class="muted">{_esc(_audit_val(a["field"],a["old_value"]))}</span>'
                f' → <strong>{_esc(_audit_val(a["field"],a["new_value"]))}</strong></li>')
        audit_html = f'<ul style="list-style:none;padding:0;margin:0">{items}</ul>'

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
    ph_row = q1("SELECT COALESCE(SUM(hours),0), COALESCE(SUM(hours*technicians),0) FROM project_logs WHERE project_id=?", (pid,))
    h_logged = ph_row[0] if ph_row else 0
    ph_logged = ph_row[1] if ph_row else 0
    h_est = p.get("estimated_hours") or 0
    h_pct = min(100, int(ph_logged/h_est*100)) if h_est else 0
    hours_html = ""
    if h_est or ph_logged:
        trend = f"{h_pct}% de {h_est}h estimadas" if h_est else ""
        ph_label = f"Horas registradas" + (f" · {ph_logged:.1f} person-h" if ph_logged != h_logged else "")
        hours_html = (
            '<div class="nd-kpi-strip" style="margin-bottom:16px">'
            + _kpi_card(f"{h_logged}h", ph_label, "brand" if h_pct < 100 else "warn", "⏱", trend)
            + (f'<div class="nd-kpi" style="flex:1;min-width:180px"><div class="nd-kpi-lbl" style="margin-bottom:6px">Progreso horas</div>'
               f'<div class="progress" style="height:8px"><div class="progress-bar" style="width:{h_pct}%"></div></div>'
               f'<div class="nd-kpi-trend">{h_pct}%</div></div>' if h_est else "")
            + '</div>'
        )

    # ── build time tab HTML ──
    wl_summary_html = ""
    for ts in wl_summary:
        wl_summary_html += (f'<div class="time-card">'
            f'<div class="tc-name">{_esc(ts["uname"])}</div>'
            f'<div class="tc-hours">{ts["total_hours"]:.1f}h</div>'
            f'<div class="tc-detail">{ts["days"]} días · {ts["entries"]} registros</div>'
            f'</div>')

    wl_rows = ""
    for wl in work_logs_all:
        can_del = (wl['user_id'] == user['id'] or user.get('role') == 'admin')
        del_btn = f'<button class="btn btn-danger btn-icon" onclick="delWorkLog({wl["id"]})">✕</button>' if can_del else ''
        wl_rows += (f'<tr>'
            f'<td class="muted" style="font-size:.75rem;white-space:nowrap">{_esc(wl["log_date"])}</td>'
            f'<td>{_esc(wl["uname"])}</td>'
            f'<td style="font-weight:700">{wl["hours"]}h</td>'
            f'<td class="muted col-m-hide" style="font-size:.8rem">{_esc(wl.get("description","") or "")}</td>'
            f'<td>{del_btn}</td></tr>')

    today_str = _date.today().isoformat()
    all_users_wl = rs(q("SELECT id,display_name FROM users WHERE active=1 AND role!='backoffice' ORDER BY display_name"))
    user_opts_wl = "".join(f'<option value="{u["id"]}">{_esc(u["display_name"])}</option>' for u in all_users_wl)
    time_tab_html = f"""
<div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-bottom:16px">
  {f'<div class="field" style="margin:0"><label>Técnico</label><select id="wl-user">{user_opts_wl}</select></div>' if user.get("role")=="admin" else ""}
  <div class="field" style="margin:0;flex:0 0 140px">
    <label>Fecha</label>
    <input type="date" id="wl-date" value="{today_str}">
  </div>
  <div class="field" style="margin:0;flex:0 0 90px">
    <label>Horas</label>
    <input type="number" id="wl-hours" min="0.25" max="24" step="0.25" value="1">
  </div>
  <div class="field" style="margin:0;flex:1;min-width:140px">
    <label>Descripción</label>
    <input id="wl-desc" placeholder="Qué se hizo...">
  </div>
  <button class="btn btn-primary btn-sm" onclick="addWorkLog()">+ Registrar</button>
</div>
<div class="time-summary-grid">{wl_summary_html or '<p class="muted" style="grid-column:1/-1;text-align:center;padding:20px">Sin horas registradas todavía</p>'}</div>
<div class="card">
  <h3 style="margin-bottom:12px">Horas registradas</h3>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Fecha</th><th>Técnico</th><th>Horas</th>
    <th class="col-m-hide">Descripción</th><th></th>
  </tr></thead><tbody>{wl_rows or "<tr><td colspan='5' class='muted' style='text-align:center;padding:16px'>Sin registros</td></tr>"}</tbody></table></div>
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

    timer_banner_html = ""

    # ── kit recommendations tab ──
    _KIT_CATS = {
        "sfp_10g":("SFP 10G","rc-sfp10g"), "sfp_1g":("SFP 1G","rc-sfp1g"),
        "glc":("GLC/SFP","rc-glc"), "fiber_patch":("Fibra óptica","rc-fiber"),
        "patchcord_rj45":("Patch RJ45","rc-patchrj45"), "cisco_cable":("Cable Cisco","rc-cisco"),
        "stack_cable":("Cable STACK","rc-stack"), "poe_injector":("Inyector POE","rc-poe"),
        "other":("Otro","rc-other"),
    }
    _KIT_ST = {
        "pending":("⏳ Pendiente","rec-status-pending"),
        "brought":("✅ Llevado","rec-status-brought"),
        "not_needed":("— No necesario","rec-status-not_needed"),
    }
    kit_rows_html = ""
    for kr in kit_recs:
        cat_lbl, cat_cls = _KIT_CATS.get(kr.get("category","other"), ("Otro","rc-other"))
        st_lbl, st_cls = _KIT_ST.get(kr.get("status","pending"), ("⏳ Pendiente","rec-status-pending"))
        added_by_txt = f'por {_esc(kr.get("uname") or "?")}' if kr.get("uname") else ""
        notes_txt = f' · {_esc(kr["notes"])}' if kr.get("notes") else ""
        qty_unit = f'{_esc(str(kr["quantity"]))} {_esc(kr["unit"])}'
        krid = kr["id"]
        status_val = kr.get("status","pending")
        toggle_btn = ""
        if status_val == "pending":
            toggle_btn = (f'<button class="btn btn-ghost btn-icon" title="Marcar como llevado" '
                f'onclick="kitSetStatus({krid},\'brought\')">✅</button>'
                f'<button class="btn btn-ghost btn-icon" title="No necesario" '
                f'onclick="kitSetStatus({krid},\'not_needed\')">✗</button>')
        elif status_val in ("brought","not_needed"):
            toggle_btn = (f'<button class="btn btn-ghost btn-icon" title="Volver a pendiente" '
                f'onclick="kitSetStatus({krid},\'pending\')">↩</button>')
        kit_rows_html += (
            f'<div class="rec-item">'
            f'<div style="padding-top:3px"><span class="rec-cat {cat_cls}">{cat_lbl}</span></div>'
            f'<div class="ri-main">'
            f'<div class="ri-name">{_esc(kr["item_name"])}</div>'
            f'<div class="ri-meta">{qty_unit}{notes_txt} {added_by_txt}</div>'
            f'</div>'
            f'<div class="ri-actions">'
            f'<span class="{st_cls}">{st_lbl}</span>'
            f'{toggle_btn}'
            f'<button class="btn btn-danger btn-icon" onclick="delKitRec({krid})">✕</button>'
            f'</div></div>')
    kit_tab_html = f"""
<div class="toolbar" style="margin-bottom:12px">
  <h2>🧰 Maletín de obra</h2>
  <button class="btn btn-primary btn-sm" onclick="openKitRecModal()">+ Añadir</button>
</div>
<p class="muted" style="font-size:.82rem;margin-bottom:16px;line-height:1.5">
  Material que el equipo de campo debería llevar para esta intervención.
  Sin movimiento de almacén — es una lista de preparación.
</p>
<div class="card">
{kit_rows_html if kit_rows_html else "<p class='muted' style='text-align:center;padding:24px'>Sin items en el maletín — añade el primero.</p>"}
</div>"""

    task_done = len([t for t in tasks if t['status'] == 'done'])
    task_total = len(tasks)
    task_pct = int(task_done / task_total * 100) if task_total else 0
    total_hours = sum(wl.get('hours') or 0 for wl in work_logs_all)
    total_hours_fmt = f"{total_hours:.1f}h" if total_hours else "0h"
    safe_proj = {k: v for k, v in p.items() if isinstance(v, (str, int, float, type(None)))}
    # JS data for Gantt and task deps
    all_tasks_js = json.dumps([{
        "id": t["id"], "title": t.get("title",""),
        "description": t.get("description","") or "",
        "status": t.get("status","pending"),
        "priority": t.get("priority","normal"),
        "due_date": t.get("due_date","") or "",
        "start_date": t.get("start_date","") or "",
        "created_at": (t.get("created_at","") or "")[:10],
    } for t in tasks], ensure_ascii=False)
    task_dep_opts = "".join(
        f'<option value="{t["id"]}">{_esc(t["title"][:60])}</option>' for t in tasks)
    content = f"""
<div style="margin-bottom:8px"><a href="{BP}/projects" class="muted" style="font-size:.85rem">← Proyectos</a></div>

<div class="proj-hd">
  <div class="proj-hd-top">
    <div class="proj-hd-info">
      <div class="proj-hd-title">
        {_wt_badge(p.get('work_type') or 'proyecto')}
        <h1>{_esc(p["name"])}</h1>
        <span class="muted" style="font-size:.85rem">{_esc(p["client"])}</span>
        {('&nbsp;<span class="chip">#'+_esc(p["reference"])+'</span>') if p.get("reference") else ""}
      </div>
      <div class="proj-hd-meta">
        {_badge2(p["status"])}
        {_pbadge(p["priority"])}
        {'<span class="muted" style="font-size:.8rem">📅 '+_esc((p["due_date"] or "")[:10])+'</span>' if p.get("due_date") else ""}
        {_sla_badge(p)}
        {'<span class="chip" style="font-size:.72rem">🔄 '+{"monthly":"Mensual","quarterly":"Trimestral","biannual":"Semestral","annual":"Anual"}.get(p.get("recurrence","none"),"")+'</span>' if p.get("recurrence","none") not in ("none","","None",None) else ""}
      </div>
      {('<div class="avatar-row" style="margin-top:8px">'+member_avatars+'</div>') if member_avatars else ""}
    </div>
    <div class="proj-hd-actions">
      <a href="{BP}/projects/{pid}/report" target="_blank" class="btn btn-ghost btn-sm">🖨 Informe</a>
      <a href="{BP}/projects/{pid}/parte" target="_blank" class="btn btn-ghost btn-sm">📄 Parte</a>
      <a href="{BP}/projects/{pid}/albaran" target="_blank" class="btn btn-ghost btn-sm">🧾 Albarán</a>
      <button class="btn btn-ghost btn-sm" onclick="openSigModal()">✍️ Firma</button>
      <button class="btn btn-ghost btn-sm" onclick="showSaveTemplateModal()">💾 Plantilla</button>
      <button class="btn btn-ghost btn-sm" onclick="editProject({_jattr(safe_proj)})">✏️ Editar</button>
    </div>
  </div>
  {('<div style="margin:10px 0 0;padding-top:10px;border-top:1px solid var(--border);font-size:.875rem;color:var(--muted);line-height:1.6">'+_esc(p["description"])+'</div>') if p.get("description") else ""}
  <div class="proj-hd-kpis">
    <div class="proj-hd-kpi">
      <div class="v">{task_done}/{task_total}</div>
      <div class="l">Tareas</div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-start;gap:4px;min-width:100px">
      <div class="progress" style="width:100px"><div class="progress-bar" style="width:{task_pct}%"></div></div>
      <div style="font-size:.7rem;color:var(--muted)">{task_pct}% completado</div>
    </div>
    <div class="proj-hd-kpi">
      <div class="v">{total_hours_fmt}</div>
      <div class="l">Horas totales</div>
    </div>
    <div style="margin-left:auto">
    </div>
  </div>
</div>


<div class="tabs" style="overflow-x:auto">
  <button class="tab-btn active" onclick="showTab('trabajo',this)">Trabajo</button>
  <button class="tab-btn" onclick="showTab('recursos',this)">Recursos</button>
  <button class="tab-btn" onclick="showTab('cierre',this)">Cierre</button>
</div>

<!-- TAB TRABAJO -->
<div id="tab-trabajo" class="tab-pane active">
<div class="trabajo-grid">

<div class="trabajo-main">
<div class="card" style="padding:0;overflow:hidden">
<div class="toolbar" style="padding:16px 16px 12px">
  <div style="display:flex;align-items:center;gap:10px">
    <h2 style="margin:0">Tareas ({len(tasks)})</h2>
    <div class="view-toggle" id="task-view-toggle">
      <button class="active" id="vbtn-kanban" onclick="setTaskView('kanban')">⊞ Kanban</button>
      <button id="vbtn-list" onclick="setTaskView('list')">☰ Lista</button>
      <button id="vbtn-gantt" onclick="setTaskView('gantt')">📊 Gantt</button>
    </div>
  </div>
  <button class="btn btn-primary btn-sm" onclick="openNewTask()">+ Tarea</button>
</div>
<div id="tasks-kanban" style="padding:0 16px 16px">
{_build_kanban(tasks, pid)}
</div>
<div id="tasks-list" style="display:none;padding:0 16px 16px">
<div class="tbl-wrap"><table><thead><tr>
  <th style="width:40px"></th><th>Tarea</th><th>Estado</th>
  <th class="col-m-hide">Prioridad</th><th class="col-m-hide">Vencimiento</th><th></th>
</tr></thead><tbody>{t_rows or "<tr><td colspan='6' class='muted' style='text-align:center;padding:20px'>Sin tareas</td></tr>"}</tbody></table></div>
</div>
<div id="tasks-gantt" style="display:none;padding:0 16px 16px;overflow-x:auto">
  <div id="gantt-svg-wrap" style="min-width:500px"></div>
</div>
</div>
</div>

<div class="trabajo-side">
<div class="comment-section">
  <h3 style="margin-bottom:14px;font-size:.95rem;font-weight:700">💬 Seguimiento del proyecto ({len(comments)})</h3>
  {comments_tab_html}
</div>
</div>

</div>
</div>

<!-- TAB RECURSOS -->
<div id="tab-recursos" class="tab-pane">

<div class="card">
  <div class="toolbar" style="margin-bottom:12px"><h2>📁 Archivos ({len(pfiles)})</h2></div>
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

{kit_tab_html}

{extras_tab_html}

<div class="card">
  <div class="toolbar" style="margin-bottom:12px">
    <h3>Materiales asignados ({len(assignments)})</h3>
    <button class="btn btn-primary btn-sm" onclick="openNewAssign()">+ Material</button>
  </div>
  <div class="tbl-wrap"><table><thead><tr>
    <th>Material</th><th style="text-align:center">Solicitado</th>
    <th style="text-align:center">Asignado</th><th style="text-align:center">Consumido</th>
    <th style="text-align:center">Devuelto</th><th>Estado</th>
    <th class="col-m-hide">Ud</th><th></th>
  </tr></thead><tbody>{a_rows or "<tr><td colspan='8' class='muted' style='text-align:center;padding:20px'>Sin materiales asignados</td></tr>"}</tbody></table></div>
</div>

</div>

<!-- TAB CIERRE -->
<div id="tab-cierre" class="tab-pane">

<div class="card">
<div class="toolbar">
  <h2>⏱ Registro de trabajo</h2>
  <span class="muted" style="font-size:.82rem">Registra horas desde la pestaña <strong>Trabajo</strong> →</span>
</div>
{hours_html}
{time_tab_html}
{f"<h3 style='margin:20px 0 8px;font-size:.9rem;font-weight:700;color:var(--muted)'>📋 Diario de obra ({len(logs)} entradas)</h3><ul class='timeline'>{log_items}</ul>" if log_items else ""}
</div>

<div class="card">
<div class="toolbar">
  <h2>👥 Equipo ({len(members)})</h2>
  <button class="btn btn-primary btn-sm" onclick="openAddMember()">+ Añadir persona</button>
</div>
<div class="tbl-wrap"><table><thead><tr>
  <th style="width:36px"></th><th>Técnico</th>
  <th class="col-m-hide">Período</th><th class="col-m-hide">Notas</th><th></th>
</tr></thead><tbody>
  {member_rows or "<tr><td colspan='5' class='muted' style='text-align:center;padding:20px'>Sin personas asignadas al proyecto</td></tr>"}
</tbody></table></div>
<p class="muted" style="font-size:.82rem;padding:12px 0 0">Las personas aquí asignadas aparecen en el calendario de movimientos de personal.</p>
</div>

<div class="card">
  <table><tbody>{info_rows or "<tr><td class='muted'>Sin datos adicionales</td></tr>"}</tbody></table>
</div>
{f'<div class="card"><h3 style="margin-bottom:12px">Historial de cambios</h3>{audit_html}</div>' if audit_html else ""}

</div>

<!-- MODAL kit recomendación -->
<div class="modal-bg" id="kit-rec-modal">
<div class="modal" style="max-width:460px">
  <h2>🧰 Añadir al maletín de obra</h2>
  <div class="form-row single">
    <div><label>Categoría</label>
    <select id="kr-cat">
      <option value="sfp_10g">SFP 10G</option>
      <option value="sfp_1g">SFP 1G</option>
      <option value="glc">GLC / SFP estándar</option>
      <option value="fiber_patch">Patchcord fibra óptica</option>
      <option value="patchcord_rj45">Patchcord RJ45</option>
      <option value="cisco_cable">Cable especial Cisco</option>
      <option value="stack_cable">Cable STACK</option>
      <option value="poe_injector">Inyector POE</option>
      <option value="other">Otro</option>
    </select></div>
  </div>
  <div class="form-row single">
    <div><label>Descripción / modelo</label>
    <input id="kr-name" placeholder="Ej: SFP-10G-SR, GLC-SX-MMD, cable consola Cisco..."></div>
  </div>
  <div class="form-row">
    <div><label>Cantidad</label><input type="text" id="kr-qty" value="1" style="width:80px"></div>
    <div><label>Unidad</label><input id="kr-unit" value="uds" style="width:80px"></div>
  </div>
  <div class="form-row single">
    <div><label>Notas (opcional)</label>
    <input id="kr-notes" placeholder="Contexto, motivo, alternativas..."></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeKitRecModal()">Cancelar</button>
    <button class="btn btn-primary" onclick="doAddKitRec()">Añadir al maletín</button>
  </div>
</div></div>

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
    <div><label>Dirección <button type="button" class="btn btn-ghost btn-icon" style="font-size:.72rem;margin-left:4px;vertical-align:middle" onclick="geocodeProjAddr()" title="Geolocalizar dirección">📍</button></label><input id="f-addr"></div>
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
      <option value="quoted">Presupuestado</option>
      <option value="pending_approval">Pend. firma</option>
      <option value="completed">Completado</option><option value="cancelled">Cancelado</option>
    </select></div>
    <div><label>Recurrencia</label><select id="f-recurrence">
      <option value="none">Sin recurrencia</option>
      <option value="monthly">Mensual</option><option value="quarterly">Trimestral</option>
      <option value="biannual">Semestral</option><option value="annual">Anual</option>
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
  <div class="form-row">
    <div><label>Inicio (Gantt)</label><input type="date" id="t-start"></div>
    <div><label>Fecha límite</label><input type="date" id="t-due"></div>
  </div>
  <div class="form-row single" id="t-deps-row">
    <div><label>Depende de <span class="muted" style="font-weight:400;font-size:.75rem">(bloqueada por estas tareas)</span></label>
    <select id="t-deps" multiple style="height:72px;width:100%;font-size:.82rem">
    {task_dep_opts}
    </select>
    <span class="muted" style="font-size:.72rem">Ctrl+clic para selección múltiple</span>
    </div>
  </div>
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
    <button type="button" class="btn btn-ghost btn-sm" onclick="loadClTemplate()" title="Cargar plantilla según tipo de trabajo">📋 Plantilla</button>
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

<!-- MODAL fotos tarea -->
<div class="modal-bg" id="photo-modal">
<div class="modal" style="max-width:560px">
  <h2 id="photo-modal-title">📷 Fotos</h2>
  <div id="photo-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:8px;margin-bottom:16px;min-height:60px"></div>
  <label style="display:flex;align-items:center;gap:10px;cursor:pointer;background:var(--surface2,var(--surface));border:2px dashed var(--border);border-radius:8px;padding:12px;justify-content:center">
    <input type="file" id="photo-input" accept="image/*" capture="environment" multiple style="display:none" onchange="uploadTaskPhotos(this.files)">
    <span style="font-size:1.5rem">📷</span>
    <span style="font-size:.875rem;color:var(--muted)">Tomar foto o seleccionar imágenes</span>
  </label>
  <div class="modal-foot" style="margin-top:12px">
    <button type="button" class="btn btn-ghost" onclick="closePhotoModal()">Cerrar</button>
  </div>
</div></div>

<!-- MODAL comentarios de tarea -->
<div class="modal-bg" id="tcm-modal">
<div class="modal" style="max-width:480px">
  <h2 id="tcm-title">Comentarios</h2>
  <div id="tcm-list" style="max-height:280px;overflow-y:auto;margin-bottom:12px;border:1px solid var(--border);border-radius:8px;padding:8px"></div>
  <div style="display:flex;gap:8px;align-items:flex-end">
    <textarea id="tcm-body" rows="2" placeholder="Escribe un comentario..." style="flex:1;resize:none"></textarea>
    <button class="btn btn-primary btn-sm" onclick="addTaskComment()">Enviar</button>
  </div>
  <div class="modal-foot" style="margin-top:8px">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('tcm-modal').classList.remove('open')">Cerrar</button>
  </div>
</div></div>

<!-- MODAL guardar como plantilla -->
<div class="modal-bg" id="tpl-save-modal">
<div class="modal" style="max-width:420px">
  <h2>💾 Guardar como plantilla</h2>
  <p class="muted" style="font-size:.82rem;margin-bottom:12px">Guarda este proyecto y sus tareas como plantilla reutilizable.</p>
  <div class="form-row single">
    <div><label>Nombre de la plantilla *</label>
    <input id="tpl-name" placeholder="Ej: Instalación switch Cisco, Mantenimiento red LAN..."></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('tpl-save-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doSaveTemplate()">💾 Guardar</button>
  </div>
</div></div>

<!-- MODAL firma cliente -->
<div class="modal-bg" id="sig-modal">
<div class="modal" style="max-width:500px">
  <h2>✍️ Firma del cliente</h2>
  <p class="muted" style="font-size:.875rem;margin-bottom:12px">El cliente firma en el recuadro para confirmar la entrega del trabajo</p>
  <canvas id="sig-canvas" width="460" height="180"
    style="border:2px solid var(--border);border-radius:8px;touch-action:none;cursor:crosshair;background:#fff;width:100%;max-width:460px;display:block"></canvas>
  <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
    <button class="btn btn-ghost btn-sm" onclick="clearSignature()">Borrar</button>
    <span class="muted" style="font-size:.78rem;align-self:center">Firma con el dedo o ratón</span>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeSigModal()">Cancelar</button>
    <button type="button" class="btn btn-primary" onclick="saveSignature()">Guardar firma</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)}, pid={pid};
var _kitPending={kit_pending_count};
var _projWorkType={json.dumps(p.get('work_type','proyecto'))};
var _clTaskId=null;
var _allTasks={all_tasks_js};
var _allTasksById={{}};
_allTasks.forEach(function(t){{_allTasksById[t.id]=t;}});

// ── tabs ──
function showTab(name,btn){{
  document.querySelectorAll('.tab-pane').forEach(function(p){{p.classList.remove('active');}});
  document.querySelectorAll('.tab-btn').forEach(function(b){{b.classList.remove('active');}});
  document.getElementById('tab-'+name).classList.add('active');
  if(btn) btn.classList.add('active');
  history.replaceState(null,'','#'+name);
}}
(function(){{
  var hash=(location.hash||'').replace('#','');
  var valid=['trabajo','recursos','cierre'];
  if(hash && valid.indexOf(hash)>=0){{
    var pane=document.getElementById('tab-'+hash);
    var btn=document.querySelector('.tab-btn[onclick*="'+hash+'"]');
    if(pane){{
      document.querySelectorAll('.tab-pane').forEach(function(p){{p.classList.remove('active');}});
      document.querySelectorAll('.tab-btn').forEach(function(b){{b.classList.remove('active');}});
      pane.classList.add('active');
      if(btn) btn.classList.add('active');
    }}
  }}
}})();

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
  document.getElementById('f-recurrence').value=p.recurrence||'none';
  document.getElementById('proj-modal').classList.add('open');
}}
function geocodeProjAddr(){{
  var addr=document.getElementById('f-addr').value.trim();
  if(!addr){{Toast.show('Escribe primero una dirección','err');return;}}
  fetch(bp+'/api/geocode?q='+encodeURIComponent(addr))
    .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'No encontrado');}});}})
    .then(function(d){{
      fetch(bp+'/api/projects/{pid}/geocode',{{method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{lat:d.lat,lng:d.lng}})}})
        .then(function(r){{if(r.ok)Toast.show('Ubicación guardada ✓','ok');}});
    }}).catch(function(err){{Toast.show('No se encontró la dirección: '+err.message,'err');}});
}}
function closeProjModal(){{document.getElementById('proj-modal').classList.remove('open');}}
document.getElementById('proj-modal').onclick=function(e){{if(e.target===this)closeProjModal();}};
function _doSaveProject(){{
  fetch(bp+'/api/projects/'+pid,{{method:'PUT',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:document.getElementById('f-name').value,
      reference:document.getElementById('f-ref').value,
      work_type:document.getElementById('f-wtype').value,
      client:document.getElementById('f-client').value,address:document.getElementById('f-addr').value,
      contact_name:document.getElementById('f-cname').value,contact_phone:document.getElementById('f-cphone').value,
      description:document.getElementById('f-desc').value,status:document.getElementById('f-status').value,
      priority:document.getElementById('f-priority').value,start_date:document.getElementById('f-start').value,
      due_date:document.getElementById('f-due').value,estimated_hours:parseFloat(document.getElementById('f-hours').value)||0,
      recurrence:document.getElementById('f-recurrence').value}})
  }}).then(function(r){{if(r.ok)location.reload();}});
}}
document.getElementById('proj-form').onsubmit=function(e){{
  e.preventDefault();
  var newStatus=document.getElementById('f-status').value;
  if(newStatus==='completed'&&_kitPending>0){{
    ConfirmDialog.show('Maletín pendiente',
      'Hay '+_kitPending+' ítem(s) en el maletín sin confirmar como llevados. ¿Cerrar el proyecto igualmente?')
      .then(function(ok){{if(ok)_doSaveProject();}});
    return;
  }}
  _doSaveProject();
}};

// ── task view toggle ──
function setTaskView(v){{
  document.getElementById('tasks-kanban').style.display=v==='kanban'?'':'none';
  document.getElementById('tasks-list').style.display=v==='list'?'':'none';
  document.getElementById('tasks-gantt').style.display=v==='gantt'?'':'none';
  document.getElementById('vbtn-kanban').className=v==='kanban'?'active':'';
  document.getElementById('vbtn-list').className=v==='list'?'active':'';
  document.getElementById('vbtn-gantt').className=v==='gantt'?'active':'';
  localStorage.setItem('nd_task_view_'+pid,v);
  if(v==='gantt') buildGantt();
}}
(function(){{
  var saved=localStorage.getItem('nd_task_view_'+pid);
  if(saved&&saved==='list') setTaskView('list');
  else if(saved&&saved==='gantt') setTaskView('gantt');
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
  document.getElementById('t-start').value='';
  document.getElementById('t-due').value='';
  Array.from(document.getElementById('t-deps').options).forEach(function(o){{o.selected=false;}});
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
  document.getElementById('t-start').value=t.start_date||'';
  document.getElementById('t-due').value=t.due_date||'';
  // load deps for this task
  fetch(bp+'/api/tasks/'+t.id+'/dependencies')
    .then(function(r){{return r.json();}})
    .then(function(deps){{
      var depIds=deps.map(function(d){{return String(d.depends_on);}});
      Array.from(document.getElementById('t-deps').options).forEach(function(o){{
        o.selected=depIds.indexOf(o.value)>=0;
      }});
    }}).catch(function(){{}});
  document.getElementById('task-modal').classList.add('open');
}}
function closeTaskModal(){{document.getElementById('task-modal').classList.remove('open');}}
document.getElementById('task-modal').onclick=function(e){{if(e.target===this)closeTaskModal();}};
document.getElementById('task-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('task-id').value;
  var selDeps=Array.from(document.getElementById('t-deps').selectedOptions).map(function(o){{return parseInt(o.value);}});
  var d={{title:document.getElementById('t-title').value,description:document.getElementById('t-desc').value,
    status:document.getElementById('t-status').value,priority:document.getElementById('t-priority').value,
    start_date:document.getElementById('t-start').value,
    due_date:document.getElementById('t-due').value}};
  var url=id?bp+'/api/tasks/'+id:bp+'/api/projects/'+pid+'/tasks';
  fetch(url,{{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{
      if(!r.ok) return;
      return r.json().then(function(j){{
        var tid=id||j.id;
        if(!tid){{location.reload();return;}}
        // sync dependencies
        return fetch(bp+'/api/tasks/'+tid+'/dependencies',{{method:'POST',
          headers:{{'Content-Type':'application/json'}},
          body:JSON.stringify({{deps:selDeps}})
        }}).then(function(){{location.reload();}});
      }});
    }});
}};
function toggleTask(id,status){{
  var next=status==='done'?'pending':'done';
  fetch(bp+'/api/tasks/'+id+'/toggle',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{status:next}})}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
function delTask(id){{
  ConfirmDialog.show('¿Eliminar tarea?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/tasks/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
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
var _clTemplates={{
  "instalacion":["Verificar alimentación eléctrica","Rack y cableado organizado","Etiquetado de puertos completado","Configuración de dispositivos aplicada","Prueba de conectividad end-to-end","Documentación entregada al cliente"],
  "averia":["Diagnóstico inicial documentado","Identificar componente fallido","Reemplazo o reconfiguración aplicada","Verificar servicio restaurado","Causa raíz documentada","Registro en sistema actualizado"],
  "mantenimiento":["Revisión visual de LEDs e interfaces","Limpieza de ventiladores y filtros","Revisión de logs de errores","Backup de configuración realizado","Test de failover si aplica","Informe de estado entregado"],
  "inspeccion":["Inventario físico de equipos","Estado visual del cableado","Comprobación de etiquetado","Test de velocidad y latencia","Revisión de licencias vigentes","Informe fotográfico completado"],
  "proyecto":["Kick-off con cliente realizado","Materiales disponibles confirmados","Instalación completada","Pruebas de aceptación superadas","Formación al cliente impartida","Documentación as-built entregada"]
}};
function loadClTemplate(){{
  var tmpl=_clTemplates[_projWorkType]||_clTemplates['proyecto'];
  var hasItems=document.getElementById('cl-list').querySelectorAll('li:not(.muted)').length>0;
  var doLoad=function(){{
    var reqs=tmpl.map(function(label){{
      return fetch(bp+'/api/tasks/'+_clTaskId+'/checklist',{{method:'POST',
        headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{label:label}})}});
    }});
    Promise.all(reqs).then(function(){{
      fetch(bp+'/api/tasks/'+_clTaskId+'/checklist').then(function(r){{return r.json();}}).then(renderChecklist);
      Toast.show('Plantilla cargada — '+tmpl.length+' pasos','ok');
    }});
  }};
  if(hasItems){{
    ConfirmDialog.show('¿Añadir plantilla?','Se añadirán '+tmpl.length+' pasos al checklist existente.')
      .then(function(ok){{if(ok)doLoad();}});
  }}else{{doLoad();}}
}}

// ── log ──
function updateLogPreview(){{
  var h=parseFloat(document.getElementById('log-hours').value)||0;
  var t=parseInt(document.getElementById('log-techs').value)||1;
  var el=document.getElementById('log-ph-preview');
  if(h>0&&t>1) el.textContent='→ '+( h*t).toFixed(1)+' person-horas';
  else el.textContent='';
}}
document.getElementById('log-hours').addEventListener('input',updateLogPreview);
document.getElementById('log-techs').addEventListener('change',updateLogPreview);
function addLog(){{
  var body=document.getElementById('log-body').value.trim();
  if(!body) return;
  var hours=parseFloat(document.getElementById('log-hours').value)||0;
  var techs=parseInt(document.getElementById('log-techs').value)||1;
  fetch(bp+'/api/projects/'+pid+'/log',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{body:body,hours:hours,technicians:techs}})}})
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
  var s=opt?parseInt(opt.getAttribute('data-stock')||'0'):0;
  var sm=opt?parseInt(opt.getAttribute('data-stockmin')||'0'):0;
  var req=parseInt(document.getElementById('a-req').value)||0;
  var el=document.getElementById('a-stock-info');
  if(req>s){{
    el.textContent='⚠️ Stock insuficiente: '+s+' ud en almacén (solicitado: '+req+')';
    el.style.color='var(--s-err)';
  }}else if(sm>0&&s<=sm){{
    el.textContent='⚠️ Stock bajo ('+s+'/'+sm+' mínimo). Confirma antes de asignar.';
    el.style.color='var(--s-warn)';
  }}else{{
    el.textContent='Stock en almacén: '+s+' ud';
    el.style.color='var(--muted)';
  }}
}}
document.getElementById('a-req').oninput=updateStockInfo;
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
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
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
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}}
function removeMember(id){{
  ConfirmDialog.show('¿Quitar del equipo?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/project_members/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
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
  ConfirmDialog.show('¿Eliminar este archivo?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/project_files/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}

// ── work logs ──
function addWorkLog(){{
  var uid_el=document.getElementById('wl-user');
  var date=document.getElementById('wl-date').value;
  var hours=parseFloat(document.getElementById('wl-hours').value);
  var desc=document.getElementById('wl-desc').value;
  if(!date||!hours||hours<=0){{Toast.show('Fecha y horas son obligatorias','err');return;}}
  var d={{project_id:pid,log_date:date,hours:hours,description:desc}};
  if(uid_el) d.user_id=uid_el.value;
  fetch(bp+'/api/work_logs',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}location.reload();}});
}}
function delWorkLog(id){{
  ConfirmDialog.show('¿Eliminar este registro de horas?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/work_logs/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}

// ── task photos ──
var _photoTaskId=null;
function openTaskPhotos(taskId, title){{
  _photoTaskId=taskId;
  document.getElementById('photo-modal-title').textContent='📷 '+title;
  document.getElementById('photo-input').value='';
  loadTaskPhotos(taskId);
  document.getElementById('photo-modal').classList.add('open');
}}
function closePhotoModal(){{document.getElementById('photo-modal').classList.remove('open');}}
document.getElementById('photo-modal').onclick=function(e){{if(e.target===this)closePhotoModal();}};
function loadTaskPhotos(taskId){{
  fetch(bp+'/api/tasks/'+taskId+'/photos')
    .then(function(r){{return r.json();}})
    .then(function(photos){{
      var grid=document.getElementById('photo-grid');
      if(!photos.length){{grid.innerHTML='<p class="muted" style="grid-column:1/-1;text-align:center;padding:16px;font-size:.85rem">Sin fotos todavía</p>';return;}}
      grid.innerHTML=photos.map(function(ph){{
        return '<div style="position:relative;aspect-ratio:1;overflow:hidden;border-radius:6px;background:#000">'
          +'<img src="'+bp+'/api/tasks/'+taskId+'/photos/'+ph.filename+'" '
          +'style="width:100%;height:100%;object-fit:cover" loading="lazy">'
          +'<button onclick="delTaskPhoto('+ph.id+')" style="position:absolute;top:3px;right:3px;background:rgba(0,0,0,.6);color:#fff;border:none;border-radius:50%;width:20px;height:20px;cursor:pointer;font-size:.7rem;display:flex;align-items:center;justify-content:center">✕</button>'
          +'</div>';
      }}).join('');
    }});
}}
function uploadTaskPhotos(files){{
  if(!files.length) return;
  var fd=new FormData();
  Array.from(files).forEach(function(f){{fd.append('photo',f);}});
  fetch(bp+'/api/tasks/'+_photoTaskId+'/photos',{{method:'POST',body:fd}})
    .then(function(r){{if(r.ok){{loadTaskPhotos(_photoTaskId);location.reload();}}
      else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}}
function delTaskPhoto(id){{
  ConfirmDialog.show('¿Eliminar esta foto?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/task_photos/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)loadTaskPhotos(_photoTaskId);}});
    }});
}}

// ── signature ──
var _sigDrawing=false, _sigCtx=null, _sigHasMark=false;
function openSigModal(){{
  document.getElementById('sig-modal').classList.add('open');
  var c=document.getElementById('sig-canvas');
  _sigCtx=c.getContext('2d');
  _sigCtx.clearRect(0,0,c.width,c.height);
  _sigHasMark=false;
  _sigCtx.strokeStyle='#1558c2'; _sigCtx.lineWidth=2.5; _sigCtx.lineCap='round'; _sigCtx.lineJoin='round';
  function pos(e){{
    var r=c.getBoundingClientRect();
    var scaleX=c.width/r.width, scaleY=c.height/r.height;
    var src=e.touches?e.touches[0]:e;
    return {{x:(src.clientX-r.left)*scaleX, y:(src.clientY-r.top)*scaleY}};
  }}
  c.onmousedown=c.ontouchstart=function(e){{e.preventDefault();_sigDrawing=true;var p=pos(e);_sigCtx.beginPath();_sigCtx.moveTo(p.x,p.y);}};
  c.onmousemove=c.ontouchmove=function(e){{e.preventDefault();if(!_sigDrawing)return;var p=pos(e);_sigCtx.lineTo(p.x,p.y);_sigCtx.stroke();_sigHasMark=true;}};
  c.onmouseup=c.ontouchend=function(){{_sigDrawing=false;}};
}}
function clearSignature(){{
  var c=document.getElementById('sig-canvas');
  _sigCtx.clearRect(0,0,c.width,c.height);
  _sigHasMark=false;
}}
function closeSigModal(){{document.getElementById('sig-modal').classList.remove('open');}}
document.getElementById('sig-modal').onclick=function(e){{if(e.target===this)closeSigModal();}};
function saveSignature(){{
  if(!_sigHasMark){{Toast.show('Por favor dibuja la firma antes de guardar','err');return;}}
  var dataUrl=document.getElementById('sig-canvas').toDataURL('image/png');
  fetch(bp+'/api/projects/'+pid+'/signature',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{image:dataUrl}})}})
    .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'Error');}});}})
    .then(function(){{closeSigModal();Toast.show('Firma guardada correctamente','ok');location.reload();}})
    .catch(function(err){{Toast.show(err.message,'err');}});
}}

// ── extras ──
function addExtra(){{
  var desc=document.getElementById('ex-desc').value.trim();
  if(!desc){{Toast.show('Escribe una descripción','err');return;}}
  fetch(bp+'/api/projects/'+pid+'/extras',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{description:desc,
      quantity:parseFloat(document.getElementById('ex-qty').value)||1,
      unit:document.getElementById('ex-unit').value||'ud',
      notes:document.getElementById('ex-notes').value}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}}
function delExtra(id){{
  ConfirmDialog.show('¿Eliminar este extra?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/wo_extras/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}

// ── equipment ──
function addEquipment(){{
  var model=document.getElementById('eq-model').value.trim();
  if(!model){{Toast.show('Escribe el modelo del equipo','err');return;}}
  fetch(bp+'/api/projects/'+pid+'/equipment',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{brand:document.getElementById('eq-brand').value,
      model:model,serial_number:document.getElementById('eq-serial').value,
      quantity:parseInt(document.getElementById('eq-qty').value)||1,
      notes:document.getElementById('eq-notes').value}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}}
function delEquipment(id){{
  ConfirmDialog.show('¿Eliminar este equipo?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/equipment_items/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
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
  ConfirmDialog.show('¿Eliminar comentario?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/wo_comments/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}

// ── kit recommendations ──
function openKitRecModal(){{
  document.getElementById('kr-name').value='';
  document.getElementById('kr-qty').value='1';
  document.getElementById('kr-unit').value='uds';
  document.getElementById('kr-notes').value='';
  document.getElementById('kit-rec-modal').classList.add('open');
}}
function closeKitRecModal(){{document.getElementById('kit-rec-modal').classList.remove('open');}}
document.getElementById('kit-rec-modal').onclick=function(e){{if(e.target===this)closeKitRecModal();}};
function doAddKitRec(){{
  var name=document.getElementById('kr-name').value.trim();
  if(!name){{Toast.show('Escribe una descripción','err');return;}}
  fetch(bp+'/api/projects/'+pid+'/kit',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{
      category:document.getElementById('kr-cat').value,
      item_name:name,
      quantity:document.getElementById('kr-qty').value||'1',
      unit:document.getElementById('kr-unit').value||'uds',
      notes:document.getElementById('kr-notes').value
    }})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});}});
}}
function kitSetStatus(id,status){{
  fetch(bp+'/api/project_kit/'+id,{{method:'PATCH',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{status:status}})}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
function delKitRec(id){{
  ConfirmDialog.show('¿Eliminar esta recomendación?','')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/project_kit/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}

// ── Task comments ──
var _tcmTaskId=null;
function openTaskComments(tid,title){{
  _tcmTaskId=tid;
  document.getElementById('tcm-title').textContent='💬 '+title;
  document.getElementById('tcm-body').value='';
  document.getElementById('tcm-list').innerHTML='<span class="muted">Cargando…</span>';
  document.getElementById('tcm-modal').classList.add('open');
  _loadTaskComments(tid);
}}
function _loadTaskComments(tid){{
  fetch(bp+'/api/tasks/'+tid+'/comments')
    .then(function(r){{return r.json();}}).then(_renderTaskComments);
}}
function _renderTaskComments(items){{
  var el=document.getElementById('tcm-list');
  if(!items.length){{
    el.innerHTML='<p class="muted" style="text-align:center;padding:16px;margin:0">Sin comentarios todavía.</p>';
    return;
  }}
  el.innerHTML=items.map(function(c){{
    var body=(c.body||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
    var ts=c.created_at?c.created_at.slice(0,16):'';
    return '<div style="padding:8px 0;border-bottom:1px solid var(--border)">'
      +'<div style="font-size:.75rem;color:var(--muted);margin-bottom:2px">'
      +(c.author||'')+'&nbsp;·&nbsp;'+ts
      +'<button onclick="delTaskComment('+c.id+')" style="background:none;border:none;color:var(--muted);cursor:pointer;float:right;font-size:.8rem">✕</button>'
      +'</div>'
      +'<div style="font-size:.875rem">'+body+'</div>'
      +'</div>';
  }}).join('');
}}
function addTaskComment(){{
  var body=document.getElementById('tcm-body').value.trim();
  if(!body) return;
  fetch(bp+'/api/tasks/'+_tcmTaskId+'/comments',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{body:body}})}})
    .then(function(r){{if(r.ok){{
      document.getElementById('tcm-body').value='';
      _loadTaskComments(_tcmTaskId);
    }}}});
}}
function delTaskComment(id){{
  fetch(bp+'/api/task_comments/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok&&_tcmTaskId) _loadTaskComments(_tcmTaskId);}});
}}

// ── Gantt ──
function _svgEsc(s){{return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function buildGantt(){{
  var wrap=document.getElementById('gantt-svg-wrap');
  if(!wrap) return;
  var tasks=_allTasks.filter(function(t){{return t.due_date||t.start_date;}});
  if(!tasks.length){{
    wrap.innerHTML='<p class="muted" style="text-align:center;padding:32px">Sin tareas con fechas — edita las tareas y añade inicio o fecha límite.</p>';
    return;
  }}
  var dates=[];
  tasks.forEach(function(t){{
    if(t.start_date) dates.push(new Date(t.start_date).getTime());
    if(t.due_date) dates.push(new Date(t.due_date).getTime());
    if(t.created_at) dates.push(new Date(t.created_at).getTime());
  }});
  var minD=new Date(Math.min.apply(null,dates));
  var maxD=new Date(Math.max.apply(null,dates));
  minD.setDate(minD.getDate()-2); maxD.setDate(maxD.getDate()+2);
  var totalMs=maxD-minD; var totalDays=Math.max(1,totalMs/(1000*60*60*24));
  var ROW_H=36,LABEL_W=150,BAR_W=Math.max(500,Math.ceil(totalDays*22));
  var SVG_W=LABEL_W+BAR_W,SVG_H=tasks.length*ROW_H+32;
  var SC={{done:'#64748b',blocked:'#dc2626',in_progress:'#1558c2',pending:'#94a3b8',active:'#15803d'}};
  var today=new Date().toISOString().slice(0,10);
  function dayX(ds){{
    var d=new Date(ds); return LABEL_W+(d-minD)/totalMs*BAR_W;
  }}
  // header: week marks
  var hdr='';
  var cur=new Date(minD);
  while(cur<=maxD){{
    var x=dayX(cur.toISOString().slice(0,10));
    var lbl=cur.toLocaleDateString('es-ES',{{day:'2-digit',month:'short'}});
    hdr+='<text x="'+x+'" y="18" font-size="9" fill="#94a3b8" text-anchor="middle">'+lbl+'</text>';
    hdr+='<line x1="'+x+'" y1="20" x2="'+x+'" y2="'+SVG_H+'" stroke="var(--border)" stroke-width="0.5"/>';
    cur.setDate(cur.getDate()+7);
  }}
  // rows
  var rows='';
  tasks.forEach(function(t,i){{
    var y=32+i*ROW_H;
    var color=SC[t.status]||'#94a3b8';
    var startDs=t.start_date||t.created_at||today;
    var endDs=t.due_date||(new Date(new Date(startDs).getTime()+86400000)).toISOString().slice(0,10);
    var x0=dayX(startDs),x1=dayX(endDs);
    var barW=Math.max(6,x1-x0);
    var overdue=t.due_date&&t.due_date<today&&t.status!=='done';
    var barC=overdue?'#dc2626':color;
    var lbl=t.title.length>22?t.title.slice(0,22)+'…':t.title;
    if(i%2===0) rows+='<rect x="0" y="'+y+'" width="'+SVG_W+'" height="'+ROW_H+'" fill="rgba(0,0,0,.03)"/>';
    rows+='<g onclick="editTask(_allTasksById['+t.id+'])" style="cursor:pointer">'
      +'<text x="'+(LABEL_W-6)+'" y="'+(y+ROW_H/2+4)+'" text-anchor="end" font-size="11" fill="var(--text)">'+_svgEsc(lbl)+'</text>'
      +'<rect x="'+x0+'" y="'+(y+6)+'" width="'+barW+'" height="'+(ROW_H-14)+'" rx="4" fill="'+barC+'" opacity=".85"/>';
    if(barW>30&&t.due_date){{
      var dStr=t.due_date.slice(5);
      rows+='<text x="'+(x0+barW/2)+'" y="'+(y+ROW_H/2+4)+'" text-anchor="middle" font-size="9" fill="#fff">'+dStr+'</text>';
    }}
    rows+='</g>';
  }});
  // today line
  var todayX=dayX(today);
  var todayLine='';
  if(todayX>=LABEL_W&&todayX<=SVG_W){{
    todayLine='<line x1="'+todayX+'" y1="20" x2="'+todayX+'" y2="'+SVG_H+'" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="5,3" opacity=".7"/>'
      +'<text x="'+todayX+'" y="16" text-anchor="middle" font-size="9" fill="#dc2626" font-weight="bold">Hoy</text>';
  }}
  wrap.innerHTML='<svg width="'+SVG_W+'" height="'+SVG_H+'" style="display:block;font-family:inherit;max-width:100%">'
    +hdr+rows+todayLine+'</svg>';
}}

// ── Plantillas ──
function showSaveTemplateModal(){{
  document.getElementById('tpl-name').value='{_esc(p.get("name",""))}';
  document.getElementById('tpl-save-modal').classList.add('open');
}}
function doSaveTemplate(){{
  var name=document.getElementById('tpl-name').value.trim();
  if(!name){{Toast.show('Escribe un nombre para la plantilla','err');return;}}
  var tasksForTpl=_allTasks.map(function(t){{
    return {{title:t.title,description:t.description,priority:t.priority,status:'pending'}};
  }});
  fetch(bp+'/api/templates',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:name,description:'',work_type:_projWorkType,
      estimated_hours:{p.get('estimated_hours') or 0},tasks_json:JSON.stringify(tasksForTpl)}})}})
    .then(function(r){{
      if(r.ok){{
        document.getElementById('tpl-save-modal').classList.remove('open');
        Toast.show('Plantilla guardada: '+name,'ok');
      }} else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});
    }});
}}
</script>"""
    return _shell("projects", user, content, title=_esc(p["name"]))


# ── inventory ─────────────────────────────────────────────────────────────────

from web.pages.inventory import _inventory_page
from web.pages.kit import _kit_page
from web.pages.users import _users_page
from web.pages.reports import _project_report, _project_report_md, _project_albaran, _project_parte, _profitability_page
from web.pages.calendar import _calendar_page, _calendar_week, _calendar_day
from web.pages.map import _map_page
from web.pages.settings import _settings_page
from web.pages.notifications import _notifications_page
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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        if ct.startswith("text/html"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
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
                ext = os.path.splitext(orig)[1].lower()
                if ext in _BLOCKED_EXTS:
                    self._json(400, {"error": f"Tipo de archivo no permitido: {ext}"}); return
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
        except Exception:
            self._json(500, {"error": "Error al procesar el archivo"})

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
        if rel == "/set-password":
            self._send(200, _set_password_page(qs.get("token",[""])[0])); return
        if rel == "/logout":
            _del_sess(self)
            self.send_response(302)
            self.send_header("Location", f"{BP}/login")
            self.send_header("Set-Cookie", f"nd_sess=; Path={BP or '/'}; Max-Age=0; HttpOnly")
            self.end_headers(); return

        # Static assets
        if rel == "/assets/styles/app.css":
            css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "styles", "app.css")
            if os.path.exists(css_path):
                with open(css_path, "rb") as f:
                    css_data = f.read()
                self._send(200, css_data, "text/css; charset=utf-8"); return
            self._send(404, "Not found"); return

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
            sw = f"""var CACHE='nd-v2-{BP or "root"}';
var ASSETS=['{BP}/assets/styles/app.css'];
self.addEventListener('install',function(e){{
  e.waitUntil(caches.open(CACHE).then(function(c){{return c.addAll(ASSETS);}}));
  self.skipWaiting();
}});
self.addEventListener('activate',function(e){{
  e.waitUntil(caches.keys().then(function(keys){{
    return Promise.all(keys.filter(function(k){{return k!==CACHE;}}).map(function(k){{return caches.delete(k);}}));
  }}));
  self.clients.claim();
}});
self.addEventListener('fetch',function(e){{
  var url=e.request.url;
  if(url.includes('/assets/')){{
    e.respondWith(caches.match(e.request).then(function(r){{return r||fetch(e.request);}}));
    return;
  }}
  if(e.request.method==='GET'&&(url.includes('/field')||url.includes('/api/tasks'))){{
    e.respondWith(
      fetch(e.request).then(function(r){{
        if(r.ok){{var rc=r.clone();caches.open(CACHE).then(function(c){{c.put(e.request,rc);}});}}
        return r;
      }}).catch(function(){{return caches.match(e.request)||new Response('Sin conexión',{{status:503}});}}));
    return;
  }}
  e.respondWith(fetch(e.request).catch(function(){{
    return caches.match(e.request)||new Response('Sin conexión',{{status:503}});
  }}));
}});"""
            self._send(200, sw, "application/javascript"); return

        sess = _get_sess(self)
        if not sess: self._redirect(f"{BP}/login"); return

        if rel in ("/", "/dashboard"):
            self._send(200, _dashboard(sess)); return
        if rel == "/projects":
            self._send(200, _projects_page(sess, qs.get("status",[""])[0], qs.get("view",["cards"])[0], qs.get("new",[""])[0], qs.get("tech",[""])[0], qs.get("wtype",[""])[0], qs.get("dfrom",[""])[0], qs.get("dto",[""])[0])); return
        m = re.match(r"^/projects/(\d+)$", rel)
        if m:
            html = _project_detail(sess, int(m.group(1)))
            self._send(200 if html else 404, html or "Not found"); return
        if rel == "/field":
            self._send(200, _field_page(sess)); return
        if rel == "/clients":
            self._send(200, _clients_page(sess)); return
        m = re.match(r"^/clients/(.+)$", rel)
        if m:
            import urllib.parse
            cname = urllib.parse.unquote_plus(m.group(1))
            html = _client_detail(sess, cname)
            self._send(200 if html else 404, html or "Not found"); return
        if rel == "/profitability":
            html = _profitability_page(sess)
            self._send(200 if html else 403, html or "Forbidden"); return
        m = re.match(r"^/projects/(\d+)/parte$", rel)
        if m:
            html = _project_parte(sess, int(m.group(1)))
            self._send(200 if html else 404, html or "Not found"); return
        if rel == "/inventory":
            self._send(200, _inventory_page(sess)); return
        if rel == "/kit":
            self._send(200, _kit_page(sess)); return
        if rel == "/calendar":
            view = qs.get("view", ["month"])[0]
            if view == "week":
                ws = qs.get("week_start", [""])[0]
                self._send(200, _calendar_week(sess, ws)); return
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
        if rel == "/settings":
            if sess.get("role") != "admin": self._redirect(f"{BP}/"); return
            rules = rs(q("SELECT * FROM notif_rules ORDER BY event_key"))
            self._send(200, _settings_page(sess, rules)); return
        if rel == "/workload":
            self._redirect(f"{BP}/calendar"); return
        if rel == "/map":
            self._send(200, _map_page(sess)); return
        if rel == "/notifications":
            self._send(200, _notifications_page(sess)); return
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
        m = re.match(r"^/api/tasks/(\d+)/photos$", rel)
        if m:
            tid = int(m.group(1))
            self._json(200, rs(q("SELECT * FROM task_photos WHERE task_id=? ORDER BY created_at DESC", (tid,)))); return
        if rel == "/api/geocode":
            addr = qs.get("q", [""])[0].strip()
            if not addr: self._json(400, {"error":"q requerido"}); return
            lat, lng = _geocode_address(addr)
            if lat is None: self._json(404, {"error":"Dirección no encontrada"}); return
            self._json(200, {"lat": lat, "lng": lng}); return

        if rel == "/api/notifications":
            notifs = rs(q("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (sess["id"],)))
            unread = q1("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (sess["id"],))[0]
            self._json(200, {"notifications": notifs, "unread": unread}); return
        if rel == "/api/notif_rules":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            self._json(200, rs(q("SELECT * FROM notif_rules ORDER BY event_key"))); return
        if rel == "/api/settings":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            rows = rs(q("SELECT key,value FROM app_settings"))
            cfg = {r["key"]: r["value"] for r in rows}
            cfg.pop("smtp_pass", None)
            self._json(200, cfg); return
        m = re.match(r"^/api/tasks/(\d+)/photos/(.+)$", rel)
        if m:
            tid, fname = int(m.group(1)), m.group(2)
            tp = r2d(q1("SELECT * FROM task_photos WHERE task_id=? AND filename=?", (tid, fname)))
            if not tp: self._send(404, "Not found"); return
            task_row = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if not task_row: self._send(404, "Not found"); return
            fpath = os.path.join(FILES_DIR, str(task_row["project_id"]), "tasks", fname)
            if not os.path.exists(fpath): self._send(404, "Not found"); return
            with open(fpath,'rb') as fp: fdata = fp.read()
            self._send(200, fdata, "image/jpeg", {"Content-Disposition":"inline"}); return
        if rel == "/api/materials":
            self._json(200, rs(q("SELECT * FROM materials ORDER BY name"))); return
        if rel == "/api/locations":
            locs = rs(q("""SELECT wl.*,
                COALESCE(SUM(sbl.qty),0) total_stock,
                COUNT(DISTINCT sbl.material_id) n_materials
                FROM warehouse_locations wl
                LEFT JOIN stock_by_location sbl ON sbl.location_id=wl.id AND sbl.qty>0
                GROUP BY wl.id ORDER BY wl.warehouse,wl.code"""))
            self._json(200, locs); return
        m = re.match(r"^/api/materials/(\d+)/stock_by_location$", rel)
        if m:
            mid = int(m.group(1))
            rows = rs(q("""SELECT sbl.*,wl.code loc_code,wl.name loc_name,wl.warehouse
                FROM stock_by_location sbl JOIN warehouse_locations wl ON wl.id=sbl.location_id
                WHERE sbl.material_id=? AND sbl.qty>0
                ORDER BY wl.warehouse,wl.code""", (mid,)))
            self._json(200, rows); return
        m = re.match(r"^/api/materials/(\d+)/assignments$", rel)
        if m:
            mid = int(m.group(1))
            rows = rs(q("""SELECT a.*,p.name pname,p.status pstatus,p.id pid
                FROM assignments a JOIN projects p ON p.id=a.project_id
                WHERE a.material_id=? ORDER BY a.updated_at DESC""", (mid,)))
            self._json(200, rows); return
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
            safe_name = re.sub(r'["\r\n\\]', '_', pf["original_name"] or fname)
            disp = 'inline' if is_img else f'attachment; filename="{safe_name}"'
            self._send(200, fdata, mime, {"Content-Disposition": disp}); return
        if rel == "/api/kit":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            self._json(200, rs(q("SELECT k.*,m.name mat_name,m.code mat_code FROM tech_kit k JOIN materials m ON m.id=k.material_id"))); return

        # activities
        if rel == "/api/activities":
            date_f = qs.get("date",[""])[0]
            yr_f   = qs.get("year",[""])[0]
            mo_f   = qs.get("month",[""])[0]
            ws_f   = qs.get("week_start",[""])[0]
            uid_f  = qs.get("user_id",[""])[0]
            base_q = """SELECT a.*,u.display_name uname,p.name pname
                FROM activities a
                JOIN users u ON u.id=a.user_id
                JOIN projects p ON p.id=a.project_id"""
            conds, params = [], []
            if sess.get("role") not in ("admin","backoffice"):
                conds.append("a.user_id=?"); params.append(sess["id"])
            elif uid_f:
                conds.append("a.user_id=?"); params.append(int(uid_f))
            if date_f:
                conds.append("a.activity_date=?"); params.append(date_f)
            elif ws_f:
                try:
                    ws = _date.fromisoformat(ws_f)
                    we = str(ws + timedelta(days=6))
                    conds.append("a.activity_date BETWEEN ? AND ?"); params += [ws_f, we]
                except ValueError: pass
            elif yr_f and mo_f:
                from calendar import monthrange as _mr
                _, dm = _mr(int(yr_f), int(mo_f))
                d1 = f"{int(yr_f):04d}-{int(mo_f):02d}-01"
                d2 = f"{int(yr_f):04d}-{int(mo_f):02d}-{dm:02d}"
                conds.append("a.activity_date BETWEEN ? AND ?"); params += [d1, d2]
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            rows = rs(q(f"{base_q} {where} ORDER BY a.activity_date,a.hour_start,u.display_name",
                        tuple(params)))
            self._json(200, rows); return

        # work logs
        if rel == "/api/work_logs":
            prj_f = qs.get("project_id",[""])[0]
            ws_f  = qs.get("week_start",[""])[0]
            uid_f = qs.get("user_id",[""])[0]
            base_q = """SELECT wl.*,u.display_name uname,p.name pname
                FROM work_logs wl
                JOIN users u ON u.id=wl.user_id
                JOIN projects p ON p.id=wl.project_id"""
            conds, params = [], []
            if sess.get("role") not in ("admin","backoffice"):
                conds.append("wl.user_id=?"); params.append(sess["id"])
            elif uid_f:
                conds.append("wl.user_id=?"); params.append(int(uid_f))
            if prj_f:
                conds.append("wl.project_id=?"); params.append(int(prj_f))
            if ws_f:
                try:
                    ws = _date.fromisoformat(ws_f)
                    we = str(ws + timedelta(days=6))
                    conds.append("wl.log_date BETWEEN ? AND ?"); params += [ws_f, we]
                except ValueError: pass
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            rows = rs(q(f"{base_q} {where} ORDER BY wl.log_date,u.display_name",
                        tuple(params)))
            self._json(200, rows); return

        # tech availability
        if rel == "/api/tech_availability":
            yr_f = qs.get("year",[""])[0]
            mo_f = qs.get("month",[""])[0]
            ws_f = qs.get("week_start",[""])[0]
            conds, params = [], []
            if yr_f and mo_f:
                from calendar import monthrange as _mr2
                _, dm = _mr2(int(yr_f), int(mo_f))
                d1 = f"{int(yr_f):04d}-{int(mo_f):02d}-01"
                d2 = f"{int(yr_f):04d}-{int(mo_f):02d}-{dm:02d}"
                conds.append("avail_date BETWEEN ? AND ?"); params += [d1, d2]
            elif ws_f:
                try:
                    ws = _date.fromisoformat(ws_f)
                    we = str(ws + timedelta(days=6))
                    conds.append("avail_date BETWEEN ? AND ?"); params += [ws_f, we]
                except ValueError: pass
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            self._json(200, rs(q(f"SELECT * FROM tech_availability {where} ORDER BY avail_date",
                                  tuple(params)))); return

        # project work logs
        m = re.match(r"^/api/projects/(\d+)/work_logs$", rel)
        if m:
            pid = int(m.group(1))
            rows = rs(q("""SELECT wl.*,u.display_name uname FROM work_logs wl
                JOIN users u ON u.id=wl.user_id
                WHERE wl.project_id=? ORDER BY wl.log_date DESC,u.display_name""", (pid,)))
            self._json(200, rows); return

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

        m = re.match(r"^/api/users/(\d+)/certifications$", rel)
        if m:
            uid = int(m.group(1))
            certs = rs(q("SELECT * FROM user_certifications WHERE user_id=? ORDER BY cert_name", (uid,)))
            self._json(200, certs); return

        m = re.match(r"^/api/users/(\d+)/availability$", rel)
        if m:
            uid = int(m.group(1))
            if sess.get("role") != "admin" and uid != sess["id"]:
                self._json(403, {"error":"Forbidden"}); return
            rows = rs(q("""SELECT * FROM tech_availability
                WHERE user_id=? AND status IN ('vacation','day_off','sick')
                ORDER BY avail_date""", (uid,)))
            self._json(200, rows); return

        m = re.match(r"^/api/tasks/(\d+)/comments$", rel)
        if m:
            tid = int(m.group(1))
            rows = rs(q("""SELECT tc.*,u.display_name author FROM task_comments tc
                JOIN users u ON u.id=tc.user_id WHERE tc.task_id=? ORDER BY tc.created_at ASC""", (tid,)))
            self._json(200, rows); return

        m = re.match(r"^/api/tasks/(\d+)/dependencies$", rel)
        if m:
            tid = int(m.group(1))
            rows = rs(q("""SELECT td.*,t.title dep_title FROM task_dependencies td
                JOIN tasks t ON t.id=td.depends_on WHERE td.task_id=? ORDER BY td.id""", (tid,)))
            self._json(200, rows); return

        if rel == "/api/templates":
            tmpls = rs(q("SELECT id,name,description,work_type,estimated_hours,created_at FROM project_templates ORDER BY created_at DESC"))
            self._json(200, tmpls); return

        m = re.match(r"^/api/templates/(\d+)$", rel)
        if m:
            tid = int(m.group(1))
            tpl = r2d(q1("SELECT * FROM project_templates WHERE id=?", (tid,)))
            if not tpl: self._json(404, {"error":"Not found"}); return
            self._json(200, tpl); return

        if rel == "/api/export/projects.csv":
            import io, csv
            projects_all = rs(q("""SELECT p.id,p.name,p.client,p.work_type,p.status,p.priority,
                p.reference,p.start_date,p.due_date,p.estimated_hours,p.address,
                u.display_name tech,p.created_at,p.updated_at
                FROM projects p LEFT JOIN users u ON u.id=p.assigned_to
                ORDER BY p.created_at DESC"""))
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["ID","Nombre","Cliente","Tipo","Estado","Prioridad","Referencia",
                        "Inicio","Límite","Horas est.","Dirección","Técnico","Creado","Actualizado"])
            for pr in projects_all:
                w.writerow([pr["id"],pr["name"],pr["client"],pr.get("work_type",""),
                            pr["status"],pr["priority"],pr.get("reference",""),
                            pr.get("start_date",""),pr.get("due_date",""),
                            pr.get("estimated_hours",""),pr.get("address",""),
                            pr.get("tech",""),pr.get("created_at","")[:10],pr.get("updated_at","")[:10]])
            body = buf.getvalue().encode("utf-8-sig")
            self.send_response(200)
            self.send_header("Content-Type","text/csv; charset=utf-8")
            self.send_header("Content-Disposition",'attachment; filename="proyectos-nuvodesk.csv"')
            self.send_header("Content-Length",str(len(body)))
            self.end_headers(); self.wfile.write(body); return

        if rel == "/api/tech_inventory":
            rows = rs(q("""SELECT ti.*,u.display_name uname,m.name mat_name,m.code mat_code,m.unit mat_unit
                FROM tech_inventory ti
                JOIN users u ON u.id=ti.user_id
                JOIN materials m ON m.id=ti.material_id
                WHERE ti.qty>0 ORDER BY u.display_name,m.name"""))
            self._json(200, rows); return

        m = re.match(r"^/projects/(\d+)/report$", rel)
        if m:
            html = _project_report(sess, int(m.group(1)))
            self._send(200 if html else 404, html or "Not found"); return

        m = re.match(r"^/projects/(\d+)/albaran$", rel)
        if m:
            html = _project_albaran(sess, int(m.group(1)))
            self._send(200 if html else 404, html or "Not found"); return

        m = re.match(r"^/projects/(\d+)/report\.md$", rel)
        if m:
            md = _project_report_md(sess, int(m.group(1)))
            if not md: self._send(404, "Not found"); return
            slug = re.sub(r'[^a-z0-9]+', '-', (md.split('\n')[0].lstrip('# ').lower()))[:40]
            fname = f"informe-{slug}.md"
            body = md.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body); return

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

        # public endpoints — no auth required
        if rel == "/api/set-password":
            data = _body(self)
            token = (data.get("token","") or "").strip()
            pw = (data.get("password","") or "").strip()
            if not token or not pw:
                self._json(400, {"error":"Datos incompletos"}); return
            if len(pw) < 8:
                self._json(400, {"error":"La contraseña debe tener al menos 8 caracteres"}); return
            row = r2d(q1("SELECT id,reset_token_expiry FROM users WHERE reset_token=?", (token,)))
            if not row:
                self._json(400, {"error":"Enlace inválido o expirado"}); return
            expiry = row.get("reset_token_expiry","")
            if expiry and datetime.fromisoformat(expiry) < datetime.now():
                self._json(400, {"error":"El enlace ha caducado (48 horas)"}); return
            run("UPDATE users SET pw_hash=?,reset_token=NULL,reset_token_expiry=NULL WHERE id=?",
                (_hash(pw), row["id"]))
            self._json(200, {"ok":True}); return

        # login — parse body before auth check
        if rel == "/api/login":
            data = _body(self)
            un = (data.get("username","") or "").strip()
            pw = data.get("password","") or ""
            fail_entry = _login_fails.get(un, {})
            if fail_entry.get("locked_until", 0) > time.time():
                self._send(200, _login_page("Demasiados intentos fallidos. Espera 5 minutos.")); return
            u = r2d(q1("SELECT * FROM users WHERE username=? AND active=1", (un,)))
            if not u or not _check_pw(pw, u["pw_hash"]):
                count = fail_entry.get("count", 0) + 1
                locked = time.time() + _LOCKOUT_SECONDS if count >= _LOCKOUT_THRESHOLD else 0
                _login_fails[un] = {"count": count, "locked_until": locked}
                self._send(200, _login_page("Usuario o contraseña incorrectos")); return
            _login_fails.pop(un, None)
            # upgrade legacy SHA-256 hash to scrypt on successful login
            if len(u["pw_hash"]) == 64:
                run("UPDATE users SET pw_hash=? WHERE id=?", (_hash(pw), u["id"]))
            tok = _new_sess(u)
            self.send_response(302)
            self.send_header("Location", f"{BP}/")
            self.send_header("Set-Cookie", f"nd_sess={tok}; Path={BP or '/'}; HttpOnly; SameSite=Strict; Secure")
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

        # activities
        if rel == "/api/activities":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            uid   = int(data.get("user_id") or 0)
            prj   = int(data.get("project_id") or 0)
            adate = (data.get("activity_date","") or "").strip()
            if not uid or not prj or not adate:
                self._json(400, {"error":"Usuario, proyecto y fecha requeridos"}); return
            all_day = 1 if data.get("all_day") else 0
            hs_raw = data.get("hour_start"); he_raw = data.get("hour_end")
            hs = int(hs_raw) if hs_raw is not None else None
            he = int(he_raw) if he_raw is not None else None
            if not all_day and (hs is None or he is None or he <= hs):
                self._json(400, {"error":"Horas inicio y fin requeridas (fin > inicio)"}); return
            atype = data.get("type","physical") or "physical"
            if atype not in ("physical","online","meeting","travel","other"):
                self._json(400, {"error":"Tipo inválido"}); return
            existing = rs(q("""SELECT a.id,p.name pname,a.hour_start,a.hour_end,a.all_day
                FROM activities a JOIN projects p ON p.id=a.project_id
                WHERE a.user_id=? AND a.activity_date=?""", (uid, adate)))
            for ex in existing:
                urow = r2d(q1("SELECT display_name FROM users WHERE id=?", (uid,)))
                uname = urow["display_name"] if urow else str(uid)
                if all_day or ex["all_day"]:
                    self._json(409, {"error":f"Conflicto: {uname} ya tiene actividad ese día"}); return
                if hs < (ex["hour_end"] or 0) and he > (ex["hour_start"] or 0):
                    self._json(409, {"error":
                        f"Conflicto: {uname} ya tiene '{ex['pname']}' "
                        f"de {ex['hour_start']:02d}:00 a {ex['hour_end']:02d}:00 ese día"}); return
            warning = None
            avail = r2d(q1("SELECT status FROM tech_availability WHERE user_id=? AND avail_date=?",
                           (uid, adate)))
            if avail and avail["status"] == "traveling" and atype == "physical":
                warning = "El técnico está desplazado ese día"
            aid = run("""INSERT INTO activities
                (user_id,project_id,activity_date,all_day,hour_start,hour_end,type,notes,created_by)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (uid, prj, adate, all_day, hs, he, atype, data.get("notes",""), sess["id"]))
            if int(uid) != sess["id"]:
                prow = r2d(q1("SELECT name FROM projects WHERE id=?", (prj,)))
                _notify(uid, "Nueva actividad planificada",
                        f"{prow['name'] if prow else prj} · {adate}",
                        f"{BP}/calendar/{adate}", "activity_assigned")
            resp = {"id": aid}
            if warning: resp["warning"] = warning
            self._json(201, resp); return

        # work logs
        if rel == "/api/work_logs":
            uid_raw = data.get("user_id")
            if sess.get("role") == "admin":
                uid = int(uid_raw or sess["id"])
            else:
                uid = sess["id"]
            prj      = int(data.get("project_id") or 0)
            log_date = (data.get("log_date","") or "").strip()
            hours    = float(data.get("hours") or 0)
            if not prj or not log_date or hours <= 0 or hours > 24:
                self._json(400, {"error":"Proyecto, fecha y horas válidas (0–24) requeridos"}); return
            act_id = data.get("activity_id")
            wid = run("""INSERT INTO work_logs
                (user_id,project_id,log_date,hours,description,activity_id,created_by)
                VALUES(?,?,?,?,?,?,?)""",
                (uid, prj, log_date, hours, data.get("description",""),
                 int(act_id) if act_id else None, sess["id"]))
            self._json(201, {"id": wid}); return

        # tech availability — batch (date range)
        if rel == "/api/tech_availability/batch":
            uid        = int(data.get("user_id") or 0)
            date_from  = (data.get("date_from","") or "").strip()
            date_to    = (data.get("date_to","") or "").strip()
            status     = (data.get("status","vacation") or "vacation").strip()
            if not uid or not date_from or not date_to:
                self._json(400, {"error":"user_id, date_from y date_to requeridos"}); return
            _vac_ok = ("vacation","day_off","sick")
            _adm_ok = ("available","remote","traveling","off") + _vac_ok
            allowed = _adm_ok if sess.get("role") == "admin" else _vac_ok
            if status not in allowed:
                self._json(400, {"error":"Estado inválido"}); return
            if sess.get("role") != "admin" and uid != sess["id"]:
                self._json(403, {"error":"Solo puedes gestionar tus propias ausencias"}); return
            try:
                d_from = _date.fromisoformat(date_from)
                d_to   = _date.fromisoformat(date_to)
            except ValueError:
                self._json(400, {"error":"Fechas inválidas"}); return
            if d_to < d_from: self._json(400, {"error":"date_to debe ser >= date_from"}); return
            notes  = (data.get("notes","") or "").strip()
            cur = d_from
            count = 0
            while cur <= d_to:
                run("""INSERT INTO tech_availability (user_id,avail_date,status,notes)
                    VALUES(?,?,?,?)
                    ON CONFLICT(user_id,avail_date) DO UPDATE
                    SET status=excluded.status, notes=excluded.notes""",
                    (uid, str(cur), status, notes))
                cur += timedelta(days=1)
                count += 1
            self._json(200, {"ok": True, "days": count}); return

        # tech availability — single day
        if rel == "/api/tech_availability":
            uid        = int(data.get("user_id") or 0)
            avail_date = (data.get("avail_date","") or "").strip()
            status     = data.get("status","available") or "available"
            if not uid or not avail_date:
                self._json(400, {"error":"Usuario y fecha requeridos"}); return
            _vac_ok2 = ("vacation","day_off","sick")
            _adm_ok2 = ("available","remote","traveling","off") + _vac_ok2
            allowed2 = _adm_ok2 if sess.get("role") == "admin" else _vac_ok2
            if status not in allowed2:
                self._json(400, {"error":"Estado inválido"}); return
            if sess.get("role") != "admin" and uid != sess["id"]:
                self._json(403, {"error":"Forbidden"}); return
            run("""INSERT INTO tech_availability (user_id,avail_date,status,notes)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id,avail_date) DO UPDATE
                SET status=excluded.status, notes=excluded.notes""",
                (uid, avail_date, status, data.get("notes","")))
            self._json(200, {"ok": True}); return

        # change requests — create
        if rel == "/api/change_requests":
            act_id = int(data.get("activity_id") or 0)
            if not act_id: self._json(400, {"error":"activity_id requerido"}); return
            act = r2d(q1("SELECT * FROM activities WHERE id=?", (act_id,)))
            if not act: self._json(404, {"error":"Actividad no encontrada"}); return
            if sess.get("role") != "admin" and act["user_id"] != sess["id"]:
                self._json(403, {"error":"Forbidden"}); return
            if q1("SELECT id FROM change_requests WHERE activity_id=? AND status='pending'", (act_id,)):
                self._json(400, {"error":"Ya existe una solicitud pendiente para esta actividad"}); return
            req_type = (data.get("type","") or "").strip()
            msg      = (data.get("message","") or "").strip()
            if req_type not in ("cancel","reschedule","modify") or not msg:
                self._json(400, {"error":"Tipo y mensaje requeridos"}); return
            admin_id = act["created_by"] or 1
            crid = run("""INSERT INTO change_requests
                (activity_id,requester_id,admin_id,type,message)
                VALUES(?,?,?,?,?)""",
                (act_id, sess["id"], admin_id, req_type, msg))
            req_row = r2d(q1("SELECT display_name FROM users WHERE id=?", (sess["id"],)))
            prow    = r2d(q1("SELECT name FROM projects WHERE id=?", (act["project_id"],)))
            type_lbl = {"cancel":"Cancelar","reschedule":"Reagendar","modify":"Modificar"}.get(req_type, req_type)
            _notify(admin_id, f"Solicitud de cambio: {type_lbl}",
                    f"{req_row['display_name'] if req_row else '?'} · "
                    f"{prow['name'] if prow else '?'} · {act['activity_date']}",
                    f"{BP}/calendar/{act['activity_date']}", "change_request",
                    extra={"change_request_id": crid})
            self._json(201, {"id": crid}); return

        # change requests — resolve
        m = re.match(r"^/api/change_requests/(\d+)/resolve$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            crid = int(m.group(1))
            cr   = r2d(q1("SELECT * FROM change_requests WHERE id=?", (crid,)))
            if not cr: self._json(404, {"error":"No encontrada"}); return
            if cr["status"] != "pending": self._json(400, {"error":"Ya resuelta"}); return
            action = data.get("action","")
            if action not in ("approve","reject"):
                self._json(400, {"error":"action debe ser approve o reject"}); return
            new_status = "approved" if action == "approve" else "rejected"
            run("UPDATE change_requests SET status=?,admin_response=?,resolved_at=datetime('now') WHERE id=?",
                (new_status, data.get("response",""), crid))
            if new_status == "approved" and cr["type"] == "cancel":
                run("DELETE FROM activities WHERE id=?", (cr["activity_id"],))
            act = r2d(q1("SELECT activity_date,project_id FROM activities WHERE id=?",
                         (cr["activity_id"],))) or {}
            prow = r2d(q1("SELECT name FROM projects WHERE id=?", (act.get("project_id"),))) if act else None
            decision = "aprobada" if new_status == "approved" else "rechazada"
            _notify(cr["requester_id"], f"Solicitud de cambio {decision}",
                    f"{prow['name'] if prow else ''} · {act.get('activity_date','')}",
                    f"{BP}/calendar/{act.get('activity_date','')}", "change_request_resolved")
            self._json(200, {"ok": True}); return

        # projects
        m = re.match(r"^/api/users/(\d+)/certifications$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            uid = int(m.group(1))
            cert = (data.get("cert_name","") or "").strip()
            if not cert: self._json(400, {"error":"Nombre de certificación requerido"}); return
            cid = run("INSERT INTO user_certifications (user_id,cert_name,cert_code,issued_date,expires_date,notes) VALUES(?,?,?,?,?,?)",
                (uid, cert, data.get("cert_code",""), data.get("issued_date",""),
                 data.get("expires_date",""), data.get("notes","")))
            self._json(201, {"id": cid, "ok": True}); return

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
            # auto-geocode on create if address provided
            new_addr_c = data.get("address","")
            if new_addr_c:
                _glat, _glng = _geocode_address(new_addr_c)
                if _glat is not None:
                    run("UPDATE projects SET lat=?,lng=? WHERE id=?", (_glat, _glng, pid))
            new_tech_create = data.get("assigned_to")
            if new_tech_create and int(new_tech_create) != sess["id"]:
                _notify(int(new_tech_create), "Nuevo proyecto asignado",
                        f"{n} — {c}", f"{BP}/projects/{pid}", "project_assigned",
                        extra={"project": {
                            "name": n, "client": c,
                            "priority": data.get("priority","normal"),
                            "due_date": data.get("due_date",""),
                            "work_type": wt,
                        }})
            self._json(201, {"id":pid}); return

        # task photos upload
        m = re.match(r"^/api/tasks/(\d+)/photos$", rel)
        if m:
            tid = int(m.group(1))
            task_row = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if not task_row: self._json(404, {"error":"Tarea no encontrada"}); return
            proj_id = task_row["project_id"]
            try:
                _, files = _parse_multipart(self)
                if not files: self._json(400, {"error":"Sin archivos"}); return
                task_dir = os.path.join(FILES_DIR, str(proj_id), "tasks")
                os.makedirs(task_dir, exist_ok=True)
                saved = []
                for _, fobj in files.items():
                    orig = fobj.get('filename') or 'foto.jpg'
                    ext = os.path.splitext(orig)[1].lower()
                    mime_check = fobj.get('mime','') or mimetypes.guess_type(orig)[0] or ''
                    if ext in _BLOCKED_EXTS or not mime_check.startswith('image/'):
                        self._json(400, {"error": "Solo se permiten imágenes en fotos de tarea"}); return
                    safe = re.sub(r'[^\w\.\-]', '_', orig)[:120]
                    stored = f"{secrets.token_hex(8)}_{safe}"
                    with open(os.path.join(task_dir, stored), 'wb') as fp:
                        fp.write(fobj['data'])
                    pid2 = run("INSERT INTO task_photos (task_id,project_id,filename,original_name,uploaded_by) VALUES(?,?,?,?,?)",
                               (tid, proj_id, stored, orig, sess["id"]))
                    saved.append(pid2)
                self._json(201, {"ids": saved})
            except Exception as ex:
                self._json(500, {"error": str(ex)})
            return

        # project geocode
        m = re.match(r"^/api/projects/(\d+)/geocode$", rel)
        if m:
            pid = int(m.group(1))
            lat = data.get("lat"); lng = data.get("lng")
            if lat is None or lng is None: self._json(400, {"error":"lat/lng requeridos"}); return
            run("UPDATE projects SET lat=?,lng=? WHERE id=?", (float(lat), float(lng), pid))
            self._json(200, {"ok":True}); return

        # project signature
        m = re.match(r"^/api/projects/(\d+)/signature$", rel)
        if m:
            pid = int(m.group(1))
            img_data = (data.get("image") or "")
            if not img_data.startswith("data:image/"): self._json(400, {"error":"Imagen inválida"}); return
            header, b64 = img_data.split(",", 1)
            raw = base64.b64decode(b64)
            proj_dir = os.path.join(FILES_DIR, str(pid))
            os.makedirs(proj_dir, exist_ok=True)
            filename = f"firma_cliente_{_date.today().isoformat()}.png"
            with open(os.path.join(proj_dir, filename), 'wb') as fp:
                fp.write(raw)
            run("INSERT OR REPLACE INTO project_files (project_id,filename,original_name,mimetype,size_bytes,uploaded_by,notes) VALUES(?,?,?,?,?,?,?)",
                (pid, filename, "Firma cliente", "image/png", len(raw), sess["id"], "Firma digital del cliente"))
            self._json(200, {"ok": True}); return

        # notifications mark read
        if rel == "/api/notifications/read_all":
            run("UPDATE notifications SET read=1 WHERE user_id=?", (sess["id"],))
            self._json(200, {"ok":True}); return
        m = re.match(r"^/api/notifications/(\d+)/read$", rel)
        if m:
            run("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (int(m.group(1)), sess["id"]))
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

        # kit recommendations
        m = re.match(r"^/api/projects/(\d+)/kit$", rel)
        if m:
            pid = int(m.group(1))
            item_name = (data.get("item_name","") or "").strip()
            if not item_name: self._json(400, {"error":"Descripción requerida"}); return
            kid = run("""INSERT INTO project_kit
                (project_id,added_by,category,item_name,quantity,unit,notes,status)
                VALUES(?,?,?,?,?,?,?,?)""",
                (pid, sess["id"],
                 data.get("category","other"), item_name,
                 str(data.get("quantity","1")), data.get("unit","uds"),
                 data.get("notes",""), "pending"))
            self._json(201, {"id":kid}); return

        # task comments
        m = re.match(r"^/api/tasks/(\d+)/comments$", rel)
        if m:
            tid = int(m.group(1))
            body = (data.get("body","") or "").strip()
            if not body: self._json(400, {"error":"Texto requerido"}); return
            task_r = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if not task_r: self._json(404, {"error":"Tarea no encontrada"}); return
            cid = run("INSERT INTO task_comments (task_id,project_id,user_id,body) VALUES(?,?,?,?)",
                (tid, task_r["project_id"], sess["id"], body))
            self._json(201, {"id":cid}); return

        # task dependencies (replace all deps for this task)
        m = re.match(r"^/api/tasks/(\d+)/dependencies$", rel)
        if m:
            tid = int(m.group(1))
            task_r = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if not task_r: self._json(404, {"error":"Tarea no encontrada"}); return
            new_deps = [int(d) for d in (data.get("deps") or []) if d != tid]
            run("DELETE FROM task_dependencies WHERE task_id=?", (tid,))
            for dep_id in new_deps:
                try:
                    run("INSERT OR IGNORE INTO task_dependencies (task_id,depends_on) VALUES(?,?)", (tid, dep_id))
                except Exception:
                    pass
            self._json(200, {"ok":True}); return

        # templates
        if rel == "/api/templates":
            if sess.get("role") not in ("admin","backoffice"):
                self._json(403, {"error":"Forbidden"}); return
            tname = (data.get("name","") or "").strip()
            if not tname: self._json(400, {"error":"Nombre requerido"}); return
            tid = run("""INSERT INTO project_templates
                (name,description,work_type,estimated_hours,tasks_json,created_by)
                VALUES(?,?,?,?,?,?)""",
                (tname, data.get("description",""), data.get("work_type","proyecto"),
                 float(data.get("estimated_hours") or 0),
                 data.get("tasks_json","[]"), sess["id"]))
            self._json(201, {"id":tid}); return

        m = re.match(r"^/api/templates/(\d+)/apply$", rel)
        if m:
            tmpl_id = int(m.group(1))
            tpl = r2d(q1("SELECT * FROM project_templates WHERE id=?", (tmpl_id,)))
            if not tpl: self._json(404, {"error":"Plantilla no encontrada"}); return
            pname = (data.get("name","") or "").strip()
            pclient = (data.get("client","") or "").strip()
            if not pname or not pclient: self._json(400, {"error":"Nombre y cliente requeridos"}); return
            new_pid = run("""INSERT INTO projects
                (name,client,description,status,priority,work_type,estimated_hours,
                 start_date,due_date,assigned_to,created_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (pname, pclient, tpl.get("description",""), "active", "normal",
                 tpl.get("work_type","proyecto"), tpl.get("estimated_hours",0),
                 data.get("start_date",""), data.get("due_date",""),
                 data.get("assigned_to") or None, sess["id"]))
            try:
                tasks_j = json.loads(tpl.get("tasks_json","[]") or "[]")
                for t in tasks_j:
                    run("""INSERT INTO tasks (project_id,title,description,status,priority,created_by,updated_at)
                        VALUES(?,?,?,?,?,?,datetime('now'))""",
                        (new_pid, t.get("title","Tarea"), t.get("description",""),
                         "pending", t.get("priority","normal"), sess["id"]))
            except Exception:
                pass
            self._json(201, {"id":new_pid}); return

        # project comments
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
                (project_id,title,description,status,priority,start_date,due_date,created_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,datetime('now'))""",
                (pid,t,data.get("description",""),data.get("status","pending"),
                 data.get("priority","normal"),data.get("start_date",""),
                 data.get("due_date",""),sess["id"]))
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
            techs = max(1, int(data.get("technicians") or 1))
            lid = run("INSERT INTO project_logs (project_id,user_id,body,hours,technicians) VALUES(?,?,?,?,?)",
                      (pid, sess["id"], body, hours, techs))
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
                (code,name,description,unit,stock_warehouse,stock_field,stock_min,category,unit_cost,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))""",
                (code,name,data.get("description",""),data.get("unit","ud"),
                 int(data.get("stock_warehouse") or 0),int(data.get("stock_field") or 0),
                 int(data.get("stock_min") or 0),data.get("category",""),
                 float(data.get("unit_cost") or 0)))
            self._json(201, {"id":mid}); return

        # create location
        if rel == "/api/locations":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            code = (data.get("code") or "").strip().upper()
            name = (data.get("name") or "").strip()
            warehouse = (data.get("warehouse") or "Almacén Principal").strip()
            if not code or not name: self._json(400, {"error":"Código y nombre requeridos"}); return
            if q1("SELECT id FROM warehouse_locations WHERE code=?", (code,)):
                self._json(400, {"error":f"Código '{code}' ya existe"}); return
            lid = run("INSERT INTO warehouse_locations (code,name,warehouse,description) VALUES (?,?,?,?)",
                      (code, name, warehouse, data.get("description","")))
            self._json(201, {"id": lid}); return

        # stock adjust with optional location
        m = re.match(r"^/api/materials/(\d+)/adjust$", rel)
        if m:
            mid = int(m.group(1))
            qty = int(data.get("qty") or 0)
            if qty == 0: self._json(400, {"error":"Cantidad 0"}); return
            mat = r2d(q1("SELECT * FROM materials WHERE id=?", (mid,)))
            if not mat: self._json(404, {"error":"Not found"}); return
            lid_raw = data.get("location_id")
            lid = int(lid_raw) if lid_raw else None
            notes = data.get("notes", "")
            if lid:
                loc = r2d(q1("SELECT id FROM warehouse_locations WHERE id=?", (lid,)))
                if not loc: self._json(404, {"error":"Ubicación no encontrada"}); return
                cur = r2d(q1("SELECT qty FROM stock_by_location WHERE material_id=? AND location_id=?", (mid, lid)))
                cur_qty = cur["qty"] if cur else 0
                new_loc_qty = cur_qty + qty
                if new_loc_qty < 0:
                    self._json(400, {"error":f"Stock insuficiente en esa ubicación ({cur_qty} disponibles)"}); return
                if cur:
                    run("UPDATE stock_by_location SET qty=?,updated_at=datetime('now') WHERE material_id=? AND location_id=?",
                        (new_loc_qty, mid, lid))
                else:
                    run("INSERT INTO stock_by_location (material_id,location_id,qty) VALUES (?,?,?)", (mid, lid, new_loc_qty))
            new_wh = mat["stock_warehouse"] + qty
            if new_wh < 0: self._json(400, {"error":"Stock total insuficiente"}); return
            run("UPDATE materials SET stock_warehouse=?,updated_at=datetime('now') WHERE id=?", (new_wh, mid))
            direction = "in" if qty > 0 else "out"
            _stock_move(mid, abs(qty), direction, "adjust", 0, sess["id"], notes, lid)
            self._json(200, {"ok":True,"new_stock":new_wh}); return

        # transfer: location-to-location or location↔field
        m = re.match(r"^/api/materials/(\d+)/transfer$", rel)
        if m:
            mid = int(m.group(1))
            qty = int(data.get("qty") or 0)
            from_loc = data.get("from_loc", "")   # location_id (int as str) or "field"
            to_loc   = data.get("to_loc", "")     # location_id (int as str) or "field"
            notes    = data.get("notes", "")
            if qty <= 0: self._json(400, {"error":"Cantidad debe ser > 0"}); return
            if from_loc == to_loc: self._json(400, {"error":"Origen y destino iguales"}); return
            mat = r2d(q1("SELECT * FROM materials WHERE id=?", (mid,)))
            if not mat: self._json(404, {"error":"Not found"}); return

            def _loc_qty(loc_id):
                r = r2d(q1("SELECT qty FROM stock_by_location WHERE material_id=? AND location_id=?", (mid, int(loc_id))))
                return r["qty"] if r else 0

            def _set_loc(loc_id, new_qty):
                cur = r2d(q1("SELECT id FROM stock_by_location WHERE material_id=? AND location_id=?", (mid, int(loc_id))))
                if cur:
                    run("UPDATE stock_by_location SET qty=?,updated_at=datetime('now') WHERE material_id=? AND location_id=?",
                        (new_qty, mid, int(loc_id)))
                else:
                    run("INSERT INTO stock_by_location (material_id,location_id,qty) VALUES (?,?,?)", (mid, int(loc_id), new_qty))

            if from_loc == "field":
                if mat["stock_field"] < qty:
                    self._json(400, {"error":f"Stock en campo insuficiente ({mat['stock_field']} disponibles)"}); return
                run("UPDATE materials SET stock_field=stock_field-?,stock_warehouse=stock_warehouse+?,updated_at=datetime('now') WHERE id=?",
                    (qty, qty, mid))
                if to_loc != "field":
                    _set_loc(to_loc, _loc_qty(to_loc) + qty)
                _stock_move(mid, qty, "in", "transfer_to_warehouse", 0, sess["id"],
                            notes or "Campo → Almacén", int(to_loc) if to_loc != "field" else None)
            elif to_loc == "field":
                fq = _loc_qty(from_loc) if from_loc else mat["stock_warehouse"]
                if from_loc and fq < qty:
                    self._json(400, {"error":f"Stock insuficiente en ubicación ({fq} disponibles)"}); return
                if mat["stock_warehouse"] < qty:
                    self._json(400, {"error":f"Stock en almacén insuficiente ({mat['stock_warehouse']} disponibles)"}); return
                if from_loc:
                    _set_loc(from_loc, fq - qty)
                run("UPDATE materials SET stock_warehouse=stock_warehouse-?,stock_field=stock_field+?,updated_at=datetime('now') WHERE id=?",
                    (qty, qty, mid))
                _stock_move(mid, qty, "out", "transfer_to_field", 0, sess["id"],
                            notes or "Almacén → Campo", int(from_loc) if from_loc else None)
            else:
                # location to location (internal transfer)
                fq = _loc_qty(from_loc)
                if fq < qty:
                    self._json(400, {"error":f"Stock insuficiente en ubicación de origen ({fq} disponibles)"}); return
                _set_loc(from_loc, fq - qty)
                _set_loc(to_loc, _loc_qty(to_loc) + qty)
                _stock_move(mid, qty, "out", "transfer_internal", int(from_loc), sess["id"],
                            notes or f"Loc {from_loc} → Loc {to_loc}", int(from_loc))
                _stock_move(mid, qty, "in", "transfer_internal", int(to_loc), sess["id"],
                            notes or f"Loc {from_loc} → Loc {to_loc}", int(to_loc))
            self._json(200, {"ok":True}); return

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
            fn = (data.get("first_name","") or "").strip()
            ln = (data.get("last_name","") or "").strip()
            dn = (data.get("display_name","") or "").strip() or (fn + (" " + ln if ln else "")).strip() or un
            pw = (data.get("password","") or "").strip()
            email = (data.get("email","") or "").strip()
            if not un or not dn: self._json(400, {"error":"Datos incompletos"}); return
            if pw and len(pw) < 8:
                self._json(400, {"error":"La contraseña debe tener al menos 8 caracteres"}); return
            if not pw and not email:
                self._json(400, {"error":"Se requiere contraseña o email para enviar activación"}); return
            if q1("SELECT id FROM users WHERE username=?", (un,)):
                self._json(400, {"error":"Usuario ya existe"}); return
            token = secrets.token_urlsafe(32) if not pw else None
            expiry = (datetime.now() + timedelta(hours=4)).isoformat() if not pw else None
            uid = run(
                "INSERT INTO users (username,pw_hash,display_name,role,active,email,show_in_planning,"
                "first_name,last_name,phone,extension,reset_token,reset_token_expiry) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (un, _hash(pw) if pw else "",
                 dn, data.get("role","technician"),
                 1 if data.get("active",1) else 0,
                 email,
                 1 if data.get("show_in_planning",1) else 0,
                 fn, ln,
                 (data.get("phone","") or "").strip(),
                 (data.get("extension","") or "").strip(),
                 token, expiry))
            resp = {"id": uid, "welcome_sent": False}
            if token and data.get("send_welcome") and email:
                from core.email_templates import tpl_welcome
                _proto = self.headers.get("X-Forwarded-Proto", "https")
                _host  = self.headers.get("Host", "localhost")
                set_pw_url = f"{_proto}://{_host}{BP}/set-password?token={token}"
                subj, html = tpl_welcome(dn, un, set_pw_url)
                werr = send_email(email, subj, html)
                if werr:
                    resp["welcome_error"] = werr
                else:
                    resp["welcome_sent"] = True
            self._json(201, resp); return

        # settings
        if rel == "/api/settings/test_email":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            to = (data.get("to","") or "").strip()
            from core.email_templates import tpl_test
            subj, html = tpl_test(to)
            err = send_email(to, subj, html)
            if err: self._json(200, {"ok":False,"error":err}); return
            self._json(200, {"ok":True}); return

        self._json(404, {"error":"Not found"})

    def do_PUT(self):
        p = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) and BP else p.path
        data = _body(self)
        sess = _get_sess(self)
        if not sess: self._json(401, {"error":"Unauthorized"}); return

        m = re.match(r"^/api/locations/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            lid = int(m.group(1))
            if not q1("SELECT id FROM warehouse_locations WHERE id=?", (lid,)):
                self._json(404, {"error":"Not found"}); return
            code = (data.get("code") or "").strip().upper()
            name = (data.get("name") or "").strip()
            if not code or not name: self._json(400, {"error":"Código y nombre requeridos"}); return
            clash = r2d(q1("SELECT id FROM warehouse_locations WHERE code=? AND id!=?", (code, lid)))
            if clash: self._json(400, {"error":f"Código '{code}' ya existe"}); return
            run("UPDATE warehouse_locations SET code=?,name=?,warehouse=?,description=?,active=? WHERE id=?",
                (code, name, (data.get("warehouse") or "Almacén Principal").strip(),
                 data.get("description",""), 1 if data.get("active", True) else 0, lid))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/projects/(\d+)$", rel)
        if m:
            pid = int(m.group(1))
            old = r2d(q1("SELECT status,assigned_to,priority,due_date,address,lat,lng FROM projects WHERE id=?", (pid,))) or {}
            new_status = data.get("status","active")
            closing = (new_status == "completed" and old.get("status") != "completed")
            closed_sql = ",closed_at=datetime('now')" if closing else ""
            new_recurrence = data.get("recurrence","none") or "none"
            run(f"""UPDATE projects SET name=?,client=?,description=?,status=?,priority=?,
                address=?,reference=?,contact_name=?,contact_phone=?,estimated_hours=?,
                start_date=?,due_date=?,assigned_to=?,work_type=?,recurrence=?,
                updated_at=datetime('now'){closed_sql} WHERE id=?""",
                (data.get("name",""),data.get("client",""),data.get("description",""),
                 new_status,data.get("priority","normal"),
                 data.get("address",""),data.get("reference",""),data.get("contact_name",""),
                 data.get("contact_phone",""),float(data.get("estimated_hours") or 0),
                 data.get("start_date",""),data.get("due_date",""),
                 data.get("assigned_to") or None,
                 data.get("work_type","proyecto") or "proyecto", new_recurrence, pid))
            # audit trail
            _audit_fields = {
                "status": (old.get("status",""), new_status),
                "priority": (old.get("priority",""), data.get("priority","normal")),
                "assigned_to": (str(old.get("assigned_to") or ""), str(data.get("assigned_to") or "")),
                "due_date": (old.get("due_date","") or "", data.get("due_date","") or ""),
            }
            for _f, (_ov, _nv) in _audit_fields.items():
                if str(_ov) != str(_nv):
                    run("INSERT INTO project_audit (project_id,user_id,field,old_value,new_value) VALUES(?,?,?,?,?)",
                        (pid, sess["id"], _f, str(_ov), str(_nv)))
            # auto-geocode if address changed or lat/lng missing
            new_addr = data.get("address","")
            if new_addr and (new_addr != (old.get("address") or "") or not old.get("lat")):
                _glat, _glng = _geocode_address(new_addr)
                if _glat is not None:
                    run("UPDATE projects SET lat=?,lng=? WHERE id=?", (_glat, _glng, pid))
            # notify if assigned_to changed (skip self-assignment)
            new_tech = data.get("assigned_to")
            if new_tech and str(new_tech) != str(old.get("assigned_to") or "") and int(new_tech) != sess["id"]:
                _notify(int(new_tech), "Nuevo proyecto asignado",
                        f"{data.get('name','')} — {data.get('client','')}",
                        f"{BP}/projects/{pid}", "project_assigned",
                        extra={"project": {
                            "name": data.get("name",""),
                            "client": data.get("client",""),
                            "priority": data.get("priority","normal"),
                            "due_date": data.get("due_date",""),
                            "work_type": data.get("work_type","proyecto"),
                        }})
            # auto-create next occurrence when completing a recurring project
            if closing and new_recurrence != "none":
                _RECUR_DAYS = {"monthly":30,"quarterly":90,"biannual":180,"annual":365}
                days = _RECUR_DAYS.get(new_recurrence, 30)
                next_start = _date.today().isoformat()
                try:
                    next_due = (_date.today() + timedelta(days=days)).isoformat()
                except Exception:
                    next_due = ""
                proj_row = r2d(q1("SELECT * FROM projects WHERE id=?", (pid,))) or {}
                _next_pid = run("""INSERT INTO projects
                    (name,client,description,status,priority,address,reference,
                     contact_name,contact_phone,estimated_hours,start_date,due_date,
                     assigned_to,created_by,work_type,recurrence,recurrence_parent_id,
                     updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                    (proj_row.get("name",""),proj_row.get("client",""),
                     proj_row.get("description",""),"active",proj_row.get("priority","normal"),
                     proj_row.get("address",""),proj_row.get("reference",""),
                     proj_row.get("contact_name",""),proj_row.get("contact_phone",""),
                     proj_row.get("estimated_hours",0),next_start,next_due,
                     proj_row.get("assigned_to"),sess["id"],
                     proj_row.get("work_type","proyecto"),new_recurrence,pid))

            resp = {"ok": True}
            if closing:
                t_row  = q1("SELECT COUNT(*) t, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) d FROM tasks WHERE project_id=?", (pid,))
                h_row  = q1("SELECT COALESCE(SUM(hours),0) FROM project_logs WHERE project_id=?", (pid,))
                wl_row = q1("SELECT COALESCE(SUM(hours),0) FROM work_logs WHERE project_id=?", (pid,))
                est_h  = float(data.get("estimated_hours") or 0)
                resp["closing_summary"] = {
                    "pid": pid,
                    "name": data.get("name",""),
                    "tasks_done": int((t_row[1] or 0)),
                    "tasks_total": int((t_row[0] or 0)),
                    "hours_estimated": est_h,
                    "hours_logged": float(h_row[0] or 0) if h_row else 0,
                    "hours_timer": float(wl_row[0] or 0) if wl_row else 0,
                }
            self._json(200, resp); return

        m = re.match(r"^/api/tasks/(\d+)$", rel)
        if m:
            tid = int(m.group(1))
            task = r2d(q1("SELECT project_id FROM tasks WHERE id=?", (tid,)))
            if not task: self._json(404, {"error":"Not found"}); return
            comp = str(_date.today()) if data.get("status") == "done" else ""
            run("""UPDATE tasks SET title=?,description=?,status=?,priority=?,
                start_date=?,due_date=?,completed_date=?,updated_at=datetime('now') WHERE id=?""",
                (data.get("title",""),data.get("description",""),data.get("status","pending"),
                 data.get("priority","normal"),data.get("start_date",""),
                 data.get("due_date",""),comp,tid))
            run("UPDATE projects SET updated_at=datetime('now') WHERE id=?", (task["project_id"],))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/checklist/(\d+)$", rel)
        if m:
            cid = int(m.group(1))
            done = 1 if data.get("done") else 0
            run("UPDATE task_checklist SET done=? WHERE id=?", (done, cid))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/work_logs/(\d+)$", rel)
        if m:
            wid = int(m.group(1))
            wl  = r2d(q1("SELECT * FROM work_logs WHERE id=?", (wid,)))
            if not wl: self._json(404, {"error":"No encontrado"}); return
            if sess.get("role") != "admin" and wl["user_id"] != sess["id"]:
                self._json(403, {"error":"Forbidden"}); return
            hours = float(data.get("hours") or 0)
            if hours <= 0 or hours > 24:
                self._json(400, {"error":"Horas inválidas (0–24)"}); return
            run("UPDATE work_logs SET hours=?,description=?,log_date=?,project_id=?,activity_id=? WHERE id=?",
                (hours, data.get("description",""),
                 data.get("log_date", wl["log_date"]),
                 int(data.get("project_id") or wl["project_id"]),
                 int(data["activity_id"]) if data.get("activity_id") else None,
                 wid))
            self._json(200, {"ok": True}); return

        m = re.match(r"^/api/materials/(\d+)$", rel)
        if m:
            mid = int(m.group(1))
            code = (data.get("code","") or "").strip()
            if q1("SELECT id FROM materials WHERE code=? AND id!=?", (code, mid)):
                self._json(400, {"error":f"Código '{code}' ya existe"}); return
            run("""UPDATE materials SET code=?,name=?,description=?,unit=?,
                stock_warehouse=?,stock_field=?,stock_min=?,category=?,unit_cost=?,
                updated_at=datetime('now') WHERE id=?""",
                (code,data.get("name",""),data.get("description",""),data.get("unit","ud"),
                 int(data.get("stock_warehouse") or 0),int(data.get("stock_field") or 0),
                 int(data.get("stock_min") or 0),data.get("category",""),
                 float(data.get("unit_cost") or 0),mid))
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

        m = re.match(r"^/api/project_kit/(\d+)$", rel)
        if m:
            kid = int(m.group(1))
            status = data.get("status","pending")
            if status not in ("pending","brought","not_needed"):
                self._json(400, {"error":"Estado inválido"}); return
            run("UPDATE project_kit SET status=? WHERE id=?", (status, kid))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/users/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            uid = int(m.group(1))
            fn = (data.get("first_name","") or "").strip()
            ln = (data.get("last_name","") or "").strip()
            dn = (data.get("display_name","") or "").strip() or (fn + (" " + ln if ln else "")).strip()
            run("UPDATE users SET display_name=?,username=?,role=?,active=?,email=?,show_in_planning=?,"
                "first_name=?,last_name=?,phone=?,extension=?,labor_rate=? WHERE id=?",
                (dn, data.get("username",""),
                 data.get("role","technician"), 1 if data.get("active",1) else 0,
                 (data.get("email","") or "").strip(),
                 1 if data.get("show_in_planning",1) else 0,
                 fn, ln,
                 (data.get("phone","") or "").strip(),
                 (data.get("extension","") or "").strip(),
                 float(data.get("labor_rate") or 0),
                 uid))
            if data.get("password"):
                if len(data["password"]) < 8:
                    self._json(400, {"error":"La contraseña debe tener al menos 8 caracteres"}); return
                run("UPDATE users SET pw_hash=? WHERE id=?", (_hash(data["password"]),uid))
            self._json(200, {"ok":True}); return

        # settings
        if rel == "/api/settings":
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            _allowed = {"smtp_host","smtp_port","smtp_user","smtp_pass","smtp_from","smtp_tls","notif_due_days"}
            for k, v in data.items():
                if k in _allowed:
                    set_setting(k, str(v))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/notif_rules/([a-z_]+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            ek = m.group(1)
            if "notify_internal" in data:
                run("UPDATE notif_rules SET notify_internal=? WHERE event_key=?",
                    (1 if data["notify_internal"] else 0, ek))
            if "notify_email" in data:
                run("UPDATE notif_rules SET notify_email=? WHERE event_key=?",
                    (1 if data["notify_email"] else 0, ek))
            self._json(200, {"ok":True}); return

        self._json(404, {"error":"Not found"})

    def do_DELETE(self):
        p = urlparse(self.path)
        rel = p.path[len(BP):] if p.path.startswith(BP) and BP else p.path
        sess = _get_sess(self)
        if not sess: self._json(401, {"error":"Unauthorized"}); return

        # notifications delete
        if rel == "/api/notifications":
            run("DELETE FROM notifications WHERE user_id=?", (sess["id"],))
            self._json(200, {"ok":True}); return
        m = re.match(r"^/api/notifications/(\d+)$", rel)
        if m:
            run("DELETE FROM notifications WHERE id=? AND user_id=?", (int(m.group(1)), sess["id"]))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/projects/(\d+)$", rel)
        if m:
            pid = int(m.group(1))
            try:
                # schedule_slots has no ON DELETE CASCADE — clear manually
                run("DELETE FROM schedule_slots WHERE project_id=?", (pid,))
                run("DELETE FROM projects WHERE id=?", (pid,))
                self._json(200, {"ok": True})
            except Exception as ex:
                self._json(500, {"error": str(ex)})
            return

        m = re.match(r"^/api/tasks/(\d+)$", rel)
        if m:
            run("DELETE FROM tasks WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/checklist/(\d+)$", rel)
        if m:
            run("DELETE FROM task_checklist WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/locations/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            lid = int(m.group(1))
            total_stock = r2d(q1("SELECT COALESCE(SUM(qty),0) s FROM stock_by_location WHERE location_id=?", (lid,)))
            if total_stock and total_stock["s"] > 0:
                self._json(400, {"error":"No se puede eliminar una ubicación con stock"}); return
            run("DELETE FROM warehouse_locations WHERE id=?", (lid,))
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
            # nullify nullable FK references before deleting
            for tbl_col in [("projects","assigned_to"),("projects","created_by"),
                            ("tasks","assigned_to"),("tasks","created_by"),
                            ("project_files","uploaded_by"),("task_photos","uploaded_by"),
                            ("assignments","added_by"),("tech_kit_assignments","added_by"),
                            ("notifications","user_id")]:
                try:
                    run(f"UPDATE {tbl_col[0]} SET {tbl_col[1]}=NULL WHERE {tbl_col[1]}=?", (uid,))
                except Exception:
                    pass
            # delete NOT NULL FK rows (cascade-like)
            for tbl_col in [("project_members","user_id"),("tech_kit","user_id"),
                            ("activities","user_id"),("work_logs","user_id"),
                            ("tech_availability","user_id"),
                            ("change_requests","requester_id"),("change_requests","admin_id"),
                            ("project_logs","user_id"),("wo_comments","user_id"),
                            ("project_audit","user_id"),
                            ("schedule_slots","user_id"),("time_entries","user_id"),
                            ("notifications","user_id")]:
                try:
                    run(f"DELETE FROM {tbl_col[0]} WHERE {tbl_col[1]}=?", (uid,))
                except Exception:
                    pass
            try:
                run("DELETE FROM users WHERE id=?", (uid,))
                self._json(200, {"ok":True})
            except Exception as ex:
                self._json(400, {"error": f"No se puede eliminar: {ex}. Desactiva el usuario en su lugar."})
            return

        m = re.match(r"^/api/certifications/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            run("DELETE FROM user_certifications WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/tech_availability/(\d+)$", rel)
        if m:
            eid = int(m.group(1))
            row = r2d(q1("SELECT user_id FROM tech_availability WHERE id=?", (eid,)))
            if not row: self._json(404, {"error":"No encontrado"}); return
            if sess.get("role") != "admin" and row["user_id"] != sess["id"]:
                self._json(403, {"error":"Forbidden"}); return
            run("DELETE FROM tech_availability WHERE id=?", (eid,))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/task_comments/(\d+)$", rel)
        if m:
            cid = int(m.group(1))
            row = r2d(q1("SELECT user_id FROM task_comments WHERE id=?", (cid,)))
            if row and (row["user_id"] == sess["id"] or sess.get("role") == "admin"):
                run("DELETE FROM task_comments WHERE id=?", (cid,))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/task_deps/(\d+)$", rel)
        if m:
            run("DELETE FROM task_dependencies WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/templates/(\d+)$", rel)
        if m:
            if sess.get("role") not in ("admin","backoffice"):
                self._json(403, {"error":"Forbidden"}); return
            run("DELETE FROM project_templates WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/activities/(\d+)$", rel)
        if m:
            if sess.get("role") != "admin": self._json(403, {"error":"Forbidden"}); return
            run("DELETE FROM activities WHERE id=?", (int(m.group(1)),))
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

        m = re.match(r"^/api/work_logs/(\d+)$", rel)
        if m:
            wid = int(m.group(1))
            wl = r2d(q1("SELECT * FROM work_logs WHERE id=?", (wid,)))
            if wl and (wl['user_id'] == sess['id'] or sess.get('role') == 'admin'):
                run("DELETE FROM work_logs WHERE id=?", (wid,))
            self._json(200, {"ok":True}); return

        m = re.match(r"^/api/task_photos/(\d+)$", rel)
        if m:
            tp = r2d(q1("SELECT * FROM task_photos WHERE id=?", (int(m.group(1)),)))
            if tp:
                fpath = os.path.join(FILES_DIR, str(tp['project_id']), "tasks", tp['filename'])
                try: os.remove(fpath)
                except: pass
                run("DELETE FROM task_photos WHERE id=?", (int(m.group(1)),))
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

        m = re.match(r"^/api/project_kit/(\d+)$", rel)
        if m:
            run("DELETE FROM project_kit WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok":True}); return

        self._json(404, {"error":"Not found"})

# ── periodic notification job ─────────────────────────────────────────────────

def _periodic_checks():
    """Run every hour: check project due dates, overdue tasks, low stock."""
    from core.notify import get_setting as _gs, _notify as _nf
    today = _date.today()
    try:
        due_days = int(_gs("notif_due_days", "2") or "2")
    except ValueError:
        due_days = 2
    deadline = today + timedelta(days=due_days)

    # 1. Projects due soon
    projects_due = rs(q(
        """SELECT id, name, client, due_date, assigned_to, priority, work_type FROM projects
           WHERE status NOT IN ('completed','cancelled')
           AND due_date != '' AND due_date IS NOT NULL
           AND date(due_date) <= ? AND date(due_date) >= ?
           AND assigned_to IS NOT NULL""",
        (str(deadline), str(today))
    ))
    for p in projects_due:
        uid = p["assigned_to"]
        url = f"{BP}/projects/{p['id']}"
        due_str = p["due_date"][:10]
        already = q1(
            "SELECT id FROM notifications WHERE user_id=? AND url=? AND created_at > datetime('now','-20 hours')",
            (uid, url)
        )
        if not already:
            try:
                days_left = (datetime.strptime(due_str, "%Y-%m-%d").date() - today).days
            except Exception:
                days_left = 0
            _nf(uid, "Proyecto próximo a vencer",
                f"{p['name']} — {p['client']} · vence {due_str}",
                url, "project_due_soon",
                extra={"project": {
                    "name": p["name"], "client": p["client"],
                    "due_date": due_str,
                    "priority": p.get("priority","normal"),
                    "work_type": p.get("work_type",""),
                }, "days_left": days_left})

    # 2. Overdue tasks (assigned project)
    overdue_tasks = rs(q(
        """SELECT t.id, t.title, t.due_date, p.id pid, p.name pname, p.assigned_to
           FROM tasks t JOIN projects p ON p.id=t.project_id
           WHERE t.status != 'done'
           AND t.due_date != '' AND t.due_date IS NOT NULL
           AND date(t.due_date) < ?
           AND p.assigned_to IS NOT NULL""",
        (str(today),)
    ))
    for t in overdue_tasks:
        uid = t["assigned_to"]
        url = f"{BP}/projects/{t['pid']}"
        already = q1(
            "SELECT id FROM notifications WHERE user_id=? AND body LIKE ? AND created_at > datetime('now','-20 hours')",
            (uid, f"%{t['title'][:30]}%")
        )
        if not already:
            _nf(uid, "Tarea vencida sin completar",
                f"{t['title']} — {t['pname']} · venció {t['due_date'][:10]}",
                url, "task_overdue",
                extra={"task_name": t["title"], "project_name": t["pname"],
                       "due_date": t["due_date"][:10]})

    # 3. Low stock — notify all admin users
    low_stock = rs(q(
        "SELECT id, code, name, stock_warehouse, stock_min FROM materials "
        "WHERE stock_min > 0 AND stock_warehouse <= stock_min"
    ))
    if low_stock:
        admins = rs(q("SELECT id FROM users WHERE role='admin' AND active=1"))
        for mat in low_stock:
            url = f"{BP}/inventory"
            body = f"{mat['name']} (cod.{mat['code']}) — stock: {mat['stock_warehouse']}, mínimo: {mat['stock_min']}"
            for adm in admins:
                already = q1(
                    "SELECT id FROM notifications WHERE user_id=? AND body LIKE ? AND created_at > datetime('now','-20 hours')",
                    (adm["id"], f"%{mat['name'][:20]}%")
                )
                if not already:
                    _nf(adm["id"], "Material con stock bajo",
                        body, url, "stock_low",
                        extra={"material_name": mat["name"],
                               "current_qty": mat["stock_warehouse"],
                               "min_qty": mat["stock_min"]})


def _start_periodic_job():
    def _loop():
        time.sleep(60)  # short delay on startup
        while True:
            try:
                _periodic_checks()
            except Exception as e:
                print(f"[notify-job] error: {e}")
            time.sleep(3600)
    t = threading.Thread(target=_loop, daemon=True, name="notif-job")
    t.start()


# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    _start_periodic_job()
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"NuvoDesk v2 → http://localhost:{PORT}{BP}/  (admin/admin)")
    server.serve_forever()
