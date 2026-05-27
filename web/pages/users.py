"""Users management page."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
)
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
