"""Projects list and kanban pages."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR,
    WORK_TYPES, _wt_badge, _badge, _badge2, _pbadge, _empty_state,
)
from web.layout import _shell

def _projects_page(user, filter_status="", view="cards", new="", tech_filter="", wtype_filter="", dfrom="", dto=""):
    conds, params_list = [], []
    if filter_status:
        conds.append("p.status=?"); params_list.append(filter_status)
    if tech_filter:
        conds.append("p.assigned_to=?"); params_list.append(int(tech_filter))
    if wtype_filter:
        conds.append("p.work_type=?"); params_list.append(wtype_filter)
    if dfrom:
        conds.append("p.due_date>=?"); params_list.append(dfrom)
    if dto:
        conds.append("p.due_date<=?"); params_list.append(dto)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    params = tuple(params_list)

    def _pu(**kw):
        p = {"status": filter_status, "view": view, "tech": tech_filter, "wtype": wtype_filter, "dfrom": dfrom, "dto": dto}
        p.update(kw)
        qs = "&".join(f"{k}={v}" for k, v in p.items() if v and not (k == "view" and v == "cards"))
        return f"{BP}/projects" + (f"?{qs}" if qs else "")

    projects = rs(q(f"""SELECT p.*,u.display_name tech,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id) task_t,
        (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') task_d,
        (SELECT COUNT(*) FROM project_members pm WHERE pm.project_id=p.id) member_count
        FROM projects p LEFT JOIN users u ON u.id=p.assigned_to
        {where}
        ORDER BY CASE p.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
          WHEN 'normal' THEN 2 ELSE 3 END, p.updated_at DESC""", params))

    techs = rs(q("SELECT id,display_name FROM users WHERE active=1 AND show_in_planning=1 ORDER BY display_name"))
    tech_opts = "".join(f'<option value="{t["id"]}">{_esc(t["display_name"])}</option>' for t in techs)

    fbtn = lambda s, l: (f'<a href="{_pu(status=s)}" '
        f'class="btn btn-sm {"btn-primary" if filter_status==s else "btn-ghost"}">{l}</a>')
    filters = (fbtn("","Todos")+fbtn("active","Activos")+fbtn("paused","Pausados")
               +fbtn("quoted","Presupuestados")+fbtn("pending_approval","Pend. firma")
               +fbtn("completed","Completados")+fbtn("cancelled","Cancelados"))

    wtype_opts = ('<option value="' + _pu(wtype="") + '"' +
                  (' selected' if not wtype_filter else '') + '>Todos los tipos</option>')
    for _key, _info in WORK_TYPES.items():
        _sel = ' selected' if wtype_filter == _key else ''
        wtype_opts += f'<option value="{_pu(wtype=_key)}"{_sel}>{_info["icon"]} {_info["name"]}</option>'

    tech_sel_opts2 = ('<option value="' + _pu(tech="") + '"' +
                     (' selected' if not tech_filter else '') + '>Todos los técnicos</option>')
    for _t in techs:
        _sel = ' selected' if tech_filter == str(_t["id"]) else ''
        tech_sel_opts2 += f'<option value="{_pu(tech=str(_t["id"]))}" {_sel}>{_esc(_t["display_name"])}</option>'

    _border_color = {"active":"var(--s-ok)","paused":"var(--s-warn)","completed":"var(--muted)",
                     "cancelled":"var(--muted)","quoted":"#7c3aed","pending_approval":"var(--s-info)","": "var(--muted)"}
    _prog_color   = {"active":"var(--s-ok)","paused":"var(--s-warn)","completed":"var(--muted)",
                     "cancelled":"var(--muted)","quoted":"#7c3aed","pending_approval":"var(--s-info)","": "var(--muted)"}

    # ── card view ──
    cards_html = ""
    for p in projects:
        pct = int(p['task_d']/p['task_t']*100) if p['task_t'] else 0
        is_crit = p.get('priority') == 'urgent' and p.get('status') == 'active'
        bc = 'var(--s-err)' if is_crit else _border_color.get(p['status'], "#a8a29e")
        pc_color = _prog_color.get(p['status'], "#a8a29e")
        ref_chip = f'<span class="chip">#{_esc(p["reference"])}</span>' if p.get("reference") else ""
        due_html = f'🗓 {_esc(p["due_date"][:10])}' if p.get("due_date") else ""
        tech_html = f'👤 {_esc(p["tech"])}' if p.get("tech") else ""
        prog_html = ""
        if p["task_t"]:
            prog_html = (f'<div class="proj-card-prog">'
                f'<div class="proj-card-prog-label">'
                f'<span>Tareas</span><span>{p["task_d"]}/{p["task_t"]}</span></div>'
                f'<div class="progress"><div class="progress-bar" style="width:{pct}%;background:{pc_color}"></div></div></div>')
        mc = p.get('member_count', 0)
        members_html = (f'<span style="font-size:.75rem;color:var(--muted)">👥 {mc}</span>' if mc else "")
        safe_p = {k: v for k, v in dict(p).items() if isinstance(v, (str, int, float, type(None)))}
        wt_html = _wt_badge(p.get('work_type') or 'proyecto')
        search_val = f"{p['name']} {p['client']} {p.get('reference','') or ''} {p.get('tech','') or ''}".lower()
        pid = p["id"]
        cards_html += (
            f'<a class="proj-card" href="{BP}/projects/{pid}" data-search="{_esc(search_val)}"'
            f' style="border-left:3px solid {bc}">'
            f'<div class="proj-card-body">'
            f'<div class="proj-card-name">{_esc(p["name"])}</div>'
            f'<div class="proj-card-client">{_esc(p["client"])}</div>'
            f'<div class="proj-card-tags">'
            f'{wt_html}'
            f'{_badge2(p["status"])}'
            f'{_pbadge(p["priority"])}'
            f'{ref_chip}</div>'
            f'{prog_html}'
            f'</div>'
            f'<div class="proj-card-foot">'
            f'<span>{due_html}</span>'
            f'<span style="display:flex;align-items:center;gap:6px">{members_html}{tech_html}</span>'
            f'<button onclick="event.preventDefault();event.stopPropagation();editProject({_jattr(safe_p)})" '
            f'class="btn btn-ghost btn-icon">✏️</button>'
            f'<button data-pid="{pid}" data-pname="{_esc(p["name"])}" '
            f'onclick="event.preventDefault();event.stopPropagation();deleteProject(this.dataset.pid,this.dataset.pname)" '
            f'class="btn btn-ghost btn-icon" style="color:var(--danger,#dc2626)">🗑</button>'
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
        search_val2 = f"{p['name']} {p['client']} {p.get('reference','') or ''} {p.get('tech','') or ''}".lower()
        pid2 = p["id"]
        is_crit2 = p.get('priority') == 'urgent' and p.get('status') == 'active'
        crit_cls2 = ' class="nd-crit"' if is_crit2 else ''
        rows += (f'<tr data-search="{_esc(search_val2)}"{crit_cls2}><td><a href="{BP}/projects/{pid2}" class="fw7">{_esc(p["name"])}</a>'
            f'{ref_html}<br><span class="muted" style="font-size:.75rem">{_esc(p["client"])}</span></td>'
            f'<td>{_badge2(p["status"])}</td><td class="col-m-hide">{_pbadge(p["priority"])}</td>'
            f'<td class="muted col-m-hide">{_esc(p["tech"] or "—")}</td>'
            f'<td class="muted col-m-hide">{_esc((p["due_date"] or "—")[:10])}</td>'
            f'<td class="col-m-hide">{prog}</td>'
            f'<td><button class="btn btn-ghost btn-icon" onclick="editProject({_jattr(safe_p2)})">✏️</button>'
            f'<button data-pid="{pid2}" data-pname="{_esc(p["name"])}" '
            f'onclick="deleteProject(this.dataset.pid,this.dataset.pname)" '
            f'class="btn btn-ghost btn-icon" style="color:var(--danger,#dc2626)">🗑</button>'
            f'<a href="{BP}/projects/{pid2}" class="btn btn-ghost btn-icon">→</a></td></tr>')

    empty = _empty_state("📁", "Sin proyectos todavía", "Crea el primero con + Nuevo")
    vt_cards  = "active" if view == "cards" else ""
    vt_list   = "active" if view == "list"  else ""
    url_cards = _pu(view="cards")
    url_list  = _pu(view="list")

    content = f"""
<div class="toolbar">
  <h1>Proyectos</h1>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <div style="position:relative">
      <svg style="position:absolute;left:9px;top:50%;transform:translateY(-50%);color:var(--muted);pointer-events:none"
           width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      <input id="proj-search" type="search" placeholder="Buscar proyecto, cliente, ref…"
             style="padding-left:30px;min-width:220px" oninput="filterProjects(this.value)">
    </div>
    <div class="view-toggle">
      <button class="{vt_cards}" onclick="window.location='{url_cards}'">⊞ Tarjetas</button>
      <button class="{vt_list}"  onclick="window.location='{url_list}'">☰ Lista</button>
    </div>
    <a href="{BP}/field" class="btn btn-ghost btn-sm">⚡ Modo campo</a>
    <button class="btn btn-ghost btn-sm" onclick="showTemplatesModal()">📋 Plantillas</button>
    <a href="{BP}/api/export/projects.csv" class="btn btn-ghost btn-sm">⬇ CSV</a>
    <button class="btn btn-primary" onclick="openNewProject()">+ Nuevo</button>
  </div>
</div>
<div class="toolbar-left" style="margin-bottom:18px;gap:8px;flex-wrap:wrap">
  {filters}
  <select onchange="location.href=this.value" style="height:32px;padding:0 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg3);color:var(--text);font-size:.82rem">{wtype_opts}</select>
  <select onchange="location.href=this.value" style="height:32px;padding:0 8px;border-radius:6px;border:1px solid var(--border);background:var(--bg3);color:var(--text);font-size:.82rem">{tech_sel_opts2}</select>
  <form method="get" action="{BP}/projects" style="display:inline-flex;gap:6px;align-items:center">
    <input type="hidden" name="status" value="{_esc(filter_status)}">
    <input type="hidden" name="view" value="{_esc(view)}">
    <input type="hidden" name="tech" value="{_esc(tech_filter)}">
    <input type="hidden" name="wtype" value="{_esc(wtype_filter)}">
    <span class="muted" style="font-size:.8rem;white-space:nowrap">Límite:</span>
    <input type="date" name="dfrom" value="{_esc(dfrom)}" style="height:32px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg3);color:var(--text);font-size:.82rem">
    <span class="muted" style="font-size:.8rem">—</span>
    <input type="date" name="dto" value="{_esc(dto)}" style="height:32px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg3);color:var(--text);font-size:.82rem">
    <button type="submit" class="btn btn-ghost btn-sm">Filtrar</button>
    {f'<a href="{_pu(dfrom="",dto="")}" class="btn btn-ghost btn-sm">✕</a>' if dfrom or dto else ''}
  </form>
</div>
<div id="proj-search-empty" style="display:none;text-align:center;padding:32px;color:var(--muted)">
  Sin resultados para la búsqueda.
</div>

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
function filterProjects(q){{
  q=q.toLowerCase().trim();
  var cards=document.querySelectorAll('.proj-card[data-search]');
  var rows=document.querySelectorAll('#view-list tr[data-search]');
  var visCards=0,visRows=0;
  cards.forEach(function(el){{
    var show=!q||el.dataset.search.indexOf(q)>=0;
    el.style.display=show?'':'none';
    if(show)visCards++;
  }});
  rows.forEach(function(el){{
    var show=!q||el.dataset.search.indexOf(q)>=0;
    el.style.display=show?'':'none';
    if(show)visRows++;
  }});
  var empty=document.getElementById('proj-search-empty');
  var vis=(document.getElementById('view-cards').style.display!=='none')?visCards:visRows;
  empty.style.display=(q&&vis===0)?'':'none';
}}
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
function deleteProject(id,name){{
  ConfirmDialog.show('¿Eliminar proyecto "'+name+'"?','Se eliminarán también todas sus tareas, materiales y archivos.')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/projects/'+id,{{method:'DELETE'}})
        .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'Error');}});}})
        .then(function(){{location.href=bp+'/projects';}})
        .catch(function(err){{Toast.show(err.message,'err');}});
    }});
}}
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
    .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'Error');}});}})
    .then(function(j){{
      closeProjModal();
      if(j.closing_summary){{ showClosingModal(j.closing_summary); }}
      else{{ location.href=bp+'/projects'; }}
    }})
    .catch(function(err){{Toast.show(err.message,'err');}});
}};
(function(){{
  var qs=new URLSearchParams(window.location.search);
  var tipo=qs.get('new');
  if(tipo==='averia'||tipo==='proyecto'){{
    var today=new Date().toISOString().slice(0,10);
    openNewProject();
    if(tipo==='averia'){{
      document.getElementById('f-wtype').value='averia';
      document.getElementById('f-priority').value='urgent';
    }}
    document.getElementById('f-start').value=today;
    document.getElementById('f-name').focus();
    history.replaceState(null,'',window.location.pathname);
  }}
}})();
var _CLOSING_CHECKS=[
  'Prueba de conectividad realizada',
  'Cables y puertos etiquetados',
  'Documentación entregada al cliente',
  'Área de trabajo limpia',
  'Equipos instalados inventariados',
  'Firma del cliente obtenida'
];
function showClosingModal(s){{
  var el=document.getElementById('closing-modal');
  var pct=s.tasks_total?Math.round(s.tasks_done/s.tasks_total*100):100;
  document.getElementById('cm-name').textContent=s.name;
  document.getElementById('cm-tasks').textContent=s.tasks_done+'/'+s.tasks_total+' ('+pct+'%)';
  document.getElementById('cm-est').textContent=s.hours_estimated?s.hours_estimated+'h':'—';
  document.getElementById('cm-timer').textContent=s.hours_timer?s.hours_timer+'h':'—';
  document.getElementById('cm-report').href=bp+'/projects/'+s.pid+'/report';
  document.getElementById('cm-albaran').href=bp+'/projects/'+s.pid+'/albaran';
  document.getElementById('cm-view').href=bp+'/projects/'+s.pid;
  var cl=document.getElementById('cm-checklist');
  cl.innerHTML=_CLOSING_CHECKS.map(function(c,i){{
    return '<label style="display:flex;align-items:center;gap:8px;font-size:.85rem;cursor:pointer">'
      +'<input type="checkbox" id="cc-'+i+'" style="width:16px;height:16px;accent-color:var(--primary)">'
      +'<span>'+c+'</span></label>';
  }}).join('');
  el.classList.add('open');
}}
</script>

<div class="modal-bg" id="closing-modal">
<div class="modal" style="max-width:480px">
  <div style="text-align:center">
    <div style="font-size:3rem;margin-bottom:8px">✅</div>
    <h2 style="margin-bottom:4px">Proyecto completado</h2>
    <p id="cm-name" style="color:var(--muted);font-size:.9rem;margin-bottom:16px"></p>
  </div>
  <div style="background:var(--bg3);border-radius:8px;padding:14px;margin-bottom:16px">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;font-size:.875rem">
      <span style="color:var(--muted)">Tareas completadas</span><span id="cm-tasks" class="fw7"></span>
      <span style="color:var(--muted)">Horas estimadas</span><span id="cm-est" class="fw7"></span>
      <span style="color:var(--muted)">Horas registradas</span><span id="cm-timer" class="fw7"></span>
    </div>
  </div>
  <div style="background:var(--bg3);border-radius:8px;padding:14px;margin-bottom:16px">
    <div style="font-size:.8rem;font-weight:700;margin-bottom:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">✔ Checklist de cierre</div>
    <div id="cm-checklist" style="display:flex;flex-direction:column;gap:6px"></div>
  </div>
  <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
    <a id="cm-report" href="#" class="btn btn-primary" target="_blank">📄 Ver informe</a>
    <a id="cm-albaran" href="#" class="btn btn-ghost" target="_blank">🧾 Albarán</a>
    <a id="cm-view" href="#" class="btn btn-ghost">→ Ir al proyecto</a>
    <button class="btn btn-ghost" onclick="document.getElementById('closing-modal').classList.remove('open');location.reload()">Cerrar</button>
  </div>
</div></div>

<!-- MODAL plantillas -->
<div class="modal-bg" id="tpl-modal">
<div class="modal" style="max-width:560px">
  <h2>📋 Plantillas de proyecto</h2>
  <div id="tpl-list" style="max-height:280px;overflow-y:auto;margin-bottom:16px"></div>
  <p class="muted" style="font-size:.8rem;margin-bottom:12px">Las plantillas se crean desde el detalle de un proyecto con el botón 💾 Plantilla.</p>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('tpl-modal').classList.remove('open')">Cerrar</button>
  </div>
</div></div>

<!-- MODAL crear desde plantilla -->
<div class="modal-bg" id="tpl-apply-modal">
<div class="modal" style="max-width:480px">
  <h2 id="tpl-apply-title">Nuevo proyecto desde plantilla</h2>
  <input type="hidden" id="tpl-apply-id">
  <div class="form-row">
    <div><label>Nombre del proyecto *</label><input id="tpl-pname" required></div>
    <div><label>Cliente *</label><input id="tpl-pclient" required></div>
  </div>
  <div class="form-row">
    <div><label>Fecha inicio</label><input type="date" id="tpl-pstart"></div>
    <div><label>Fecha límite</label><input type="date" id="tpl-pdue"></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('tpl-apply-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doApplyTemplate()">Crear proyecto</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
function showTemplatesModal(){{
  document.getElementById('tpl-list').innerHTML='<span class="muted">Cargando…</span>';
  document.getElementById('tpl-modal').classList.add('open');
  fetch(bp+'/api/templates').then(function(r){{return r.json();}}).then(function(tmpls){{
    var el=document.getElementById('tpl-list');
    if(!tmpls.length){{
      el.innerHTML='<p class="muted" style="text-align:center;padding:24px">Sin plantillas. Ábrelas desde un proyecto → 💾 Plantilla.</p>';
      return;
    }}
    el.innerHTML=tmpls.map(function(t){{
      var wt=(t.work_type||'proyecto');
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)">'
        +'<div><div class="fw7">'+t.name+'</div>'
        +'<div class="muted" style="font-size:.75rem">'+wt+(t.estimated_hours?' · '+t.estimated_hours+'h est.':'')+'</div></div>'
        +'<div style="display:flex;gap:6px">'
        +'<button class="btn btn-primary btn-sm" onclick="openApplyTemplate('+t.id+','+JSON.stringify(t.name)+','+JSON.stringify(t.work_type)+')">→ Crear</button>'
        +'<button class="btn btn-danger btn-sm" onclick="delTemplate('+t.id+')">✕</button>'
        +'</div></div>';
    }}).join('');
  }});
}}
function openApplyTemplate(id,name,wtype){{
  document.getElementById('tpl-apply-id').value=id;
  document.getElementById('tpl-apply-title').textContent='Nuevo proyecto: '+name;
  document.getElementById('tpl-pname').value='';
  document.getElementById('tpl-pclient').value='';
  document.getElementById('tpl-pstart').value='';
  document.getElementById('tpl-pdue').value='';
  document.getElementById('tpl-apply-modal').classList.add('open');
}}
function doApplyTemplate(){{
  var id=document.getElementById('tpl-apply-id').value;
  var pname=document.getElementById('tpl-pname').value.trim();
  var pclient=document.getElementById('tpl-pclient').value.trim();
  if(!pname||!pclient){{Toast.show('Nombre y cliente son obligatorios','err');return;}}
  fetch(bp+'/api/templates/'+id+'/apply',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name:pname,client:pclient,
      start_date:document.getElementById('tpl-pstart').value,
      due_date:document.getElementById('tpl-pdue').value}})}})
    .then(function(r){{return r.ok?r.json():r.json().then(function(j){{throw new Error(j.error||'Error');}});}})
    .then(function(j){{
      document.getElementById('tpl-apply-modal').classList.remove('open');
      document.getElementById('tpl-modal').classList.remove('open');
      Toast.show('Proyecto creado desde plantilla','ok');
      setTimeout(function(){{location.href=bp+'/projects/'+j.id;}},600);
    }}).catch(function(e){{Toast.show(e.message,'err');}});
}}
function delTemplate(id){{
  ConfirmDialog.show('¿Eliminar esta plantilla?','Esta acción no se puede deshacer.')
    .then(function(ok){{if(!ok)return;
      fetch(bp+'/api/templates/'+id,{{method:'DELETE'}})
        .then(function(){{showTemplatesModal();}});
    }});
}}
</script>"""
    return _shell("projects", user, content, title="Proyectos")


# ── kanban builder ────────────────────────────────────────────────────────────
_COL_CSS = {
    "pending":    "var(--muted)",
    "in_progress":"var(--brand)",
    "blocked":    "var(--s-err)",
    "done":       "var(--s-ok)",
}
_PRI_CSS = {"low":"var(--muted)","normal":"var(--muted)","high":"var(--s-warn)","urgent":"var(--s-err)"}
_PRI_LBL = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}

def _build_kanban(tasks, pid):
    cols = [
        ("pending",    "Pendiente",  "🔘"),
        ("in_progress","En curso",   "🔵"),
        ("blocked",    "Bloqueado",  "🔴"),
        ("done",       "Hecho",      "🟢"),
    ]
    task_by_status = {s: [] for s, *_ in cols}
    for t in tasks:
        s = t['status'] if t['status'] in task_by_status else 'pending'
        task_by_status[s].append(t)

    html = '<div class="kanban">'
    for status, label, icon in cols:
        ccolor   = _COL_CSS[status]
        col_tasks = task_by_status[status]
        cards = ""
        for t in col_tasks:
            pcolor_css = _PRI_CSS.get(t['priority'], "var(--muted)")
            plabel     = _PRI_LBL.get(t['priority'], '')
            cl_total   = t.get('cl_t', 0)
            cl_done    = t.get('cl_d', 0)
            cl_pct     = int(cl_done/cl_total*100) if cl_total else 0
            cl_html    = ""
            if cl_total:
                cl_html = (f'<div style="margin-top:6px">'
                           f'<div style="font-size:.7rem;color:var(--muted);margin-bottom:2px">'
                           f'Checklist {cl_done}/{cl_total}</div>'
                           f'<div class="progress"><div class="progress-bar" style="width:{cl_pct}%"></div></div></div>')
            due_html   = f'<span style="font-size:.72rem;color:var(--muted)">🗓 {t["due_date"][:10]}</span>' if t.get('due_date') else ""
            crit_cls   = ' nd-crit' if t['status'] == 'blocked' else ''
            photo_badge = (f'<span style="position:absolute;top:-2px;right:-2px;background:var(--brand);'
                           f'color:#fff;border-radius:50%;font-size:.55rem;width:14px;height:14px;'
                           f'display:flex;align-items:center;justify-content:center;line-height:1">'
                           f'{t["photo_count"]}</span>' if t.get("photo_count") else "")
            cards += (
                f'<div class="task-card{crit_cls}" draggable="true" '
                f'data-task-id="{t["id"]}" data-status="{t["status"]}" '
                f'data-title="{_esc(t["title"])}" data-priority="{t["priority"]}">'
                f'<div class="task-card-strip" style="background:{pcolor_css}"></div>'
                f'<div class="task-card-inner">'
                f'<div class="task-card-title">{_esc(t["title"])}</div>'
                f'{("<div style=font-size:.75rem;color:var(--muted);margin-bottom:4px>"+_esc(t["description"])+"</div>") if t.get("description") else ""}'
                f'{cl_html}'
                f'<div class="task-card-foot">'
                f'<span style="color:{pcolor_css};font-size:.72rem;font-weight:700">▲ {plabel}</span>'
                f'{due_html}'
                f'<button class="btn btn-ghost btn-icon" style="margin-left:auto;font-size:.75rem" '
                f'onclick="openChecklist({t["id"]},{json.dumps(t["title"])})">☑</button>'
                f'<button class="btn btn-ghost btn-icon" style="font-size:.75rem;position:relative" '
                f'onclick="openTaskPhotos({t["id"]},{json.dumps(t["title"])})">📷'
                + photo_badge
                + '</button>'
                f'<div class="nd-ovfl-wrap">'
                f'<button class="btn btn-ghost btn-icon" style="font-size:.75rem" onclick="ndOverflow(this)" title="Más opciones">⋯</button>'
                f'<div class="nd-ovfl-drop flip-up">'
                f'<button class="nd-ovfl-item" onclick="editTask({json.dumps(dict(t))})">✏️ Editar</button>'
                f'<button class="nd-ovfl-item danger" onclick="delTask({t["id"]})">✕ Eliminar</button>'
                f'</div></div>'
                f'</div></div></div>')

        count = len(col_tasks)
        html += (f'<div class="kanban-col" data-status="{status}">'
                 f'<div class="kanban-col-hd">'
                 f'<div class="col-title" style="color:{ccolor}">{icon} {label}</div>'
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
