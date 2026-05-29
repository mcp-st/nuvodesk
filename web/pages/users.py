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
        phone_str = _esc(u.get("phone") or "")
        phone_td = f'<span style="font-size:.78rem;color:var(--muted)">{phone_str}</span>' if phone_str else ""
        rows += (f'<tr>'
            f'<td class="fw7">{full}</td>'
            f'<td class="muted" style="font-size:.82rem">{_esc(u["username"])}</td>'
            f'<td>{_esc(role_lbl)}</td>'
            f'<td>{active_dot}</td>'
            f'<td class="col-m-hide">{_esc(u.get("email") or "")}</td>'
            f'<td class="col-m-hide">{phone_td}</td>'
            f'<td><button class="btn btn-ghost btn-icon" data-user="{user_attr}" '
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

<div class="modal-bg" id="del-confirm-modal">
<div class="modal" style="max-width:380px;text-align:center">
  <div style="font-size:2rem;margin-bottom:12px">⚠️</div>
  <h2 style="margin-bottom:8px">¿Eliminar usuario?</h2>
  <p class="muted" style="margin-bottom:24px;font-size:.88rem">Esta acción no se puede deshacer.</p>
  <div style="display:flex;gap:10px;justify-content:center">
    <button id="del-confirm-cancel" class="btn btn-ghost">Cancelar</button>
    <button id="del-confirm-ok" class="btn btn-danger">Eliminar</button>
  </div>
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
    send_welcome:(!id&&document.getElementById('u-send-welcome').checked)?true:false
  }};
  if(pw) d.password=pw;
  fetch(id?bp+'/api/users/'+id:bp+'/api/users',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{
      if(r.ok){{
        r.json().then(function(j){{
          if(j.welcome_sent) alert('Usuario creado. Email de bienvenida enviado a '+d.email+'.');
          else if(j.welcome_error) alert('Usuario creado, pero error al enviar email: '+j.welcome_error);
          location.reload();
        }});
      }} else r.json().then(function(j){{alert(j.error||'Error');}});
    }}).catch(function(){{alert('Error de red al guardar usuario.');}});
}};

var _delConfirmId=null;
function delUser(id){{
  _delConfirmId=id;
  document.getElementById('del-confirm-modal').classList.add('open');
}}
document.getElementById('del-confirm-ok').onclick=function(){{
  var id=_delConfirmId;
  document.getElementById('del-confirm-modal').classList.remove('open');
  fetch(bp+'/api/users/'+id,{{method:'DELETE'}})
    .then(function(r){{
      if(r.ok){{ location.reload(); return; }}
      return r.text().then(function(t){{
        try{{var j=JSON.parse(t);alert(j.error||'Error al eliminar usuario.');}}
        catch(e){{alert('Error al eliminar usuario ('+r.status+').');}}
      }});
    }}).catch(function(){{alert('Error de red al eliminar usuario.');}});
}};
document.getElementById('del-confirm-cancel').onclick=function(){{
  document.getElementById('del-confirm-modal').classList.remove('open');
}};
</script>"""
    return _shell("users", user, content)
