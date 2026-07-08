"""App settings page: SMTP config + notification rules."""
import json
from core.db import BP
from core.helpers import _esc
from core.notify import get_setting
from web.layout import _shell

_EVENTS = [
    ("project_assigned",  "Proyecto asignado a técnico"),
    ("project_due_soon",  "Proyecto próximo a vencer"),
    ("task_overdue",      "Tarea vencida sin completar"),
    ("stock_low",         "Material por debajo del stock mínimo"),
    ("project_completed", "Proyecto marcado como completado"),
]


def _settings_page(user, rules: list):
    bp = BP
    smtp_host = _esc(get_setting("smtp_host"))
    smtp_port = _esc(get_setting("smtp_port", "587"))
    smtp_user = _esc(get_setting("smtp_user"))
    smtp_from = _esc(get_setting("smtp_from"))
    smtp_tls  = get_setting("smtp_tls", "1") == "1"
    due_days  = _esc(get_setting("notif_due_days", "2"))

    rules_by_key = {r["event_key"]: r for r in rules}

    rules_rows = ""
    for key, label in _EVENTS:
        r = rules_by_key.get(key, {"notify_internal": 1, "notify_email": 0})
        ni = "checked" if r["notify_internal"] else ""
        ne = "checked" if r["notify_email"]    else ""
        rules_rows += f"""
<tr>
  <td>{_esc(label)}</td>
  <td style="text-align:center">
    <input type="checkbox" class="rule-toggle" data-key="{key}" data-field="notify_internal"
           {ni} onchange="saveRule('{key}','notify_internal',this.checked)"
           style="width:18px;height:18px;accent-color:var(--primary);cursor:pointer">
  </td>
  <td style="text-align:center">
    <input type="checkbox" class="rule-toggle" data-key="{key}" data-field="notify_email"
           {ne} onchange="saveRule('{key}','notify_email',this.checked)"
           style="width:18px;height:18px;accent-color:var(--primary);cursor:pointer">
  </td>
</tr>"""

    content = f"""
<div class="toolbar"><h1>Configuración</h1></div>

<div class="card" style="max-width:680px;margin-bottom:20px">
  <h3 style="margin-top:0;margin-bottom:16px">📧 SMTP — Correo saliente</h3>
  <form id="smtp-form">
  <div class="form-row">
    <div><label>Servidor SMTP (host)</label>
      <input id="s-host" value="{smtp_host}" placeholder="smtp.gmail.com"></div>
    <div><label>Puerto</label>
      <input id="s-port" type="number" value="{smtp_port}" placeholder="587" style="max-width:100px"></div>
  </div>
  <div class="form-row">
    <div><label>Usuario</label>
      <input id="s-user" value="{smtp_user}" placeholder="user@empresa.com" autocomplete="off"></div>
    <div><label>Contraseña</label>
      <input id="s-pass" type="password" placeholder="••••••••" autocomplete="new-password"></div>
  </div>
  <div class="form-row">
    <div><label>Dirección remitente (From)</label>
      <input id="s-from" value="{smtp_from}" placeholder="nuvodesk@empresa.com"></div>
    <div style="display:flex;align-items:flex-end;padding-bottom:4px">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:.9rem">
        <input type="checkbox" id="s-tls" {"checked" if smtp_tls else ""}
               style="width:16px;height:16px;accent-color:var(--primary)">
        Usar TLS (STARTTLS)
      </label>
    </div>
  </div>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px">
    <button type="submit" class="btn btn-primary">Guardar SMTP</button>
    <span id="smtp-msg" style="font-size:.85rem"></span>
  </div>
  </form>
  <hr style="margin:20px 0;border-color:var(--border)">
  <div>
    <label style="font-size:.85rem;font-weight:600;display:block;margin-bottom:6px">
      Enviar correo de prueba
    </label>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <input id="test-email" type="email" placeholder="destino@ejemplo.com" style="flex:1;min-width:200px">
      <button class="btn btn-ghost" onclick="testEmail()">Enviar prueba</button>
    </div>
    <div id="test-msg" style="font-size:.85rem;margin-top:6px"></div>
  </div>
</div>

<div class="card" style="max-width:680px">
  <h3 style="margin-top:0;margin-bottom:4px">🔔 Reglas de notificaciones</h3>
  <p class="muted" style="font-size:.85rem;margin-bottom:16px">
    Los avisos internos aparecen en la campana de la barra lateral.<br>
    Los emails requieren que el usuario tenga dirección de correo configurada.
  </p>

  <div class="form-row" style="margin-bottom:16px;max-width:300px">
    <div>
      <label>Días de antelación para aviso de vencimiento</label>
      <input id="s-ddays" type="number" min="1" max="30" value="{due_days}"
             style="max-width:80px" onchange="saveDueDays(this.value)">
    </div>
  </div>

  <div class="tbl-wrap">
  <table>
    <thead><tr>
      <th>Evento</th>
      <th style="text-align:center;white-space:nowrap">Aviso interno</th>
      <th style="text-align:center;white-space:nowrap">Email</th>
    </tr></thead>
    <tbody>{rules_rows}</tbody>
  </table>
  </div>
</div>

<script>
var bp={json.dumps(BP)};
document.getElementById('smtp-form').onsubmit=function(e){{
  e.preventDefault();
  var d={{
    smtp_host:document.getElementById('s-host').value,
    smtp_port:document.getElementById('s-port').value,
    smtp_user:document.getElementById('s-user').value,
    smtp_from:document.getElementById('s-from').value,
    smtp_tls:document.getElementById('s-tls').checked?'1':'0'
  }};
  var pw=document.getElementById('s-pass').value;
  if(pw) d.smtp_pass=pw;
  fetch(bp+'/api/settings',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json();}})
    .then(function(j){{
      var el=document.getElementById('smtp-msg');
      el.textContent=j.ok?'✅ Guardado':'❌ '+(j.error||'Error');
      el.style.color=j.ok?'var(--green,#15803d)':'var(--red,#dc2626)';
      setTimeout(function(){{el.textContent='';}},3000);
    }});
}};
function testEmail(){{
  var to=document.getElementById('test-email').value.trim();
  if(!to){{Toast.show('Escribe una dirección de destino','err');return;}}
  var msg=document.getElementById('test-msg');
  msg.textContent='Enviando...';msg.style.color='var(--muted)';
  fetch(bp+'/api/settings/test_email',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{to:to}})}})
    .then(function(r){{return r.json();}})
    .then(function(j){{
      msg.textContent=j.ok?'✅ Enviado correctamente':'❌ '+(j.error||'Error');
      msg.style.color=j.ok?'var(--green,#15803d)':'var(--red,#dc2626)';
    }});
}}
function saveRule(key,field,val){{
  var d={{}};d[field]=val?1:0;
  fetch(bp+'/api/notif_rules/'+key,{{method:'PUT',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
}}
function saveDueDays(v){{
  fetch(bp+'/api/settings',{{method:'PUT',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{notif_due_days:v}})}});
}}
</script>"""
    return _shell("settings", user, content, title="Configuración")
