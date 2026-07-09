"""Modo campo — vista simplificada para técnicos de campo."""
import json
from datetime import date as _date
from core.db import BP, q, q1, rs
from core.helpers import _esc, _badge2, _pbadge, _empty_state, _fd
from web.layout import _shell


def _field_page(user):
    uid = user["id"]
    today = _date.today().isoformat()

    my_projects = rs(q("""SELECT p.* FROM projects p
        WHERE p.assigned_to=? AND p.status='active'
        ORDER BY CASE p.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
          WHEN 'normal' THEN 2 ELSE 3 END""", (uid,)))

    pids = [p['id'] for p in my_projects]

    if not pids:
        return _shell("field", user,
            _empty_state("🔧", "Sin proyectos activos asignados",
                "Cuando el administrador te asigne un proyecto, aparecerá aquí."),
            title="Modo campo")

    ph = ",".join("?" * len(pids))
    tasks = rs(q(f"""SELECT t.*,p.name pname,p.id pid,p.client FROM tasks t
        JOIN projects p ON p.id=t.project_id
        WHERE t.project_id IN ({ph}) AND t.status NOT IN ('done','cancelled')
        ORDER BY CASE p.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
          WHEN 'normal' THEN 2 ELSE 3 END,
          CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
          WHEN 'normal' THEN 2 ELSE 3 END,
          t.due_date ASC""", pids))

    task_cards = ""
    for t in tasks:
        is_overdue = bool(t.get('due_date') and t['due_date'] < today)
        is_blocked = t['status'] == 'blocked'
        border_style = "border-color:var(--s-err)" if (is_blocked or is_overdue) else ""
        bg_style = "background:var(--s-err-sf);" if is_blocked else ""
        cl = q1("SELECT COUNT(*),SUM(done) FROM task_checklist WHERE task_id=?", (t['id'],))
        cl_total, cl_done = (cl[0] or 0), (cl[1] or 0)
        cl_html = (f'<span class="muted" style="font-size:.82rem">☑ {int(cl_done)}/{cl_total}</span>'
                   if cl_total else "")
        due_html = (f'<span style="font-size:.8rem;color:{"var(--s-err)" if is_overdue else "var(--muted)"}">'
                    f'🗓 {_fd(t["due_date"])}</span>') if t.get("due_date") else ""
        task_cards += f"""<div class="field-task-card" id="ftask-{t['id']}" style="{bg_style}{border_style}">
  <div class="ftask-top">
    <div>
      <div class="ftask-name">{_esc(t['title'])}</div>
      <div class="ftask-proj">{_esc(t['pname'])} · {_esc(t['client'])}</div>
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-shrink:0">
      {_badge2(t['status'])}{_pbadge(t['priority'])}
    </div>
  </div>
  {"<div class='ftask-desc'>"+_esc(t['description'])+"</div>" if t.get('description') else ""}
  <div class="ftask-foot">
    <div style="display:flex;gap:8px;align-items:center">{due_html}{cl_html}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn btn-ghost btn-sm" onclick="fChecklist({t['id']},{json.dumps(t['title'])})">☑ Checklist</button>
      <button class="btn btn-ghost btn-sm" onclick="fPhoto({t['id']})">📷 Foto</button>
      <button class="btn btn-primary btn-sm" onclick="fDone({t['id']},this)">✓ Listo</button>
    </div>
  </div>
</div>"""

    if not task_cards:
        task_cards = _empty_state("✅", "Todo al día", "Sin tareas pendientes asignadas.")

    proj_pills = "".join(
        f'<a href="{BP}/projects/{p["id"]}" class="chip" style="text-decoration:none">'
        f'{_esc(p["name"])}</a>'
        for p in my_projects)

    content = f"""
<div class="toolbar" style="margin-bottom:12px">
  <h1>🔧 Modo campo</h1>
  <a href="{BP}/" class="btn btn-ghost btn-sm">← Panel</a>
</div>
<div style="margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap">{proj_pills}</div>
<div id="field-tasks">{task_cards}</div>

<div class="modal-bg" id="fcl-modal">
<div class="modal" style="max-height:90vh;overflow-y:auto">
  <h2 id="fcl-title">Checklist</h2>
  <ul class="checklist" id="fcl-list" style="font-size:1.05rem"></ul>
  <div class="add-row-form" style="margin-top:12px">
    <input id="fcl-new" placeholder="Nuevo paso...">
    <button class="btn btn-primary" onclick="fclAdd()">+</button>
  </div>
  <div class="modal-foot">
    <button class="btn btn-ghost" onclick="document.getElementById('fcl-modal').classList.remove('open')">Cerrar</button>
  </div>
</div></div>

<div class="modal-bg" id="fphoto-modal">
<div class="modal">
  <h2>📷 Subir foto</h2>
  <div id="fphoto-preview" style="margin:12px 0;text-align:center"></div>
  <label style="display:block;padding:20px;border:2px dashed var(--border);border-radius:8px;text-align:center;cursor:pointer;font-size:1rem">
    📸 Tocar para seleccionar foto
    <input type="file" id="fphoto-input" accept="image/*" capture="environment"
           style="display:none" onchange="fphotoPreview(this)">
  </label>
  <div class="modal-foot" style="margin-top:12px">
    <button class="btn btn-ghost" onclick="document.getElementById('fphoto-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="fphotoUpload()">📤 Subir</button>
  </div>
</div></div>

<style>
.field-task-card{{background:var(--bg2);border:2px solid var(--border);border-radius:12px;
  padding:18px;margin-bottom:16px;transition:border-color .15s,opacity .3s}}
.ftask-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px}}
.ftask-name{{font-size:1.1rem;font-weight:700;line-height:1.3}}
.ftask-proj{{font-size:.82rem;color:var(--muted);margin-top:2px}}
.ftask-desc{{font-size:.9rem;color:var(--muted);margin-bottom:10px;line-height:1.5}}
.ftask-foot{{display:flex;justify-content:space-between;align-items:center;gap:8px;
  flex-wrap:wrap;margin-top:12px;padding-top:10px;border-top:1px solid var(--border)}}
</style>

<script>
var bp={json.dumps(BP)};
var _fclTid=null, _fphotoTid=null;

function fChecklist(tid,title){{
  _fclTid=tid;
  document.getElementById('fcl-title').textContent='☑ '+title;
  document.getElementById('fcl-list').innerHTML='<li class="muted">Cargando…</li>';
  document.getElementById('fcl-modal').classList.add('open');
  fetch(bp+'/api/tasks/'+tid+'/checklist')
    .then(function(r){{return r.json();}}).then(fclRender);
}}
function fclRender(items){{
  var el=document.getElementById('fcl-list');
  if(!items.length){{
    el.innerHTML='<li class="muted" style="text-align:center;padding:16px">Sin pasos. Añade uno abajo.</li>';
    return;
  }}
  el.innerHTML=items.map(function(i){{
    return '<li style="display:flex;align-items:center;gap:14px;padding:10px 0;'
      +'border-bottom:1px solid var(--border)">'
      +'<input type="checkbox"'+(i.done?' checked':'')
      +' onchange="fclToggle('+i.id+',this)" style="width:24px;height:24px;cursor:pointer;flex-shrink:0">'
      +'<span style="'+(i.done?'text-decoration:line-through;color:var(--muted)':'')
      +';font-size:1rem">'+i.label+'</span></li>';
  }}).join('');
}}
function fclToggle(id,cb){{
  fetch(bp+'/api/checklist/'+id,{{method:'PATCH',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{done:cb.checked?1:0}})}})
    .then(function(r){{if(!r.ok)Toast.show('Error','err');}});
}}
function fclAdd(){{
  var inp=document.getElementById('fcl-new');
  var label=inp.value.trim();if(!label)return;
  fetch(bp+'/api/tasks/'+_fclTid+'/checklist',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{label:label}})}})
    .then(function(){{
      inp.value='';
      fetch(bp+'/api/tasks/'+_fclTid+'/checklist').then(function(r){{return r.json();}}).then(fclRender);
    }});
}}
function fPhoto(tid){{
  _fphotoTid=tid;
  document.getElementById('fphoto-preview').innerHTML='';
  document.getElementById('fphoto-input').value='';
  document.getElementById('fphoto-modal').classList.add('open');
}}
function fphotoPreview(inp){{
  if(!inp.files[0])return;
  document.getElementById('fphoto-preview').innerHTML=
    '<img src="'+URL.createObjectURL(inp.files[0])+'" style="max-width:100%;max-height:200px;border-radius:8px">';
}}
function fphotoUpload(){{
  var f=document.getElementById('fphoto-input').files[0];
  if(!f){{Toast.show('Selecciona una foto primero','warn');return;}}
  var fd=new FormData();fd.append('file',f);
  fetch(bp+'/api/tasks/'+_fphotoTid+'/photos',{{method:'POST',body:fd}})
    .then(function(r){{
      if(r.ok){{Toast.show('Foto subida ✅','ok');document.getElementById('fphoto-modal').classList.remove('open');}}
      else Toast.show('Error al subir foto','err');
    }});
}}
function fDone(tid,btn){{
  fetch(bp+'/api/tasks/'+tid+'/toggle',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{status:'done'}})}})
    .then(function(r){{
      if(r.ok){{
        var card=document.getElementById('ftask-'+tid);
        if(card){{card.style.opacity='.35';card.style.pointerEvents='none';}}
        Toast.show('Tarea marcada como lista ✓','ok');
      }}
    }});
}}
</script>"""

    return _shell("field", user, content, title="Modo campo")
