"""Dashboard page."""
from datetime import date as _date
from core.db import BP, q, q1, rs, r2d
from core.helpers import (
    _esc, _badge2, _pbadge, _kpi_card, _triage_item, _fd,
)
from web.layout import _shell


def _my_day(user):
    uid = user["id"]
    today = _date.today().isoformat()

    my_projects = rs(q("""SELECT p.*,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') task_d,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id) task_t
        FROM projects p WHERE p.assigned_to=? AND p.status='active'
        ORDER BY CASE p.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END""", (uid,)))

    my_tasks = rs(q("""SELECT t.*,p.name pname,p.id pid FROM tasks t
        JOIN projects p ON p.id=t.project_id
        WHERE t.assigned_to=? AND t.status NOT IN ('done','cancelled')
        ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
        t.due_date ASC LIMIT 20""", (uid,)))

    hours_today = q1("""SELECT COALESCE(SUM(
        (julianday(ended_at)-julianday(started_at))*24),0)
        FROM time_entries WHERE user_id=? AND ended_at IS NOT NULL
        AND date(started_at)=?""", (uid, today))
    h_today = round(float(hours_today[0] or 0), 1)

    active_te = r2d(q1("""SELECT te.*,p.name pname FROM time_entries te
        JOIN projects p ON p.id=te.project_id
        WHERE te.user_id=? AND te.ended_at IS NULL""", (uid,)))

    timer_html = ""
    if active_te:
        started_iso = (active_te.get("started_at") or "").replace(" ", "T")
        timer_html = f"""<div class="card" style="border-left:4px solid var(--s-ok);margin-bottom:0">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <span class="timer-pulse"></span>
    <div>
      <div style="font-size:.75rem;font-weight:700;color:var(--s-ok);text-transform:uppercase">Jornada activa</div>
      <div class="fw7">{_esc(active_te.get("pname",""))}</div>
    </div>
    <div id="md-elapsed" style="font-size:1.2rem;font-weight:700;font-variant-numeric:tabular-nums;color:var(--s-ok);margin-left:auto">—</div>
  </div>
</div>
<script>
(function(){{var s=new Date("{started_iso}");function t(){{var el=document.getElementById('md-elapsed');if(!el)return;var d=Math.floor((Date.now()-s.getTime())/1000);el.textContent=(Math.floor(d/3600)>0?Math.floor(d/3600)+'h ':'')+String(Math.floor((d%3600)/60)).padStart(2,'0')+'m '+String(d%60).padStart(2,'0')+'s';}}t();setInterval(t,1000);}}());
</script>"""

    proj_rows = ""
    for p in my_projects:
        pct = int(p['task_d']/p['task_t']*100) if p['task_t'] else 0
        proj_rows += (f'<tr><td><a href="{BP}/projects/{p["id"]}" class="fw7">{_esc(p["name"])}</a>'
            f'<br><span class="muted" style="font-size:.75rem">{_esc(p["client"])}</span></td>'
            f'<td>{_pbadge(p["priority"])}</td>'
            f'<td class="muted">{_fd(p.get("due_date") or "")}</td>'
            f'<td style="min-width:90px"><div class="progress" style="display:inline-block;width:60px;vertical-align:middle">'
            f'<div class="progress-bar" style="width:{pct}%"></div></div>'
            f'<span class="muted" style="font-size:.72rem;margin-left:4px">{pct}%</span></td>'
            f'<td><a href="{BP}/projects/{p["id"]}" class="btn btn-ghost btn-sm">→</a></td></tr>')

    task_rows = ""
    for t in my_tasks:
        overdue_cls = ' class="text-red"' if t.get('due_date') and t['due_date'] < today else ''
        task_rows += (f'<tr><td>{_badge2(t["status"])}</td>'
            f'<td class="fw7">{_esc(t["title"])}</td>'
            f'<td><a href="{BP}/projects/{t["pid"]}" style="color:var(--muted);font-size:.8rem">{_esc(t["pname"])}</a></td>'
            f'<td{overdue_cls} class="muted" style="font-size:.8rem">{_fd(t.get("due_date") or "")}</td></tr>')

    kpis = (
        '<div class="nd-kpi-strip" style="margin-bottom:16px">'
        + _kpi_card(len(my_projects), "Proyectos activos", "brand", "📁")
        + _kpi_card(len(my_tasks),    "Tareas pendientes", "warn",  "📋")
        + _kpi_card(f"{h_today}h",    "Horas hoy",         "ok",    "⏱")
        + '</div>'
    )

    averia_modal_day = f"""
<div class="modal-bg" id="averia-modal">
<div class="modal">
  <h2>⚡ Avería rápida</h2>
  <form id="averia-form">
  <div class="form-row">
    <div><label>Cliente *</label><input id="av-client" required placeholder="Nombre del cliente"></div>
  </div>
  <div class="form-row">
    <div><label>Descripción *</label><textarea id="av-desc" required rows="3" placeholder="Describe brevemente la avería"></textarea></div>
  </div>
  <div class="form-row">
    <div><label>Teléfono contacto</label><input id="av-phone" type="tel" placeholder="Opcional"></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('averia-modal').classList.remove('open')">Cancelar</button>
    <button type="submit" class="btn btn-primary">⚡ Crear avería</button>
  </div>
  </form>
</div></div>
<script>
var _bp='{BP}';
function openAveriaRapida(){{document.getElementById('averia-modal').classList.add('open');document.getElementById('av-client').focus();}}
document.getElementById('averia-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
document.getElementById('averia-form').onsubmit=function(e){{
  e.preventDefault();
  fetch(_bp+'/api/projects',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:'Avería '+document.getElementById('av-client').value,
      client:document.getElementById('av-client').value,
      description:document.getElementById('av-desc').value,
      contact_phone:document.getElementById('av-phone').value,
      work_type:'averia',status:'active',priority:'urgent'}})}})
    .then(function(r){{return r.json();}})
    .then(function(d){{if(d.id)window.location=_bp+'/projects/'+d.id;else Toast.show('Error al crear avería','err');}});
}};
</script>"""

    content = f"""<div class="toolbar"><h1>Mi jornada</h1>
  <button class="btn btn-primary" onclick="openAveriaRapida()">⚡ Avería rápida</button></div>
{kpis}
{timer_html}
<div class="card">
  <div class="toolbar"><h2>Mis proyectos activos</h2>
    <a href="{BP}/projects" class="btn btn-ghost btn-sm">Ver todos →</a></div>
  {"<div class='tbl-wrap'><table><thead><tr><th>Proyecto</th><th>Prioridad</th><th>Límite</th><th>Avance</th><th></th></tr></thead><tbody>" + proj_rows + "</tbody></table></div>" if proj_rows else "<p class='muted' style='text-align:center;padding:24px'>Sin proyectos activos asignados</p>"}
</div>
<div class="card">
  <h2>Mis tareas pendientes</h2>
  {"<div class='tbl-wrap'><table><thead><tr><th>Estado</th><th>Tarea</th><th>Proyecto</th><th>Límite</th></tr></thead><tbody>" + task_rows + "</tbody></table></div>" if task_rows else "<p class='muted' style='text-align:center;padding:24px'>Sin tareas pendientes asignadas</p>"}
</div>"""
    return _shell("dashboard", user, content + averia_modal_day, title="Mi jornada")


def _dashboard(user):
    if user.get("role") not in ("admin", "backoffice"):
        return _my_day(user)

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

    today = _date.today().isoformat()

    blocked_tasks = rs(q("""SELECT t.id,t.title,t.due_date,p.id pid,p.name pname,u.display_name tech
        FROM tasks t JOIN projects p ON p.id=t.project_id
        LEFT JOIN users u ON u.id=t.assigned_to
        WHERE t.status='blocked' AND p.status='active'
        ORDER BY t.due_date ASC LIMIT 10"""))

    blocked_projects = rs(q("""SELECT DISTINCT p.id FROM projects p
        JOIN tasks t ON t.project_id=p.id
        WHERE t.status='blocked' AND p.status='active'"""))
    blocked_ids = {p["id"] for p in (blocked_projects or [])}

    urgent_overdue_projs = rs(q("""SELECT id, due_date FROM projects
        WHERE status='active' AND priority='urgent'
          AND due_date!='' AND due_date<date('now')"""))
    urgent_overdue_ids = {p["id"] for p in (urgent_overdue_projs or [])}

    fuego_ids = blocked_ids | urgent_overdue_ids
    n_fuego   = len(fuego_ids)

    today_tasks = rs(q("""SELECT DISTINCT project_id FROM tasks
        WHERE status NOT IN ('done','cancelled') AND due_date=date('now')"""))
    n_hoy = len(today_tasks or [])

    n_semana = len(due_week)

    triage_html = (
        f'<div class="nd-triage-rail">'
        + _triage_item(n_fuego,  "FUEGO",        f"{n_fuego} proyectos críticos únicos",   "err",   f"{BP}/projects?filter=urgent")
        + _triage_item(n_hoy,    "HOY",          f"{n_hoy} tareas con vencimiento hoy",     "warn",  f"{BP}/projects?filter=today")
        + _triage_item(n_semana, "ESTA SEMANA",  f"{n_semana} proyectos vencen en 7 días",  "brand", f"{BP}/projects?filter=week")
        + '</div>'
    )

    kpis = (
        '<div class="nd-kpi-strip">'
        + _kpi_card(ps.get('active') or 0,  "Proyectos activos",  "brand", "📁", f"Total: {ps.get('t') or 0}")
        + _kpi_card(n_semana,                "Vencen esta semana", "warn",  "⏰", f"{n_fuego} urgentes")
        + _kpi_card(ts.get('blocked') or 0, "Tareas bloqueadas",  "err",   "🚫")
        + _kpi_card(ps.get('done') or 0,    "Completados",        "ok",    "✅")
        + '</div>'
    )

    low_html = ""
    if low_stock:
        rows = "".join(f"<tr><td><span class='chip'>{_esc(m['code'])}</span></td>"
            f"<td>{_esc(m['name'])}</td>"
            f"<td class='text-red fw7'>{m['stock_warehouse']}</td>"
            f"<td class='muted'>{m['stock_min']}</td>"
            f"<td class='muted'>{_esc(m['unit'])}</td></tr>" for m in low_stock)
        low_html = f"""<div class="card" style="border-left:4px solid var(--s-warn)">
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
            f"<td>{_badge2(t['status'])}</td></tr>" for t in overdue)
        od_html = f"""<div class="card" style="border-left:4px solid var(--s-err)">
  <h2>🕒 Tareas vencidas ({len(overdue)})</h2>
  <div class="tbl-wrap"><table><thead><tr><th>Proyecto</th><th>Tarea</th>
    <th>Vencimiento</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div>
</div>"""

    dw_html = ""
    if due_week:
        dw_rows = "".join(
            f"<tr><td><a href='{BP}/projects/{p['id']}'>{_esc(p['name'])}</a>"
            f"<br><span class='muted' style='font-size:.75rem'>{_esc(p['client'])}</span></td>"
            f"<td class='muted'>{_fd(p.get('due_date') or '')}</td>"
            f"<td>{_pbadge(p['priority'])}</td>"
            f"<td class='muted col-m-hide'>{_esc(p['tech'] or '—')}</td></tr>"
            for p in due_week)
        dw_html = f"""<div class="card" style="border-left:4px solid var(--brand)">
  <h2>📅 Vence esta semana ({len(due_week)})</h2>
  <div class="tbl-wrap"><table><thead><tr><th>Proyecto</th>
    <th>Límite</th><th>Prioridad</th><th class="col-m-hide">Técnico</th>
  </tr></thead><tbody>{dw_rows}</tbody></table></div>
</div>"""

    rp_rows = "".join(f"<tr>"
        f"<td><a href='{BP}/projects/{p['id']}' class='fw7'>{_esc(p['name'])}</a>"
        f"<br><span class='muted' style='font-size:.75rem'>{_esc(p['client'])}</span></td>"
        f"<td>{_badge2(p['status'])}</td><td class='col-m-hide'>{_pbadge(p['priority'])}</td>"
        f"<td class='muted col-m-hide'>{_esc(p['tech'] or '—')}</td>"
        f"<td class='muted col-m-hide'>{_fd(p.get('due_date') or '')}</td></tr>" for p in recent)

    rp_html = f"""<div class="card">
  <div class="toolbar"><h2>Proyectos recientes</h2>
    <a href="{BP}/projects" class="btn btn-ghost btn-sm">Ver todos →</a></div>
  <div class="tbl-wrap"><table><thead><tr><th>Proyecto</th><th>Estado</th>
    <th class="col-m-hide">Prioridad</th><th class="col-m-hide">Técnico</th>
    <th class="col-m-hide">Límite</th></tr></thead><tbody>{rp_rows}</tbody></table></div>
</div>"""

    bt_html = ""
    if blocked_tasks:
        bt_rows = "".join(
            f"<tr>"
            f"<td><a href='{BP}/projects/{t['pid']}'>{_esc(t['pname'])}</a></td>"
            f"<td class='fw7'>{_esc(t['title'])}</td>"
            f"<td class='muted col-m-hide'>{_esc(t['tech'] or '—')}</td>"
            f"<td class='muted col-m-hide'>{_fd(t.get('due_date') or '')}</td>"
            f"<td><button class='btn btn-ghost btn-sm' onclick='unblockTask({t['id']})'>▶ Desbloquear</button></td></tr>"
            for t in blocked_tasks)
        bt_html = f"""<div class="card" style="border-left:4px solid var(--s-err)">
  <h2>🚫 Tareas bloqueadas ({len(blocked_tasks)})</h2>
  <div class="tbl-wrap"><table><thead><tr><th>Proyecto</th><th>Tarea</th>
    <th class="col-m-hide">Técnico</th><th class="col-m-hide">Límite</th><th></th>
  </tr></thead><tbody>{bt_rows}</tbody></table></div>
</div>"""

    averia_modal = f"""
<div class="modal-bg" id="averia-modal">
<div class="modal">
  <h2>⚡ Avería rápida</h2>
  <form id="averia-form">
  <div class="form-row">
    <div><label>Cliente *</label><input id="av-client" required placeholder="Nombre del cliente"></div>
  </div>
  <div class="form-row">
    <div><label>Descripción *</label><textarea id="av-desc" required rows="3" placeholder="Describe brevemente la avería"></textarea></div>
  </div>
  <div class="form-row">
    <div><label>Teléfono contacto</label><input id="av-phone" type="tel" placeholder="Opcional"></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('averia-modal').classList.remove('open')">Cancelar</button>
    <button type="submit" class="btn btn-primary">⚡ Crear avería</button>
  </div>
  </form>
</div></div>
<script>
var _bp='{BP}';
function openAveriaRapida(){{document.getElementById('averia-modal').classList.add('open');document.getElementById('av-client').focus();}}
document.getElementById('averia-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
document.getElementById('averia-form').onsubmit=function(e){{
  e.preventDefault();
  fetch(_bp+'/api/projects',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:'Avería '+document.getElementById('av-client').value,
      client:document.getElementById('av-client').value,
      description:document.getElementById('av-desc').value,
      contact_phone:document.getElementById('av-phone').value,
      work_type:'averia',status:'active',priority:'urgent'}})}})
    .then(function(r){{return r.json();}})
    .then(function(d){{if(d.id)window.location=_bp+'/projects/'+d.id;else Toast.show('Error al crear avería','err');}});
}};
function unblockTask(tid){{
  fetch(_bp+'/api/tasks/'+tid+'/toggle',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{status:'in_progress'}})}})
    .then(function(r){{if(r.ok){{Toast.show('Tarea desbloqueada','ok');location.reload();}}else Toast.show('Error al desbloquear','err');}});
}}
</script>"""

    content = (f'<div class="toolbar"><h1>Dashboard</h1>'
               f'<button class="btn btn-primary" onclick="openAveriaRapida()">⚡ Avería rápida</button></div>'
               f'{triage_html}{kpis}{bt_html}{dw_html}{low_html}{od_html}{rp_html}{averia_modal}')
    return _shell("dashboard", user, content, title="Dashboard")

# ── projects list ─────────────────────────────────────────────────────────────
