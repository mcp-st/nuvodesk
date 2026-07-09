"""Users management page."""
import json
from core.db import BP, q, rs, r2d
from core.helpers import _esc
from web.layout import _shell

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
        safe_u = {k: u[k] for k in (
            "id","display_name","username","role","active","email",
            "show_in_planning","first_name","last_name","phone","extension"
        ) if k in u}
        user_attr = json.dumps(safe_u).replace('"', '&quot;')
        full = _esc(u.get("display_name") or "")
        full_raw = u.get("display_name") or ""
        name_json = json.dumps(full_raw).replace('"', '&quot;')
        phone_str = _esc(u.get("phone") or "")
        phone_td = f'<span style="font-size:.78rem;color:var(--muted)">{phone_str}</span>' if phone_str else ""
        show_vac = user.get("role") == "admin" or uid_val == user.get("id")
        vac_btn = (f'<button class="btn btn-ghost btn-icon" title="Ausencias" '
                   f'onclick="openVacations({uid_val},{name_json})">📅</button>') if show_vac else ""
        rows += (f'<tr>'
            f'<td class="fw7">{full}</td>'
            f'<td class="muted" style="font-size:.82rem">{_esc(u["username"])}</td>'
            f'<td>{_esc(role_lbl)}</td>'
            f'<td>{active_dot}</td>'
            f'<td class="col-m-hide">{_esc(u.get("email") or "")}</td>'
            f'<td class="col-m-hide">{phone_td}</td>'
            f'<td style="white-space:nowrap">'
            f'<button class="btn btn-ghost btn-icon" title="Certificaciones" '
            f'onclick="openCerts({uid_val},{name_json})">🎓</button>'
            f'{vac_btn}'
            f'<button class="btn btn-ghost btn-icon" data-user="{user_attr}" '
            f'onclick="editUser(JSON.parse(this.dataset.user))">✏️</button>'
            f'{del_btn}</td></tr>')

    content = f"""
<div class="toolbar"><h1>Usuarios</h1>
  <button class="btn btn-primary" onclick="openNewUser()">+ Usuario</button>
</div>
<div class="card">
<div class="tbl-wrap"><table><thead><tr>
  <th>Nombre</th><th>Login</th><th>Rol</th><th></th>
  <th class="col-m-hide">Email</th><th class="col-m-hide">Teléfono</th><th></th>
</tr></thead><tbody>{rows}</tbody></table></div>
</div>

<div class="modal-bg" id="user-modal">
<div class="modal" style="max-width:560px">
  <h2 id="user-modal-title">Nuevo usuario</h2>
  <form id="user-form">
  <input type="hidden" id="user-id">

  <div class="form-row">
    <div><label>Nombre</label><input id="u-firstname" required></div>
    <div><label>Apellido</label><input id="u-lastname"></div>
  </div>
  <div class="form-row">
    <div><label>Teléfono</label><input id="u-phone" type="tel"></div>
    <div><label>Extensión</label><input id="u-ext"></div>
  </div>
  <div class="form-row">
    <div><label>Email <span class="muted" style="font-weight:400">(notificaciones)</span></label>
      <input type="email" id="u-email"></div>
    <div><label>Usuario (login)</label><input id="u-username" required autocomplete="off"></div>
  </div>
  <div class="form-row">
    <div>
      <label>Contraseña
        <span id="u-pw-hint" class="muted" style="font-weight:400;display:none"> (vacío = enviar link por email)</span>
        <span id="u-pw-hint-edit" class="muted" style="font-weight:400;display:none"> (vacío = no cambiar)</span>
      </label>
      <input type="password" id="u-pw" autocomplete="new-password">
    </div>
    <div>
      <label>Repetir contraseña</label>
      <input type="password" id="u-pw2" autocomplete="new-password">
    </div>
  </div>
  <div class="form-row">
    <div><label>Rol</label><select id="u-role">
      <option value="technician">Técnico</option>
      <option value="backoffice">Backoffice</option>
      <option value="admin">Administrador</option>
    </select></div>
    <div></div>
  </div>
  <div class="form-row">
    <div><label>Activo</label>
      <select id="u-active"><option value="1">Sí</option><option value="0">No</option></select>
    </div>
    <div><label>Visible en planificación</label>
      <select id="u-planning"><option value="1">Sí</option><option value="0">No</option></select>
    </div>
  </div>
  <div class="form-row">
    <div><label>Tarifa/hora (€) <span class="muted" style="font-weight:400;font-size:.78rem">para rentabilidad</span></label>
      <input type="number" id="u-labor-rate" min="0" step="0.5" placeholder="0.00">
    </div>
    <div></div>
  </div>
  <div id="u-send-welcome-row" style="display:none;padding:10px 0 4px">
    <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-weight:500;font-size:.875rem">
      <input type="checkbox" id="u-send-welcome" checked style="width:16px;height:16px;accent-color:var(--primary)">
      Enviar email de bienvenida con link de activación
    </label>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="closeUserModal()">Cancelar</button>
    <button type="submit" class="btn btn-primary">Guardar</button>
  </div>
  </form>
</div></div>

<script>
var bp={json.dumps(BP)};
var _editingUser=false;
function _syncWelcomeRow(){{
  var pw=document.getElementById('u-pw').value;
  var email=document.getElementById('u-email').value.trim();
  var row=document.getElementById('u-send-welcome-row');
  if(!_editingUser && !pw && email) row.style.display='block';
  else row.style.display='none';
}}
document.getElementById('u-pw').addEventListener('input',_syncWelcomeRow);
document.getElementById('u-email').addEventListener('input',_syncWelcomeRow);

function openNewUser(){{
  _editingUser=false;
  document.getElementById('user-modal-title').textContent='Nuevo usuario';
  document.getElementById('user-id').value='';
  ['firstname','lastname','phone','ext','username','pw','pw2','email'].forEach(function(f){{
    document.getElementById('u-'+f).value='';
  }});
  document.getElementById('u-pw-hint').style.display='inline';
  document.getElementById('u-pw-hint-edit').style.display='none';
  document.getElementById('u-role').value='technician';
  document.getElementById('u-active').value='1';
  document.getElementById('u-planning').value='1';
  document.getElementById('u-labor-rate').value='';
  document.getElementById('u-send-welcome').checked=true;
  document.getElementById('u-send-welcome-row').style.display='none';
  document.getElementById('user-modal').classList.add('open');
}}
function editUser(u){{
  _editingUser=true;
  document.getElementById('user-modal-title').textContent='Editar usuario';
  document.getElementById('user-id').value=u.id;
  document.getElementById('u-firstname').value=u.first_name||'';
  document.getElementById('u-lastname').value=u.last_name||'';
  document.getElementById('u-phone').value=u.phone||'';
  document.getElementById('u-ext').value=u.extension||'';
  document.getElementById('u-username').value=u.username||'';
  document.getElementById('u-pw').value='';
  document.getElementById('u-pw2').value='';
  document.getElementById('u-pw-hint').style.display='none';
  document.getElementById('u-pw-hint-edit').style.display='inline';
  document.getElementById('u-email').value=u.email||'';
  document.getElementById('u-role').value=u.role||'technician';
  document.getElementById('u-active').value=u.active?'1':'0';
  document.getElementById('u-planning').value=(u.show_in_planning===0||u.show_in_planning==='0')?'0':'1';
  document.getElementById('u-labor-rate').value=u.labor_rate||'';
  document.getElementById('u-send-welcome-row').style.display='none';
  document.getElementById('user-modal').classList.add('open');
}}
function closeUserModal(){{document.getElementById('user-modal').classList.remove('open');}}
document.getElementById('user-modal').onclick=function(e){{if(e.target===this)closeUserModal();}};
document.getElementById('user-form').onsubmit=function(e){{
  e.preventDefault();
  var id=document.getElementById('user-id').value;
  var fn=document.getElementById('u-firstname').value.trim();
  var ln=document.getElementById('u-lastname').value.trim();
  var pw=document.getElementById('u-pw').value;
  var pw2=document.getElementById('u-pw2').value;
  if(pw && pw!==pw2){{
    document.getElementById('u-pw2').setCustomValidity('Las contraseñas no coinciden');
    document.getElementById('u-pw2').reportValidity();
    return;
  }}
  document.getElementById('u-pw2').setCustomValidity('');
  var d={{
    first_name:fn, last_name:ln,
    display_name:(fn+(ln?' '+ln:'')).trim()||fn,
    username:document.getElementById('u-username').value,
    email:document.getElementById('u-email').value,
    phone:document.getElementById('u-phone').value,
    extension:document.getElementById('u-ext').value,
    role:document.getElementById('u-role').value,
    active:document.getElementById('u-active').value==='1'?1:0,
    show_in_planning:document.getElementById('u-planning').value==='1'?1:0,
    labor_rate:parseFloat(document.getElementById('u-labor-rate').value)||0,
    send_welcome:(!id&&document.getElementById('u-send-welcome').checked)?true:false
  }};
  if(pw) d.password=pw;
  fetch(id?bp+'/api/users/'+id:bp+'/api/users',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{
      if(r.ok){{
        r.json().then(function(j){{
          if(j.welcome_error) Toast.show('Usuario creado, pero error al enviar email: '+j.welcome_error,'warn');
          location.reload();
        }});
      }} else r.json().then(function(j){{Toast.show(j.error||'Error','err');}});
    }}).catch(function(){{Toast.show('Error de red al guardar usuario.','err');}});
}};

function delUser(id){{
  ConfirmDialog.show('¿Eliminar usuario?','Esta acción no se puede deshacer.')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/users/'+id,{{method:'DELETE'}})
        .then(function(r){{
          if(r.ok){{location.reload();return;}}
          return r.text().then(function(t){{
            try{{var j=JSON.parse(t);Toast.show(j.error||'Error al eliminar usuario.','err');}}
            catch(e){{Toast.show('Error al eliminar usuario ('+r.status+').','err');}}
          }});
        }}).catch(function(){{Toast.show('Error de red al eliminar usuario.','err');}});
    }});
}}

/* ── Certificaciones ── */
var _certUid=null;
function openCerts(uid,name){{
  _certUid=uid;
  document.getElementById('certs-title').textContent='Certificaciones — '+name;
  document.getElementById('certs-list').innerHTML='<span class="muted">Cargando…</span>';
  document.getElementById('certs-modal').classList.add('open');
  fetch(bp+'/api/users/'+uid+'/certifications')
    .then(function(r){{return r.json();}}).then(renderCerts);
}}
function renderCerts(certs){{
  var el=document.getElementById('certs-list');
  if(!certs.length){{
    el.innerHTML='<p class="muted" style="text-align:center;padding:12px">Sin certificaciones registradas.</p>';
    return;
  }}
  el.innerHTML=certs.map(function(c){{
    var exp=c.expires_date?'· Vence: '+c.expires_date.slice(8,10)+'-'+c.expires_date.slice(5,7)+'-'+c.expires_date.slice(0,4):'';
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)">'
      +'<div><div class="fw7">'+c.cert_name+'</div>'
      +(c.cert_code?'<span class="chip" style="font-size:.72rem">'+c.cert_code+'</span>':'')
      +'<span class="muted" style="font-size:.75rem;margin-left:4px">'+exp+'</span></div>'
      +'<button class="btn btn-danger btn-icon" onclick="delCert('+c.id+')">✕</button>'
      +'</div>';
  }}).join('');
}}
function delCert(id){{
  fetch(bp+'/api/certifications/'+id,{{method:'DELETE'}})
    .then(function(r){{
      if(r.ok)fetch(bp+'/api/users/'+_certUid+'/certifications')
        .then(function(r2){{return r2.json();}}).then(renderCerts);
    }});
}}
document.getElementById('cert-form').onsubmit=function(e){{
  e.preventDefault();
  var d={{cert_name:document.getElementById('cert-name').value,
    cert_code:document.getElementById('cert-code').value,
    issued_date:getDateVal('cert-issued'),
    expires_date:getDateVal('cert-expires')}};
  fetch(bp+'/api/users/'+_certUid+'/certifications',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json();}})
    .then(function(){{
      document.getElementById('cert-form').reset();
      fetch(bp+'/api/users/'+_certUid+'/certifications')
        .then(function(r){{return r.json();}}).then(renderCerts);
    }});
}};
</script>

<!-- MODAL certificaciones -->
<div class="modal-bg" id="certs-modal">
<div class="modal" style="max-width:520px">
  <h2 id="certs-title">Certificaciones</h2>
  <div id="certs-list" style="max-height:220px;overflow-y:auto;margin-bottom:12px"></div>
  <form id="cert-form" style="border-top:1px solid var(--border);padding-top:12px">
    <div class="form-row">
      <div><label>Certificación *</label><input id="cert-name" required placeholder="CCNA, Cisco CCNP…"></div>
      <div><label>Código</label><input id="cert-code" placeholder="CSCO-12345"></div>
    </div>
    <div class="form-row">
      <div><label>Expedición</label><input type="date" id="cert-issued"></div>
      <div><label>Vencimiento</label><input type="date" id="cert-expires"></div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="document.getElementById('certs-modal').classList.remove('open')">Cerrar</button>
      <button type="submit" class="btn btn-primary">+ Añadir</button>
    </div>
  </form>
</div></div>

<!-- MODAL vacaciones / ausencias -->
<div class="modal-bg" id="vac-modal">
<div class="modal" style="max-width:540px">
  <h2 id="vac-title">Ausencias</h2>
  <div id="vac-list" style="max-height:220px;overflow-y:auto;margin-bottom:12px"></div>
  <form id="vac-form" style="border-top:1px solid var(--border);padding-top:12px">
    <div class="form-row">
      <div><label>Desde</label><input type="date" id="vac-from" required></div>
      <div><label>Hasta</label><input type="date" id="vac-to" required></div>
    </div>
    <div class="form-row">
      <div><label>Tipo</label><select id="vac-type">
        <option value="vacation">🏖 Vacaciones</option>
        <option value="day_off">📅 Día libre</option>
        <option value="sick">🤒 Baja médica</option>
      </select></div>
      <div><label>Notas</label><input id="vac-notes" placeholder="Opcional"></div>
    </div>
    <div class="modal-foot">
      <button type="button" class="btn btn-ghost" onclick="document.getElementById('vac-modal').classList.remove('open')">Cerrar</button>
      <button type="submit" class="btn btn-primary">+ Añadir</button>
    </div>
  </form>
</div></div>

<script>
/* ── Vacaciones / ausencias ── */
var _vacUid=null;
var _VAC_LABEL={{vacation:'🏖 Vacaciones',day_off:'📅 Día libre',sick:'🤒 Baja médica'}};
var _VAC_COLOR={{vacation:'#dbeafe',day_off:'#ede9fe',sick:'#fee2e2'}};
var _VAC_TC={{vacation:'#1d4ed8',day_off:'#6d28d9',sick:'#b91c1c'}};

function openVacations(uid,name){{
  _vacUid=uid;
  document.getElementById('vac-title').textContent='Ausencias — '+name;
  document.getElementById('vac-list').innerHTML='<span class="muted">Cargando…</span>';
  document.getElementById('vac-modal').classList.add('open');
  loadVacations();
}}
function loadVacations(){{
  fetch(bp+'/api/users/'+_vacUid+'/availability')
    .then(function(r){{return r.json();}}).then(renderVacations);
}}
function renderVacations(rows){{
  var el=document.getElementById('vac-list');
  if(!rows.length){{
    el.innerHTML='<p class="muted" style="text-align:center;padding:12px">Sin ausencias registradas.</p>';
    return;
  }}
  // group consecutive entries into ranges
  var groups=[],cur=null;
  rows.forEach(function(r){{
    if(cur&&cur.status===r.status&&cur.notes===r.notes&&_nextDay(cur.lastDate)===r.avail_date){{
      cur.ids.push(r.id); cur.lastDate=r.avail_date;
    }} else {{
      if(cur)groups.push(cur);
      cur={{ids:[r.id],status:r.status,notes:r.notes,firstDate:r.avail_date,lastDate:r.avail_date}};
    }}
  }});
  if(cur)groups.push(cur);
  el.innerHTML=groups.map(function(g){{
    var lbl=_VAC_LABEL[g.status]||g.status;
    var bg=_VAC_COLOR[g.status]||'#f1f5f9';
    var tc=_VAC_TC[g.status]||'#334155';
    function _fmtD(s){{return s?s.slice(8,10)+'-'+s.slice(5,7)+'-'+s.slice(0,4):s;}}
    var dateStr=g.firstDate===g.lastDate?_fmtD(g.firstDate):_fmtD(g.firstDate)+' → '+_fmtD(g.lastDate);
    var nts=g.notes?'<span class="muted" style="font-size:.75rem;margin-left:6px">'+g.notes+'</span>':'';
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--border)">'
      +'<div style="display:flex;align-items:center;gap:8px">'
      +'<span style="background:'+bg+';color:'+tc+';border-radius:5px;padding:2px 8px;font-size:.78rem;font-weight:600">'+lbl+'</span>'
      +'<span style="font-size:.85rem">'+dateStr+'</span>'+nts+'</div>'
      +'<button class="btn btn-danger btn-icon" onclick="delVacGroup('+JSON.stringify(g.ids)+')">✕</button>'
      +'</div>';
  }}).join('');
}}
function _nextDay(d){{
  var dt=new Date(d+'T12:00:00');dt.setDate(dt.getDate()+1);
  return dt.toISOString().slice(0,10);
}}
function delVacGroup(ids){{
  var dels=ids.map(function(id){{
    return fetch(bp+'/api/tech_availability/'+id,{{method:'DELETE'}});
  }});
  Promise.all(dels).then(function(){{loadVacations();}});
}}
document.getElementById('vac-form').onsubmit=function(e){{
  e.preventDefault();
  var from=getDateVal('vac-from');
  var to=getDateVal('vac-to');
  if(!from||!to)return;
  if(to<from){{Toast.show('La fecha de fin debe ser posterior al inicio','err');return;}}
  var d={{user_id:_vacUid,date_from:from,date_to:to,
    status:document.getElementById('vac-type').value,
    notes:document.getElementById('vac-notes').value}};
  fetch(bp+'/api/tech_availability/batch',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{
      if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}
      document.getElementById('vac-form').reset();
      Toast.show('Ausencia registrada ('+res.j.days+' días)','ok');
      loadVacations();
    }});
}};
document.getElementById('vac-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
</script>"""
    return _shell("users", user, content, title="Usuarios")
