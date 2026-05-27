"""Dashboard page."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
)
from web.layout import _shell

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

    due_week = rs(q("""SELECT p.id,p.name,p.client,p.priority,p.status,p.due_date,
        u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to
        WHERE p.status NOT IN ('completed','cancelled')
          AND p.due_date!='' AND p.due_date>=date('now') AND p.due_date<=date('now','+7 days')
        ORDER BY p.due_date ASC LIMIT 8"""))

    recent = rs(q("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to
        ORDER BY p.updated_at DESC LIMIT 8"""))


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


    dw_html = ""
    if due_week:
        dw_rows = "".join(
            f"<tr><td><a href='{BP}/projects/{p['id']}'>{_esc(p['name'])}</a>"
            f"<br><span class='muted' style='font-size:.75rem'>{_esc(p['client'])}</span></td>"
            f"<td class='muted'>{_esc((p['due_date'] or '')[:10])}</td>"
            f"<td>{_pbadge(p['priority'])}</td>"
            f"<td class='muted col-m-hide'>{_esc(p['tech'] or '—')}</td></tr>"
            for p in due_week)
        dw_html = f"""<div class="card" style="border-left:4px solid var(--blue)">
  <h2>📅 Vence esta semana ({len(due_week)})</h2>
  <div class="tbl-wrap"><table><thead><tr><th>Proyecto</th>
    <th>Límite</th><th>Prioridad</th><th class="col-m-hide">Técnico</th>
  </tr></thead><tbody>{dw_rows}</tbody></table></div>
</div>"""

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

    content = (f'<div class="toolbar"><h1>Dashboard</h1>'
               f'<a href="{BP}/projects?new=averia" class="btn btn-primary">⚡ Avería rápida</a></div>'
               f'{kpis}{dw_html}{low_html}{od_html}{rp_html}')
    return _shell("dashboard", user, content)

# ── projects list ─────────────────────────────────────────────────────────────
