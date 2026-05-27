#!/usr/bin/env python3
"""NuvoDesk v3 — Nuvolink field project & materials management."""

import os, json, sqlite3, re, calendar as _cal, mimetypes, secrets, base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote_plus
from datetime import datetime, date as _date, timedelta

from core.db import (
    PORT, BP, DATA_DIR, DB_PATH, FILES_DIR,
    new_sess as _new_sess, get_sess as _get_sess, del_sess as _del_sess,
    db, q, q1, run, rs, r2d, _dblock,
)
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration,
    _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
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


# ── shell ─────────────────────────────────────────────────────────────────────

from web.layout import _NAV_ICONS, _shell
from web.pages.misc import _login_page, _download_page
from web.pages.dashboard import _dashboard
from web.pages.projects import _projects_page, _build_kanban, _build_file_grid
def _project_detail(user, pid):
    p = r2d(q1("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to WHERE p.id=?""", (pid,)))
    if not p: return None

    tasks = rs(q("""SELECT t.*,
        (SELECT COUNT(*) FROM task_checklist c WHERE c.task_id=t.id) cl_t,
        (SELECT COUNT(*) FROM task_checklist c WHERE c.task_id=t.id AND c.done=1) cl_d,
        (SELECT COUNT(*) FROM task_photos tp WHERE tp.task_id=t.id) photo_count
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

    kit_recs = rs(q("""SELECT pk.*,u.display_name uname
        FROM project_kit pk LEFT JOIN users u ON u.id=pk.added_by
        WHERE pk.project_id=? ORDER BY pk.created_at DESC""", (pid,)))

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
    ph_row = q1("SELECT COALESCE(SUM(hours),0), COALESCE(SUM(hours*technicians),0) FROM project_logs WHERE project_id=?", (pid,))
    h_logged = ph_row[0] if ph_row else 0
    ph_logged = ph_row[1] if ph_row else 0
    h_est = p.get("estimated_hours") or 0
    h_pct = min(100, int(ph_logged/h_est*100)) if h_est else 0
    hours_html = ""
    if h_est or ph_logged:
        ph_extra = (f' <span class="muted" style="font-size:.78rem">({ph_logged:.1f} person-h)</span>'
                    if ph_logged != h_logged else "")
        hours_html = (f'<div class="kpi" style="margin-bottom:16px">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
            f'<div><div class="val" style="font-size:1.2rem">{h_logged}h{ph_extra}'
            f'{(" <span class=muted style=font-size:.9rem>/ " + str(h_est) + "h</span>") if h_est else ""}</div>'
            f'<div class="lbl">Horas registradas{" · " + str(ph_logged) + " person-horas" if ph_logged != h_logged else ""}</div></div></div>'
            f'{"<div class=progress style=margin-top:8px><div class=progress-bar style=width:" + str(h_pct) + "%></div></div>" if h_est else ""}</div>')

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

    today_str = _date.today().isoformat()
    time_tab_html = f"""{timer_start_html}
<details style="margin-bottom:16px">
  <summary style="cursor:pointer;font-size:.875rem;font-weight:600;color:var(--muted);padding:8px 0;user-select:none">
    + Registrar horas manualmente
  </summary>
  <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;padding:12px 0 4px">
    <div class="field" style="margin:0;flex:0 0 140px">
      <label>Fecha</label>
      <input type="date" id="ml-date" value="{today_str}">
    </div>
    <div class="field" style="margin:0;flex:0 0 100px">
      <label>Horas</label>
      <input type="number" id="ml-hours" min="0.25" step="0.25" value="1" placeholder="1.5">
    </div>
    <div class="field" style="margin:0">
      <label>Tipo</label>
      <select id="ml-type">
        <option value="work">🔧 Trabajo</option>
        <option value="travel">🚗 Desplazamiento</option>
        <option value="wait">⏳ Espera</option>
      </select>
    </div>
    <div class="field" style="margin:0;flex:1;min-width:160px">
      <label>Notas</label>
      <input id="ml-notes" placeholder="Descripción del trabajo...">
    </div>
    <button class="btn btn-primary btn-sm" onclick="addManualLog()">Registrar</button>
  </div>
</details>
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
  <h2>📦 Recomendaciones de material</h2>
  <button class="btn btn-primary btn-sm" onclick="openKitRecModal()">+ Añadir</button>
</div>
<p class="muted" style="font-size:.82rem;margin-bottom:16px;line-height:1.5">
  Recomendaciones del jefe de proyecto — materiales que el equipo de campo debería llevar.
  No generan movimiento de almacén, son avisos de preparación.
</p>
<div class="card">
{kit_rows_html if kit_rows_html else "<p class='muted' style='text-align:center;padding:24px'>Sin recomendaciones todavía — añade la primera.</p>"}
</div>"""

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
    <button class="btn btn-ghost btn-sm" onclick="openSigModal()">✍️ Firma cliente</button>
    <button class="btn btn-ghost btn-sm" onclick="editProject({_jattr(safe_proj)})">✏️ Editar</button>
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
  <button class="tab-btn" onclick="showTab('kit',this)">📦 Material ({len(kit_recs)})</button>
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
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:0;flex-wrap:wrap">
    <div style="flex:0 0 120px"><label>Horas trabajadas</label><input type="number" id="log-hours" min="0" max="24" step="0.5" value="0" placeholder="h"></div>
    <div style="flex:0 0 140px"><label>Nº técnicos presentes</label>
      <select id="log-techs">
        <option value="1">1 técnico</option>
        <option value="2">2 técnicos</option>
        <option value="3">3 técnicos</option>
        <option value="4">4 técnicos</option>
        <option value="5">5 técnicos</option>
        <option value="6">6 técnicos</option>
      </select>
    </div>
    <div class="muted" id="log-ph-preview" style="font-size:.8rem;margin-top:18px"></div>
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

<!-- TAB KIT MATERIAL -->
<div id="tab-kit" class="tab-pane">
{kit_tab_html}
</div>

<!-- TAB INFO -->
<div id="tab-info" class="tab-pane">
<div class="card">
  <table><tbody>{info_rows or "<tr><td class='muted'>Sin datos adicionales</td></tr>"}</tbody></table>
</div>
</div>

<!-- MODAL kit recomendación -->
<div class="modal-bg" id="kit-rec-modal">
<div class="modal" style="max-width:460px">
  <h2>📦 Añadir recomendación de material</h2>
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
    <button class="btn btn-primary" onclick="doAddKitRec()">Añadir recomendación</button>
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
function addManualLog(){{
  var date=document.getElementById('ml-date').value;
  var hours=parseFloat(document.getElementById('ml-hours').value);
  if(!date||!hours||hours<=0){{alert('Fecha y horas son obligatorias');return;}}
  fetch(bp+'/api/projects/'+pid+'/time/log',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{date:date,hours:hours,
      entry_type:document.getElementById('ml-type').value,
      notes:document.getElementById('ml-notes').value}})}})
    .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'Error');}});}})
    .then(function(){{location.reload();}})
    .catch(function(err){{alert(err.message);}});
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
      else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function delTaskPhoto(id){{
  if(!confirm('¿Eliminar esta foto?')) return;
  fetch(bp+'/api/task_photos/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)loadTaskPhotos(_photoTaskId);}});
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
  if(!_sigHasMark){{alert('Por favor dibuja la firma antes de guardar');return;}}
  var dataUrl=document.getElementById('sig-canvas').toDataURL('image/png');
  fetch(bp+'/api/projects/'+pid+'/signature',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{image:dataUrl}})}})
    .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'Error');}});}})
    .then(function(){{closeSigModal();alert('Firma guardada correctamente');location.reload();}})
    .catch(function(err){{alert(err.message);}});
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
  if(!name){{alert('Escribe una descripción');return;}}
  fetch(bp+'/api/projects/'+pid+'/kit',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{
      category:document.getElementById('kr-cat').value,
      item_name:name,
      quantity:document.getElementById('kr-qty').value||'1',
      unit:document.getElementById('kr-unit').value||'uds',
      notes:document.getElementById('kr-notes').value
    }})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function kitSetStatus(id,status){{
  fetch(bp+'/api/project_kit/'+id,{{method:'PATCH',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{status:status}})}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
function delKitRec(id){{
  if(!confirm('¿Eliminar esta recomendación?')) return;
  fetch(bp+'/api/project_kit/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
</script>"""
    return _shell("projects", user, content)


# ── inventory ─────────────────────────────────────────────────────────────────

from web.pages.inventory import _inventory_page
from web.pages.kit import _kit_page
from web.pages.users import _users_page
from web.pages.reports import _project_report, _project_report_md
from web.pages.calendar import _calendar_page, _calendar_day
from web.pages.workload import _workload_page
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
            sw = """self.addEventListener('fetch',function(e){});"""
            self._send(200, sw, "application/javascript"); return

        sess = _get_sess(self)
        if not sess: self._redirect(f"{BP}/login"); return

        if rel in ("/", "/dashboard"):
            self._send(200, _dashboard(sess)); return
        if rel == "/projects":
            self._send(200, _projects_page(sess, qs.get("status",[""])[0], qs.get("view",["cards"])[0], qs.get("new",[""])[0], qs.get("tech",[""])[0], qs.get("wtype",[""])[0])); return
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
        m = re.match(r"^/api/tasks/(\d+)/photos$", rel)
        if m:
            tid = int(m.group(1))
            self._json(200, rs(q("SELECT * FROM task_photos WHERE task_id=? ORDER BY created_at DESC", (tid,)))); return
        if rel == "/api/notifications":
            notifs = rs(q("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (sess["id"],)))
            unread = q1("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (sess["id"],))[0]
            self._json(200, {"notifications": notifs, "unread": unread}); return
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

        m = re.match(r"^/api/projects/(\d+)/time/log$", rel)
        if m:
            pid = int(m.group(1))
            date_str = (data.get("date") or "").strip()
            hours = float(data.get("hours") or 0)
            if not date_str or hours <= 0:
                self._json(400, {"error":"Fecha y horas requeridas"}); return
            start_dt = datetime.fromisoformat(f"{date_str}T08:00:00")
            end_dt   = start_dt + timedelta(hours=hours)
            eid = run("""INSERT INTO time_entries (project_id,user_id,started_at,ended_at,entry_type,notes)
                VALUES(?,?,?,?,?,?)""",
                (pid, sess["id"],
                 start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                 end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                 data.get("entry_type","work"), data.get("notes","")))
            self._json(201, {"id":eid}); return

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
            old = r2d(q1("SELECT status,assigned_to FROM projects WHERE id=?", (pid,))) or {}
            new_status = data.get("status","active")
            closing = (new_status == "completed" and old.get("status") != "completed")
            closed_sql = ",closed_at=datetime('now')" if closing else ""
            run(f"""UPDATE projects SET name=?,client=?,description=?,status=?,priority=?,
                address=?,reference=?,contact_name=?,contact_phone=?,estimated_hours=?,
                start_date=?,due_date=?,assigned_to=?,work_type=?,updated_at=datetime('now'){closed_sql} WHERE id=?""",
                (data.get("name",""),data.get("client",""),data.get("description",""),
                 new_status,data.get("priority","normal"),
                 data.get("address",""),data.get("reference",""),data.get("contact_name",""),
                 data.get("contact_phone",""),float(data.get("estimated_hours") or 0),
                 data.get("start_date",""),data.get("due_date",""),
                 data.get("assigned_to") or None,
                 data.get("work_type","proyecto") or "proyecto", pid))
            # notify if assigned_to changed
            new_tech = data.get("assigned_to")
            if new_tech and str(new_tech) != str(old.get("assigned_to") or ""):
                run("INSERT INTO notifications (user_id,title,body,url) VALUES(?,?,?,?)",
                    (int(new_tech), "Nuevo proyecto asignado",
                     f"{data.get('name','')} — {data.get('client','')}",
                     f"{BP}/projects/{pid}"))
            resp = {"ok": True}
            if closing:
                t_row = q1("SELECT COUNT(*) t, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) d FROM tasks WHERE project_id=?", (pid,))
                h_row = q1("SELECT COALESCE(SUM(hours),0), COALESCE(SUM(estimated_hours),0) FROM project_logs pl, projects p WHERE pl.project_id=? AND p.id=?", (pid,pid))
                timer_row = q1("""SELECT COALESCE(SUM(CASE WHEN ended_at IS NOT NULL
                    THEN (julianday(ended_at)-julianday(started_at))*3600 ELSE 0 END),0)
                    FROM time_entries WHERE project_id=? AND ended_at IS NOT NULL""", (pid,))
                est_h = float(data.get("estimated_hours") or 0)
                resp["closing_summary"] = {
                    "pid": pid,
                    "name": data.get("name",""),
                    "tasks_done": int((t_row[1] or 0)),
                    "tasks_total": int((t_row[0] or 0)),
                    "hours_estimated": est_h,
                    "hours_logged": float(h_row[0] or 0) if h_row else 0,
                    "hours_timer": round(float(timer_row[0] or 0) / 3600, 1) if timer_row else 0,
                }
            self._json(200, resp); return

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

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"NuvoDesk v2 → http://localhost:{PORT}{BP}/  (admin/admin)")
    server.serve_forever()
