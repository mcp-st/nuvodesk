"""Calendar pages — Mes / Semana / Día."""
import json, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import BP, q, q1, rs, r2d
from core.helpers import _esc, _pcolor, _fd
from web.layout import _shell

_MONTH_NAMES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
_DOW_SHORT   = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
_DOW_FULL    = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
_TYPE_ICON   = {"physical":"⚡","online":"🌐","meeting":"👥","travel":"✈️","other":"📌"}
_TYPE_LABEL  = {"physical":"Presencial","online":"Online","meeting":"Reunión","travel":"Viaje","other":"Otro"}

_PEVENT_ICON  = {"training":"🎓","vendor":"🤝","presentation":"📢","personal":"👤","other":"📌"}
_PEVENT_LABEL = {"training":"Formación","vendor":"Proveedor","presentation":"Presentación","personal":"Personal","other":"Otro"}
_PEVENT_COLOR = "#d97706"  # amber — distinguishable from project activities
_AVAIL_ICON  = {"available":"","remote":"🏠","traveling":"✈️","off":"—",
                "vacation":"🏖","day_off":"📅","sick":"🤒"}
_AVAIL_LABEL = {"available":"Disponible","remote":"Remoto","traveling":"Desplazado","off":"Libre",
                "vacation":"Vacaciones","day_off":"Día libre","sick":"Baja médica"}
_AVAIL_COLOR = {"available":"#16a34a","remote":"#3b82f6","traveling":"#d97706","off":"#94a3b8",
                "vacation":"#2563eb","day_off":"#7c3aed","sick":"#dc2626"}
_AVAIL_BG    = {"off":"var(--border)","traveling":"repeating-linear-gradient(45deg,transparent,transparent 3px,rgba(255,165,0,.15) 3px,rgba(255,165,0,.15) 6px)",
                "vacation":"#dbeafe","day_off":"#ede9fe","sick":"#fee2e2"}


def _avail_picker_html(uid, d_str, status, is_admin, compact=True):
    """Availability badge. Admin gets a clickable dropdown picker."""
    icon  = _AVAIL_ICON.get(status, "") or "✓"
    label = _AVAIL_LABEL.get(status, status)
    color = _AVAIL_COLOR.get(status, "#16a34a")
    if not is_admin:
        return (f'<span title="{label}" style="font-size:.6rem">{icon}</span>'
                if status not in ("available", "") else "")
    uid_js  = json.dumps(uid)
    date_js = json.dumps(d_str)
    size    = ".6rem" if compact else ".72rem"
    badge   = (f'background:{color};color:#fff;border:none;border-radius:4px;'
               f'padding:1px 5px;font-size:{size};cursor:pointer;line-height:1.5;white-space:nowrap')
    opts    = "".join(
        f'<button onclick="setAvail({uid_js},{date_js},\'{s}\')" '
        f'style="background:{_AVAIL_COLOR[s]};color:#fff;border:none;border-radius:5px;'
        f'padding:4px 8px;font-size:.72rem;cursor:pointer;text-align:left;white-space:nowrap;display:block;width:100%">'
        f'{_AVAIL_ICON.get(s,"") or "✓"} {_AVAIL_LABEL[s]}</button>'
        for s in ("available", "remote", "traveling", "off", "vacation", "day_off", "sick"))
    text = f' {label}' if not compact else ""
    return (f'<div class="avp" style="position:relative;display:inline-block">'
            f'<button class="avp-btn" onclick="toggleAvp(this)" style="{badge}" title="{label}">'
            f'{icon}{text}</button>'
            f'<div class="avp-menu" style="display:none;position:fixed;z-index:9999;top:0;left:0;'
            f'background:var(--surface,#fff);border:1px solid var(--border);border-radius:8px;'
            f'padding:5px;gap:3px;flex-direction:column;min-width:130px;'
            f'box-shadow:0 4px 16px rgba(0,0,0,.18)">{opts}</div></div>')


def _avail_cr_js():
    """Shared JS for availability picker and change-request resolution."""
    return """
function toggleAvp(btn){
  document.querySelectorAll('.avp-menu').forEach(function(m){m.style.display='none';});
  var m=btn.nextElementSibling;
  if(m.style.display==='flex'){m.style.display='none';return;}
  var r=btn.getBoundingClientRect();
  m.style.position='fixed';
  m.style.zIndex='9999';
  m.style.top=(r.bottom+4)+'px';
  var left=r.left;
  if(left+160>window.innerWidth)left=window.innerWidth-164;
  m.style.left=left+'px';
  m.style.bottom='auto';
  m.style.display='flex';
}
function setAvail(uid,date,status){
  fetch(bp+'/api/tech_availability',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id:uid,avail_date:date,status:status})})
  .then(function(r){if(r.ok)location.reload();});
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.avp'))
    document.querySelectorAll('.avp-menu').forEach(function(m){m.style.display='none';});
});
function resolveCR(id,action){
  ConfirmDialog.show(action==='approve'?'¿Aprobar esta solicitud?':'¿Rechazar esta solicitud?','')
    .then(function(ok){
      if(!ok)return;
      fetch(bp+'/api/change_requests/'+id+'/resolve',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:action})})
      .then(function(r){if(r.ok)location.reload();else r.json().then(function(j){Toast.show(j.error||'Error','err');});});
    });
}"""


def _pending_cr_panel(user):
    """Card listing pending change requests for admin review."""
    if user.get("role") != "admin":
        return ""
    crs = rs(q("""SELECT cr.*,u.display_name uname,p.name pname,
        a.activity_date,a.hour_start,a.hour_end,a.all_day
        FROM change_requests cr
        JOIN activities a ON a.id=cr.activity_id
        JOIN users u ON u.id=cr.requester_id
        JOIN projects p ON p.id=a.project_id
        WHERE cr.status='pending'
        ORDER BY cr.created_at"""))
    if not crs:
        return ""
    type_lbl = {"cancel":"Cancelar","reschedule":"Reagendar","modify":"Modificar"}
    rows = ""
    for cr in crs:
        if cr["all_day"] or cr["hour_start"] is None:
            time_str = "Todo el día"
        else:
            time_str = f'{cr["hour_start"]:02d}:00–{cr["hour_end"]:02d}:00'
        rows += (
            f'<div style="display:flex;align-items:flex-start;gap:12px;padding:10px 0;'
            f'border-bottom:1px solid var(--border);flex-wrap:wrap">'
            f'<div style="flex:1;min-width:180px">'
            f'<div style="font-weight:700;font-size:.85rem">{_esc(cr["uname"])}'
            f' · <a href="{BP}/calendar/{cr["activity_date"]}" style="color:var(--primary)">'
            f'{_fd(cr["activity_date"])}</a></div>'
            f'<div style="font-size:.75rem;color:var(--muted)">'
            f'{type_lbl.get(cr["type"],cr["type"])} · {_esc(cr["pname"])} · {time_str}</div>'
            f'<div style="font-size:.8rem;margin-top:4px;font-style:italic">{_esc(cr["message"])}</div>'
            f'</div>'
            f'<div style="display:flex;gap:6px;flex-shrink:0;align-self:center">'
            f'<button class="btn btn-primary btn-sm" style="font-size:.75rem" '
            f'onclick="resolveCR({cr["id"]},\'approve\')">✓ Aprobar</button>'
            f'<button class="btn btn-danger btn-sm" style="font-size:.75rem" '
            f'onclick="resolveCR({cr["id"]},\'reject\')">✕ Rechazar</button>'
            f'</div></div>')
    return (f'<div class="card" style="border-left:4px solid #d97706;padding:14px 16px;margin-bottom:16px">'
            f'<div style="font-weight:700;margin-bottom:6px">⚠️ Solicitudes de cambio pendientes ({len(crs)})</div>'
            f'{rows}</div>')


def _load_techs():
    return rs(q("SELECT id,display_name FROM users WHERE active=1 AND show_in_planning=1 ORDER BY display_name"))


def _load_projs():
    return rs(q("SELECT id,name FROM projects WHERE status IN ('active','paused') ORDER BY name"))


def _avail_map(date_list):
    if not date_list: return {}
    ph = ",".join("?" * len(date_list))
    rows = rs(q(f"SELECT user_id,avail_date,status FROM tech_availability WHERE avail_date IN ({ph})",
                tuple(date_list)))
    return {(r["user_id"], r["avail_date"]): r["status"] for r in rows}


def _hour_select_start(selected=8):
    return "".join(
        f'<option value="{h}"{" selected" if h==selected else ""}>'
        f'{"0" if h<10 else ""}{h}:00</option>'
        for h in range(6, 20))


def _hour_select_end(selected=10):
    return "".join(
        f'<option value="{h}"{" selected" if h==selected else ""}>'
        f'{"0" if h<10 else ""}{h}:00</option>'
        for h in range(7, 21))


def _type_options():
    return "".join(
        f'<option value="{k}">{_TYPE_ICON[k]} {v}</option>'
        for k, v in _TYPE_LABEL.items())


def _user_options(exclude_roles=("backoffice",)):
    users = rs(q("SELECT id,display_name FROM users WHERE active=1 ORDER BY display_name"))
    return "".join(f'<option value="{u["id"]}">{_esc(u["display_name"])}</option>' for u in users)


def _pevent_type_options():
    return "".join(
        f'<option value="{k}">{_PEVENT_ICON[k]} {v}</option>'
        for k, v in _PEVENT_LABEL.items())


def _personal_event_modal(today_str, is_admin, pfx="pem"):
    admin_user_row = ""
    if is_admin:
        admin_user_row = (
            f'<div class="form-row single"><div><label>Técnico</label>'
            f'<select id="{pfx}-user">{_user_options()}</select></div></div>'
        )
    return f"""
<div class="modal-bg" id="pev-modal">
<div class="modal" style="max-width:480px">
  <h2>Nuevo evento personal</h2>
  {admin_user_row}
  <div class="form-row single">
    <div><label>Título</label><input id="{pfx}-title" placeholder="Ej: Formación Cisco, Reunión proveedor…"></div>
  </div>
  <div class="form-row">
    <div><label>Tipo</label><select id="{pfx}-type">{_pevent_type_options()}</select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha inicio</label><input type="date" id="{pfx}-date" value="{today_str}"></div>
    <div><label>Fecha fin (opcional)</label><input type="date" id="{pfx}-date-end"></div>
  </div>
  <div class="form-row single">
    <div><label><input type="checkbox" id="{pfx}-allday" onchange="togglePevAllDay()" checked> Todo el día</label></div>
  </div>
  <div class="form-row" id="{pfx}-hours-row" style="display:none">
    <div><label>Hora inicio</label><select id="{pfx}-hs">{_hour_select_start()}</select></div>
    <div><label>Hora fin</label><select id="{pfx}-he">{_hour_select_end()}</select></div>
  </div>
  <div class="form-row single"><div><label>Notas</label><input id="{pfx}-notes" placeholder="Opcional"></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost"
      onclick="document.getElementById('pev-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doCreatePev()">Guardar</button>
  </div>
</div></div>"""


def _personal_event_js(is_admin, pfx="pem"):
    user_field = (f"user_id:document.getElementById('{pfx}-user').value,"
                  if is_admin else "")
    return f"""
document.getElementById('pev-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function togglePevAllDay(){{
  var ad=document.getElementById('{pfx}-allday');
  var row=document.getElementById('{pfx}-hours-row');
  if(row) row.style.display=ad.checked?'none':'';
}}
function doCreatePev(){{
  var title=document.getElementById('{pfx}-title').value.trim();
  if(!title){{Toast.show('El título es obligatorio','err');return;}}
  var ad=document.getElementById('{pfx}-allday');
  var allday=ad?ad.checked:true;
  var d={{
    {user_field}
    title:title,
    event_type:document.getElementById('{pfx}-type').value,
    event_date:getDateVal('{pfx}-date'),
    date_end:getDateVal('{pfx}-date-end'),
    all_day:allday?1:0,
    hour_start:allday?null:parseInt(document.getElementById('{pfx}-hs').value),
    hour_end:allday?null:parseInt(document.getElementById('{pfx}-he').value),
    notes:document.getElementById('{pfx}-notes').value
  }};
  fetch(bp+'/api/personal_events',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{
      if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}
      location.reload();
    }});
}}
function delPersonalEvent(id){{
  ConfirmDialog.show('¿Eliminar este evento?','')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/personal_events/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}"""


def _proj_options():
    return "".join(
        f'<option value="{p["id"]}">{_esc(p["name"])}</option>'
        for p in _load_projs())


def _activity_modal(today_str, id_prefix="am"):
    """Returns HTML for the new-activity modal (admin only)."""
    return f"""
<div class="modal-bg" id="act-modal">
<div class="modal" style="max-width:500px">
  <h2>Nueva actividad</h2>
  <div class="form-row">
    <div><label>Técnico</label><select id="{id_prefix}-user">{_user_options()}</select></div>
    <div><label>Proyecto</label><select id="{id_prefix}-proj">{_proj_options()}</select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha</label><input type="date" id="{id_prefix}-date" value="{today_str}"></div>
    <div><label>Tipo</label><select id="{id_prefix}-type">{_type_options()}</select></div>
  </div>
  <div class="form-row">
    <div><label>Hora inicio</label><select id="{id_prefix}-hs">{_hour_select_start()}</select></div>
    <div><label>Hora fin</label><select id="{id_prefix}-he">{_hour_select_end()}</select></div>
  </div>
  <div class="form-row single">
    <div><label><input type="checkbox" id="{id_prefix}-allday" onchange="toggleAllDay()"> Todo el día</label></div>
  </div>
  <div class="form-row single"><div><label>Notas</label><input id="{id_prefix}-notes" placeholder="Opcional"></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost"
      onclick="document.getElementById('act-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doCreateActivity()">Guardar</button>
  </div>
</div></div>"""


def _activity_js(pfx="am"):
    return f"""
document.getElementById('act-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function toggleAllDay(){{
  var ad=document.getElementById('{pfx}-allday');
  if(!ad) return;
  document.getElementById('{pfx}-hs').disabled=ad.checked;
  document.getElementById('{pfx}-he').disabled=ad.checked;
}}
function doCreateActivity(){{
  var ad=document.getElementById('{pfx}-allday');
  var allday=ad?ad.checked:false;
  var d={{
    user_id:document.getElementById('{pfx}-user').value,
    project_id:document.getElementById('{pfx}-proj').value,
    activity_date:getDateVal('{pfx}-date'),
    type:document.getElementById('{pfx}-type').value,
    all_day:allday?1:0,
    hour_start:allday?null:parseInt(document.getElementById('{pfx}-hs').value),
    hour_end:allday?null:parseInt(document.getElementById('{pfx}-he').value),
    notes:document.getElementById('{pfx}-notes').value
  }};
  fetch(bp+'/api/activities',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{
      if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}
      if(res.j.warning){{Toast.show('Aviso: '+res.j.warning,'warn');}}
      location.reload();
    }});
}}"""


# ── Sidebar helpers ────────────────────────────────────────────────────────────

def _mini_cal_html(year, month, today, bp):
    """Grid HTML for the sidebar mini-calendar."""
    first = _date(year, month, 1)
    _, dim = _cal.monthrange(year, month)
    start_dow = first.weekday()  # 0=Mon
    prev_y, prev_m = (year, month-1) if month > 1 else (year-1, 12)
    next_y, next_m = (year, month+1) if month < 12 else (year+1, 1)
    html = (f'<div class="mc-nav">'
            f'<a href="{bp}/calendar?year={prev_y}&month={prev_m}" class="mc-arr">‹</a>'
            f'<div class="mc-title">{_MONTH_NAMES[month-1]} {year}</div>'
            f'<a href="{bp}/calendar?year={next_y}&month={next_m}" class="mc-arr">›</a>'
            f'</div><div class="mc-g">')
    for d in _DOW_SHORT:
        html += f'<div class="mc-dh">{d}</div>'
    for _ in range(start_dow):
        html += '<div class="mc-d mc-oth"></div>'
    for day in range(1, dim + 1):
        d = _date(year, month, day)
        d_str = str(d)
        cls = "mc-d mc-tod" if d == today else "mc-d"
        html += f'<a href="{bp}/calendar/{d_str}" class="{cls}">{day}</a>'
    html += '</div>'
    return html


def _right_panel(user, year, month, today, is_admin):
    """240px right sidebar: mini-cal + team today + legend."""
    mini = _mini_cal_html(year, month, today, BP)

    today_str = str(today)
    t_avail = _avail_map([today_str])
    techs = _load_techs()

    tech_rows = ""
    for t in techs:
        status = t_avail.get((t["id"], today_str), "available")
        color  = _AVAIL_COLOR.get(status, "#16a34a")
        initials = "".join(w[0].upper() for w in t["display_name"].split()[:2])
        tc = _pcolor(t["id"])
        avp = _avail_picker_html(t["id"], today_str, status, is_admin, compact=True)
        tech_rows += (f'<div class="ts-item">'
                      f'<div class="avatar avatar-sm" style="background:{tc}">{_esc(initials)}</div>'
                      f'<div class="ts-name">{_esc(t["display_name"].split()[0])}</div>'
                      f'{avp}</div>')

    legend_act = "".join(
        f'<div class="leg-row"><div class="leg-dot" style="background:{c}"></div>{_esc(l)}</div>'
        for c, l in [("#3b82f6","⚡ Presencial"),("#8b5cf6","🌐 Online"),
                     ("#dc2626","👥 Reunión"),("#f97316","✈️ Viaje"),("#64748b","📌 Otro")])
    legend_avail = "".join(
        f'<div class="leg-row"><div class="leg-dot round" style="background:{_AVAIL_COLOR[s]}"></div>{_AVAIL_LABEL[s]}</div>'
        for s in ("available","remote","traveling","vacation","day_off","sick","off"))

    return f"""<div class="cal-sidebar">
  <div class="mini-cal">{mini}</div>
  <div>
    <div class="cal-sb-title">Equipo hoy</div>
    {tech_rows}
  </div>
  <div style="margin-top:auto">
    <div class="cal-sb-title">Tipos de actividad</div>
    {legend_act}
    <div class="cal-sb-title" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">Disponibilidad</div>
    {legend_avail}
  </div>
</div>"""


# ── Month view (calp — productivity redesign) ──────────────────────────────────

# Colores rotativos para técnicos (índice en lista ordenada)
_TECH_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#a78bfa", "#ec4899", "#06b6d4"]

# Mapeo tipo de actividad → emoji
_TYPE_EMOJI = {
    "physical": "🔧",
    "online":   "🌐",
    "meeting":  "👥",
    "travel":   "✈️",
    "other":    "📌",
}

# Colores de tipo de actividad para dots en panel de detalle
_TYPE_DOT_COLOR = {
    "physical": "#3b82f6",
    "online":   "#8b5cf6",
    "meeting":  "#dc2626",
    "travel":   "#d97706",
    "other":    "#64748b",
}

_DOW_NAMES_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_MONTH_NAMES_ES = _MONTH_NAMES  # alias

# Icono overlay según disponibilidad
_AVAIL_ICON_OVERLAY = {
    "available": "✓",
    "remote":    "✓",
    "off":       "–",
    "day_off":   "–",
    "sick":      "✕",
    "vacation":  "✈",
    "traveling": "⊙",
}

# Label corto para tooltip de avatar
_AVAIL_LABEL_SHORT = {
    "available": "Disponible",
    "remote":    "Remoto",
    "off":       "Sin asignar",
    "day_off":   "Día libre",
    "sick":      "Baja médica",
    "vacation":  "Vacaciones",
    "traveling": "Desplazado",
}


def _tech_initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def _heat_level(act_count: int) -> int:
    if act_count == 0: return 0
    if act_count <= 2: return 1
    if act_count <= 4: return 2
    if act_count <= 6: return 3
    if act_count <= 8: return 4
    return 5


def _occ_info(active_count: int, total: int):
    if total == 0:
        return 0, "low"
    pct = round((active_count / total) * 100)
    level = "low" if pct < 40 else ("medium" if pct < 75 else "high")
    return pct, level


def _calendar_page(user, year, month):
    today = _date.today()
    if month < 1:  year -= 1; month = 12
    if month > 12: year += 1; month = 1
    first = _date(year, month, 1)
    _, dim = _cal.monthrange(year, month)
    prev_y, prev_m = (year, month-1) if month > 1 else (year-1, 12)
    next_y, next_m = (year, month+1) if month < 12 else (year+1, 1)

    d1 = f"{year:04d}-{month:02d}-01"
    d2 = f"{year:04d}-{month:02d}-{dim:02d}"

    # Cargar técnicos activos con show_in_planning
    techs = _load_techs()

    # Asignar colores rotativos por índice
    tech_color = {t["id"]: _TECH_COLORS[i % len(_TECH_COLORS)] for i, t in enumerate(techs)}

    # Cargar actividades del mes
    activities = rs(q("""SELECT a.*,u.display_name uname,p.name pname
        FROM activities a JOIN users u ON u.id=a.user_id JOIN projects p ON p.id=a.project_id
        WHERE a.activity_date BETWEEN ? AND ?
        ORDER BY a.activity_date,a.hour_start""", (d1, d2)))

    # act_map: {(user_id, date_str): [activity, ...]}
    act_map: dict = {}
    for a in activities:
        act_map.setdefault((a["user_id"], a["activity_date"]), []).append(a)

    # Cargar eventos personales del mes (multi-day: event_date..date_end span)
    personal_events_month = rs(q("""SELECT pe.*,u.display_name uname
        FROM personal_events pe JOIN users u ON u.id=pe.user_id
        WHERE pe.event_date<=? AND (pe.date_end='' OR pe.date_end IS NULL OR pe.date_end>=?)
        ORDER BY pe.event_date""", (d2, d1)))

    # pev_map: {date_str: [event, ...]} + pev_user_days for availability override
    pev_map: dict = {}
    pev_user_days: set = set()
    for ev in personal_events_month:
        start = ev["event_date"]
        end   = ev["date_end"] or start
        try:
            cur_d = _date.fromisoformat(start)
            end_d = _date.fromisoformat(end) if end else cur_d
        except ValueError:
            continue
        while cur_d <= end_d:
            d_s = str(cur_d)
            if d1 <= d_s <= d2:
                pev_map.setdefault(d_s, []).append(ev)
                pev_user_days.add((ev["user_id"], d_s))
            cur_d += timedelta(days=1)

    # Disponibilidad del mes
    date_list = [str(first + timedelta(days=i)) for i in range(dim)]
    avail = _avail_map(date_list)

    is_admin = user.get("role") == "admin"
    today_monday = str(today - timedelta(days=today.weekday()))
    cr_panel = _pending_cr_panel(user)

    # ── Estadísticas del mes ──────────────────────────────────────────
    month_stats = {"assigned": 0, "available_days": 0, "vacation_days": 0,
                   "sick_days": 0}

    # ── Grid mensual ──────────────────────────────────────────────────
    grid_start = first - timedelta(days=first.weekday())
    cells_html = ""
    cur = grid_start

    # JSON de datos por día para el panel de detalle (JS)
    # Estructura: {day_num: {techs:[{id,name,initials,color,avail,acts:[]}], acts:[{type,pname,uname,desc}]}}
    day_data: dict = {}

    for _ in range(42):
        d_str = str(cur)
        in_m     = (cur.month == month)
        is_tod   = (cur == today)
        is_wkend = (cur.weekday() >= 5)

        if not in_m:
            cells_html += (
                f'<div class="calp-day-cell other-month">'
                f'<div class="calp-day-top">'
                f'<span class="calp-day-num">{cur.day}</span>'
                f'</div></div>'
            )
            cur += timedelta(days=1)
            continue

        # Recopilar datos de técnicos para este día
        day_tech_data = []
        day_acts_all = []
        act_count_total = 0
        active_tech_count = 0  # técnicos con actividad

        for t in techs:
            tid = t["id"]
            avail_status = avail.get((tid, d_str), "available")
            if (tid, d_str) in pev_user_days and avail_status in ("available", "remote", ""):
                avail_status = "day_off"
            day_acts_tech = act_map.get((tid, d_str), [])
            has_act = bool(day_acts_tech) and not is_wkend
            if has_act:
                active_tech_count += 1
                act_count_total += len(day_acts_tech)
                # Estadísticas mensuales
                month_stats["assigned"] += len(day_acts_tech)
            elif not is_wkend:
                if avail_status == "vacation":
                    month_stats["vacation_days"] += 1
                elif avail_status == "sick":
                    month_stats["sick_days"] += 1
                elif avail_status == "available":
                    month_stats["available_days"] += 1
            day_tech_data.append({
                "id": tid,
                "name": t["display_name"],
                "initials": _tech_initials(t["display_name"]),
                "color": tech_color[tid],
                "avail": avail_status,
                "acts": [{"type": a.get("type","other"),
                           "pname": a["pname"],
                           "uname": a["uname"],
                           "all_day": a.get("all_day",0),
                           "hour_start": a.get("hour_start"),
                           "hour_end": a.get("hour_end")} for a in day_acts_tech]
            })
            for a in day_acts_tech:
                day_acts_all.append({
                    "type": a.get("type","other"),
                    "pname": a["pname"],
                    "uname": a["uname"],
                    "tech_name": t["display_name"],
                })

        # Personal events for this day
        day_pevents = pev_map.get(d_str, [])
        day_data[cur.day] = {"techs": day_tech_data, "acts": day_acts_all,
                             "pevents": [{"id": e["id"], "title": e["title"],
                                          "event_type": e.get("event_type","other"),
                                          "uname": e["uname"]} for e in day_pevents]}

        heat = _heat_level(act_count_total) if not is_wkend else 0
        pct, occ_level = _occ_info(active_tech_count, len(techs)) if not is_wkend else (0, "low")

        today_cls   = " today"   if is_tod   else ""
        weekend_cls = " weekend" if is_wkend else ""

        # Número del día
        day_num_html = f'<span class="calp-day-num">{cur.day}</span>'

        # Badge de actividades
        if act_count_total == 0:
            badge_cls = "calp-act-badge zero"
            badge_txt = "·"
        else:
            badge_cls = "calp-act-badge"
            badge_txt = str(act_count_total)
        badge_html = f'<span class="{badge_cls}">{badge_txt}</span>'

        # Fila de avatares (máx 4 técnicos; si hay más, mostrar "+N")
        avatars_html = '<div class="calp-avatar-row">'
        visible_techs_av = day_tech_data[:4]
        for td in visible_techs_av:
            icon = _AVAIL_ICON_OVERLAY.get(td["avail"], "✓")
            label = _AVAIL_LABEL_SHORT.get(td["avail"], "Disponible")
            acts_count = len(td["acts"])
            tip = f'{_esc(td["name"])} | {_esc(label)} | {acts_count} act.'
            avatars_html += (
                f'<div class="calp-avatar" data-avail="{_esc(td["avail"])}" '
                f'data-icon="{_esc(icon)}" '
                f'data-tech-name="{_esc(td["name"])}" '
                f'data-tech-avail="{_esc(label)}" '
                f'data-tech-acts="{acts_count}" '
                f'style="background:{td["color"]}">'
                f'{_esc(td["initials"])}</div>'
            )
        if len(day_tech_data) > 4:
            extra = len(day_tech_data) - 4
            avatars_html += (
                f'<div class="calp-avatar" style="background:var(--muted);font-size:.55rem">'
                f'+{extra}</div>'
            )
        avatars_html += '</div>'

        # Chips de actividad (máx 3 visibles)
        day_pevents = pev_map.get(d_str, [])
        slots_available = 3
        chips_html = '<div class="calp-chips">'
        shown_acts = day_acts_all[:slots_available]
        for act in shown_acts:
            atype = act["type"]
            emoji = _TYPE_EMOJI.get(atype, "📌")
            dot_color = _TYPE_DOT_COLOR.get(atype, "#64748b")
            short_name = act["pname"][:18] if act["pname"] else ""
            chips_html += (
                f'<div class="calp-chip {_esc(atype)}">'
                f'<div class="calp-chip-dot" style="background:{dot_color}"></div>'
                f'{emoji} {_esc(short_name)}'
                f'</div>'
            )
        remaining = slots_available - len(shown_acts)
        overflow_acts = max(0, len(day_acts_all) - slots_available)
        # Personal event chips (ámbar, after activity chips)
        shown_pev = day_pevents[:max(0, remaining)]
        for ev in shown_pev:
            etype = ev.get("event_type","other")
            icon = _PEVENT_ICON.get(etype, "📌")
            short_title = ev["title"][:16] if ev.get("title") else ""
            chips_html += (
                f'<div class="calp-chip" style="border-left:2px solid {_PEVENT_COLOR}">'
                f'<div class="calp-chip-dot" style="background:{_PEVENT_COLOR}"></div>'
                f'{icon} {_esc(short_title)}'
                f'</div>'
            )
        overflow_pev = max(0, len(day_pevents) - len(shown_pev))
        total_overflow = overflow_acts + overflow_pev
        if total_overflow > 0:
            chips_html += f'<div class="calp-chip more">+{total_overflow} más</div>'
        chips_html += '</div>'

        # Barra de ocupación
        occ_bar_html = ""
        if not is_wkend:
            occ_bar_html = (
                f'<div class="calp-occ-bar-wrap">'
                f'<div class="calp-occ-bar-track">'
                f'<div class="calp-occ-bar-fill {occ_level}" style="width:{pct}%"></div>'
                f'</div></div>'
            )

        cells_html += (
            f'<div class="calp-day-cell{today_cls}{weekend_cls}" '
            f'data-day="{cur.day}" data-dstr="{d_str}" data-heat="{heat}" '
            f'data-dow="{cur.weekday()}">'
            f'<div class="calp-day-top">'
            f'{day_num_html}{badge_html}'
            f'</div>'
            f'{avatars_html}'
            f'{chips_html if not is_wkend else ""}'
            f'{occ_bar_html}'
            f'</div>'
        )
        cur += timedelta(days=1)

    # ── DOW headers ───────────────────────────────────────────────────
    dow_headers_html = ""
    for i, d in enumerate(_DOW_SHORT):
        wknd_cls = ' weekend' if i >= 5 else ''
        dow_headers_html += f'<div class="calp-dow-cell{wknd_cls}">{d}</div>'

    # ── Sidebar: mini-calendario ──────────────────────────────────────
    mini_grid_html = ""
    mini_start = first - timedelta(days=first.weekday())
    mini_cur = mini_start
    for _ in range(42):
        if mini_cur.month != month:
            mini_grid_html += f'<div class="calp-mini-day other">{mini_cur.day}</div>'
        else:
            is_tod_m = (mini_cur == today)
            is_wknd_m = (mini_cur.weekday() >= 5)
            cls = "calp-mini-day"
            if is_tod_m:    cls += " today"
            elif is_wknd_m: cls += " weekend"
            mini_grid_html += f'<div class="{cls}" data-day="{mini_cur.day}">{mini_cur.day}</div>'
        mini_cur += timedelta(days=1)

    # ── Sidebar: equipo hoy ───────────────────────────────────────────
    today_str = str(today)
    today_avail = _avail_map([today_str])
    team_today_html = ""
    for t in techs:
        col = tech_color[t["id"]]
        init = _tech_initials(t["display_name"])
        avail_status = today_avail.get((t["id"], today_str), "available")
        if (t["id"], today_str) in pev_user_days and avail_status in ("available", "remote", ""):
            avail_status = "day_off"
        day_acts_today = act_map.get((t["id"], today_str), [])
        has_act_today = bool(day_acts_today)
        if has_act_today:
            dot_cls, status_label = "busy", "Asignado"
        elif avail_status == "available":
            dot_cls, status_label = "online", "Disponible"
        elif avail_status == "vacation":
            dot_cls, status_label = "offline", "Vacaciones"
        elif avail_status == "sick":
            dot_cls, status_label = "offline", "Baja"
        elif avail_status == "traveling":
            dot_cls, status_label = "busy", "Desplazado"
        elif avail_status == "day_off":
            dot_cls, status_label = "offline", "Evento personal"
        else:
            dot_cls, status_label = "offline", _AVAIL_LABEL_SHORT.get(avail_status, "Libre")
        avp = _avail_picker_html(t["id"], today_str, avail_status, is_admin, compact=True)
        team_today_html += (
            f'<div class="calp-team-member">'
            f'<div class="calp-member-avatar" style="background:{col}">{_esc(init)}</div>'
            f'<div class="calp-member-info">'
            f'<div class="calp-member-name">{_esc(t["display_name"])}</div>'
            f'<div class="calp-member-role">{_esc(status_label)}</div>'
            f'</div>'
            f'{avp}'
            f'<div class="calp-member-dot {dot_cls}"></div>'
            f'</div>'
        )

    # ── Sidebar: 4 tarjetas de estadísticas ──────────────────────────
    # Calcular ocupación media del mes
    occ_vals = []
    for d_num in range(1, dim + 1):
        d_s = f"{year:04d}-{month:02d}-{d_num:02d}"
        d_date = _date(year, month, d_num)
        if d_date.weekday() >= 5:
            continue
        active = sum(1 for t in techs if act_map.get((t["id"], d_s)))
        if active > 0 or True:  # include all weekdays
            if len(techs) > 0:
                occ_vals.append(round((active / len(techs)) * 100))
    occ_media = round(sum(occ_vals) / len(occ_vals)) if occ_vals else 0
    inc_count = sum(1 for a in activities if a.get("type") == "meeting")  # reuniones como proxy

    stats_cards_html = (
        f'<div class="calp-stats-wrap">'
        f'<div class="calp-stat-card">'
        f'<div class="calp-stat-val" style="color:var(--primary)">{month_stats["assigned"]}</div>'
        f'<div class="calp-stat-lbl">Actividades del mes</div>'
        f'</div>'
        f'<div class="calp-stat-card">'
        f'<div class="calp-stat-val" style="color:#f59e0b">{occ_media}%</div>'
        f'<div class="calp-stat-lbl">Ocupación media</div>'
        f'</div>'
        f'<div class="calp-stat-card">'
        f'<div class="calp-stat-val" style="color:#6366f1">{month_stats["vacation_days"]}</div>'
        f'<div class="calp-stat-lbl">Días vacaciones</div>'
        f'</div>'
        f'<div class="calp-stat-card">'
        f'<div class="calp-stat-val" style="color:#f43f5e">{month_stats["sick_days"]}</div>'
        f'<div class="calp-stat-lbl">Días de baja</div>'
        f'</div>'
        f'</div>'
    )

    # ── Botones y modales ─────────────────────────────────────────────
    add_btn_html = ""
    act_modal_html = ""
    act_js_str = ""
    if is_admin:
        add_btn_html = (
            f'<button class="calp-btn-pri" '
            f'onclick="document.getElementById(\'act-modal\').classList.add(\'open\')">'
            f'<svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">'
            f'<path d="M8 2a.5.5 0 01.5.5v5h5a.5.5 0 010 1h-5v5a.5.5 0 01-1 0v-5h-5a.5.5 0 010-1h5v-5A.5.5 0 018 2z"/>'
            f'</svg> Nueva asignación</button>'
        )
        act_modal_html = _activity_modal(str(today))
        act_js_str = _activity_js()

    # Botón "Nuevo evento" disponible para todos los usuarios
    pev_btn_html = (
        f'<button class="calp-btn-ghost" style="border-color:{_PEVENT_COLOR};color:{_PEVENT_COLOR}" '
        f'onclick="document.getElementById(\'pev-modal\').classList.add(\'open\')">'
        f'🗓 Evento personal</button>'
    )
    pev_modal_html = _personal_event_modal(str(today), is_admin)
    pev_js_str = _personal_event_js(is_admin)

    # ── JSON de datos por día (para el panel de detalle en JS) ────────
    day_data_json = json.dumps(day_data, ensure_ascii=False)

    # ── Mobile calendar: mini-grid ────────────────────────────────────
    mob_grid_cells = ""
    mob_start = first - timedelta(days=first.weekday())
    mob_cur = mob_start
    for _ in range(42):
        mob_in_m   = (mob_cur.month == month)
        mob_is_tod = (mob_cur == today)
        if not mob_in_m:
            mob_grid_cells += (
                f'<div class="mob-cal-cell other-month">'
                f'<span class="mob-cal-dn">{mob_cur.day}</span>'
                f'</div>'
            )
        else:
            mob_d_str = str(mob_cur)
            mob_today_cls = " today" if mob_is_tod else ""
            # Collect up to 3 unique tech colors with activity that day
            mob_dots_html = '<div class="mob-cal-dots">'
            mob_dots_shown = 0
            for t in techs:
                if mob_dots_shown >= 3:
                    break
                if act_map.get((t["id"], mob_d_str)):
                    mob_dots_html += (
                        f'<span class="mob-cal-dot" '
                        f'style="background:{tech_color[t["id"]]}"></span>'
                    )
                    mob_dots_shown += 1
            mob_dots_html += '</div>'
            mob_grid_cells += (
                f'<div class="mob-cal-cell{mob_today_cls}" '
                f'data-day="{mob_cur.day}" '
                f'onclick="mobCalSelect(this,{mob_cur.day})">'
                f'<span class="mob-cal-dn">{mob_cur.day}</span>'
                f'{mob_dots_html if mob_dots_shown else ""}'
                f'</div>'
            )
        mob_cur += timedelta(days=1)

    # ── Mobile calendar: initial day panel (today if in month, else day 1) ──
    if today.year == year and today.month == month:
        mob_initial_day = today.day
    else:
        mob_initial_day = 1
    mob_initial_dow = _date(year, month, mob_initial_day).weekday()
    _DOW_ES_LONG = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    mob_initial_title = (
        f'{_DOW_ES_LONG[mob_initial_dow]}, {mob_initial_day} de '
        f'{_MONTH_NAMES_ES[month-1]} {year}'
    )
    mob_initial_data = day_data.get(mob_initial_day, {})
    mob_initial_acts = mob_initial_data.get("acts", [])
    mob_day_panel_html = f'<div class="mob-cal-day-title">{mob_initial_title}</div>'
    if mob_initial_acts:
        for mob_act in mob_initial_acts:
            mob_acolor = _TYPE_DOT_COLOR.get(mob_act.get("type", "other"), "#64748b")
            mob_day_panel_html += (
                f'<div class="mob-cal-event">'
                f'<div class="mob-cal-event-stripe" style="background:{mob_acolor}"></div>'
                f'<div class="mob-cal-event-body">'
                f'<div class="mob-cal-event-name">{_esc(mob_act.get("pname",""))}</div>'
                f'<div class="mob-cal-event-tech">{_esc(mob_act.get("tech_name") or mob_act.get("uname",""))}</div>'
                f'</div></div>'
            )
    else:
        mob_day_panel_html += '<div class="mob-cal-empty">Sin actividades este día</div>'

    # ── Mobile calendar: equipo hoy ──────────────────────────────────
    mob_team_html = ""
    _AVAIL_STATUS_CLASS = {
        "available": "available", "remote": "available",
        "vacation": "vacation", "day_off": "vacation",
        "sick": "sick", "traveling": "traveling",
        "off": "available",
    }
    _AVAIL_LABEL_MOB = {
        "available": "Disponible", "remote": "Remoto",
        "vacation": "Vacaciones", "day_off": "Día libre",
        "sick": "Baja médica", "traveling": "Desplazado",
        "off": "Libre",
    }
    for t in techs:
        col = tech_color[t["id"]]
        init = _tech_initials(t["display_name"])
        avail_status = today_avail.get((t["id"], today_str), "available")
        sc = _AVAIL_STATUS_CLASS.get(avail_status, "available")
        slbl = _AVAIL_LABEL_MOB.get(avail_status, "Disponible")
        mob_team_html += (
            f'<div class="mob-cal-member">'
            f'<div class="mob-cal-avatar" style="background:{col}">{_esc(init)}</div>'
            f'<div class="mob-cal-member-info">'
            f'<div class="mob-cal-member-name">{_esc(t["display_name"])}</div>'
            f'<div class="mob-cal-member-status {sc}">{slbl}</div>'
            f'</div></div>'
        )

    # ── HTML principal ─────────────────────────────────────────────────
    month_title = (f'{_MONTH_NAMES_ES[month-1]} '
                   f'<span style="font-weight:400;color:var(--muted)">{year}</span>')

    content = f"""
{cr_panel}

<!-- ── Vista móvil ── -->
<div class="mob-only mob-cal">
  <div class="mob-cal-header">
    <a href="{BP}/calendar?year={prev_y}&month={prev_m}" class="mob-cal-nav">&#8249;</a>
    <h2 class="mob-cal-title">{_MONTH_NAMES_ES[month-1]} {year}</h2>
    <a href="{BP}/calendar?year={next_y}&month={next_m}" class="mob-cal-nav">&#8250;</a>
  </div>
  <div class="mob-cal-grid">
    <div class="mob-cal-dow">L</div>
    <div class="mob-cal-dow">M</div>
    <div class="mob-cal-dow">X</div>
    <div class="mob-cal-dow">J</div>
    <div class="mob-cal-dow">V</div>
    <div class="mob-cal-dow">S</div>
    <div class="mob-cal-dow">D</div>
    {mob_grid_cells}
  </div>
  <div class="mob-cal-day-panel" id="mob-cal-day">
    {mob_day_panel_html}
  </div>
  <div class="mob-cal-team">
    <div class="mob-cal-section-title">Equipo hoy</div>
    {mob_team_html}
  </div>
</div>

<script>
var MOB_CAL_DATA = {day_data_json};
var MOB_CAL_MONTH = {month};
var MOB_CAL_YEAR  = {year};
var MOB_DOW_LONG  = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'];
var MOB_MONTHS    = {json.dumps(_MONTH_NAMES_ES, ensure_ascii=False)};
var MOB_TYPE_COLOR= {{physical:'#3b82f6',online:'#8b5cf6',meeting:'#dc2626',travel:'#d97706',other:'#64748b'}};

function mobCalSelect(cell, day) {{
  document.querySelectorAll('.mob-cal-cell').forEach(function(c){{c.classList.remove('selected');}});
  cell.classList.add('selected');
  var d = new Date(MOB_CAL_YEAR, MOB_CAL_MONTH - 1, day);
  var dow = d.getDay();  // 0=Sun
  var dowIdx = dow === 0 ? 6 : dow - 1;  // convert to Mon=0
  var dateTitle = MOB_DOW_LONG[dowIdx] + ', ' + day + ' de ' + MOB_MONTHS[MOB_CAL_MONTH - 1] + ' ' + MOB_CAL_YEAR;
  var events = (MOB_CAL_DATA[day] || {{}}).acts || [];
  var panel = document.getElementById('mob-cal-day');
  var html = '<div class="mob-cal-day-title">' + dateTitle + '</div>';
  if (events.length === 0) {{
    html += '<div class="mob-cal-empty">Sin actividades este día</div>';
  }} else {{
    events.forEach(function(ev) {{
      var color = MOB_TYPE_COLOR[ev.type] || '#64748b';
      html += '<div class="mob-cal-event">' +
        '<div class="mob-cal-event-stripe" style="background:' + color + '"></div>' +
        '<div class="mob-cal-event-body">' +
          '<div class="mob-cal-event-name">' + (ev.pname || '') + '</div>' +
          '<div class="mob-cal-event-tech">' + (ev.tech_name || ev.uname || '') + '</div>' +
        '</div></div>';
    }});
  }}
  panel.innerHTML = html;
}}

// Mark initial selected cell
(function() {{
  var initial = {mob_initial_day};
  document.querySelectorAll('.mob-cal-cell[data-day]').forEach(function(c) {{
    if (parseInt(c.dataset.day) === initial) c.classList.add('selected');
  }});
}})();
</script>

<!-- ── Vista desktop ── -->
<div class="desk-only">

<div id="calp-tooltip" class="calp-tooltip">
  <div class="calp-tooltip-name" id="calp-tt-name"></div>
  <div class="calp-tooltip-row">
    <span id="calp-tt-status" class="calp-tooltip-status"></span>
    <span id="calp-tt-acts" style="font-size:.65rem"></span>
  </div>
</div>

<div class="calp-shell">

  <!-- Topbar -->
  <div class="calp-topbar">
    <div style="display:flex;align-items:center;gap:8px">
      <a href="{BP}/calendar?year={prev_y}&month={prev_m}" class="calp-nav-btn" title="Mes anterior">‹</a>
      <a href="{BP}/calendar?year={next_y}&month={next_m}" class="calp-nav-btn" title="Mes siguiente">›</a>
      <h1 class="calp-month-title">{month_title}</h1>
    </div>
    <div style="flex:1"></div>
    <div style="display:flex;align-items:center;gap:6px">
      <a href="{BP}/calendar?view=week&week_start={today_monday}" class="calp-btn-ghost">Semana</a>
      <span class="calp-btn-ghost active">Mes</span>
      <a href="{BP}/calendar?year={today.year}&month={today.month}" class="calp-btn-ghost">Hoy</a>
      {pev_btn_html}
      {add_btn_html}
    </div>
  </div>

  <!-- Legend strip -->
  <div class="calp-legend-strip">
    <div class="calp-legend-group">
      <span class="calp-legend-label">Estado técnico</span>
      <div class="calp-legend-item"><div class="calp-legend-dot" style="background:#22c55e"></div>Disponible</div>
      <div class="calp-legend-item"><div class="calp-legend-dot" style="background:#4b5563"></div>Libre</div>
      <div class="calp-legend-item"><div class="calp-legend-dot" style="background:#6366f1"></div>Vacaciones</div>
      <div class="calp-legend-item"><div class="calp-legend-dot" style="background:#f43f5e"></div>Baja</div>
      <div class="calp-legend-item"><div class="calp-legend-dot" style="background:#f97316"></div>Desplazado</div>
    </div>
    <div class="calp-legend-sep"></div>
    <div class="calp-legend-group">
      <span class="calp-legend-label">Carga</span>
      <div class="calp-legend-heat">
        Carga:
        <div class="calp-heat-swatch" style="background:rgba(59,130,246,.06)"></div>
        <div class="calp-heat-swatch" style="background:rgba(59,130,246,.13)"></div>
        <div class="calp-heat-swatch" style="background:rgba(59,130,246,.22)"></div>
        <div class="calp-heat-swatch" style="background:rgba(245,158,11,.28)"></div>
        <div class="calp-heat-swatch" style="background:rgba(244,63,94,.28)"></div>
        <span style="margin-left:2px">baja → alta</span>
      </div>
    </div>
  </div>

  <!-- DOW row -->
  <div class="calp-dow-row">
    {dow_headers_html}
  </div>

  <!-- Main canvas: grid + sidebar -->
  <div class="calp-body">

    <!-- Grid -->
    <div class="calp-grid-wrap">
      <div class="calp-grid" id="calpGrid">
        {cells_html}
      </div>
    </div>

    <!-- Sidebar -->
    <aside class="calp-sidebar">

      <!-- Mini calendar -->
      <div class="calp-mini-cal">
        <div class="calp-mini-cal-header">
          <span class="calp-mini-cal-title">{_MONTH_NAMES_ES[month-1]} {year}</span>
          <div class="calp-mini-nav">
            <a href="{BP}/calendar?year={prev_y}&month={prev_m}" class="calp-mini-nav-btn">‹</a>
            <a href="{BP}/calendar?year={next_y}&month={next_m}" class="calp-mini-nav-btn">›</a>
          </div>
        </div>
        <div class="calp-mini-dow-row">
          <div class="calp-mini-dow">L</div><div class="calp-mini-dow">M</div>
          <div class="calp-mini-dow">X</div><div class="calp-mini-dow">J</div>
          <div class="calp-mini-dow">V</div><div class="calp-mini-dow">S</div>
          <div class="calp-mini-dow">D</div>
        </div>
        <div class="calp-mini-grid" id="calpMiniGrid">
          {mini_grid_html}
        </div>
      </div>

      <!-- Equipo hoy -->
      <div class="calp-team-panel">
        <div class="calp-panel-title">Equipo hoy</div>
        {team_today_html}
      </div>

      <!-- 4 tarjetas de estadísticas -->
      {stats_cards_html}

      <!-- No-selection placeholder -->
      <div class="calp-no-selection" id="calpNoSelection">
        <div class="calp-no-selection-icon">📅</div>
        <div>Haz clic en un día para ver el detalle del equipo</div>
      </div>

      <!-- Detail panel -->
      <div class="calp-detail-panel" id="calpDetailPanel">
        <div class="calp-detail-header">
          <div class="calp-detail-date" id="calpDetailDate"></div>
          <button class="calp-detail-close" id="calpDetailClose">✕</button>
        </div>
        <div class="calp-detail-techs" id="calpDetailTechs"></div>
        <div class="calp-detail-acts" id="calpDetailActs"></div>
      </div>

    </aside>
  </div>

</div>

</div><!-- /desk-only -->

{act_modal_html}
{pev_modal_html}

<script>
var bp = {json.dumps(BP)};
var calpYear  = {year};
var calpMonth = {month};
var CALP_DAY_DATA = {day_data_json};

var CALP_DOW    = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'];
var CALP_MONTHS = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                   'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
var CALP_AVAIL_LABEL = {{
  available:'Disponible', remote:'Remoto', off:'Sin asignar',
  day_off:'Día libre', sick:'Baja médica', vacation:'Vacaciones', traveling:'Desplazado'
}};
var CALP_TYPE_ICON  = {{physical:'🔧', online:'🌐', meeting:'👥', travel:'✈️', other:'📌'}};
var CALP_TYPE_COLOR = {{
  physical:'#3b82f6', online:'#8b5cf6', meeting:'#dc2626',
  travel:'#d97706', other:'#64748b'
}};
</script>
<script>
{act_js_str}
{pev_js_str}
{_avail_cr_js()}

(function() {{
  var grid = document.getElementById('calpGrid');
  var tooltip = document.getElementById('calp-tooltip');
  var ttName  = document.getElementById('calp-tt-name');
  var ttStatus = document.getElementById('calp-tt-status');
  var ttActs  = document.getElementById('calp-tt-acts');
  if (!grid) return;

  /* ── Avatar tooltip ─────────────────────────────────────────────── */
  document.addEventListener('mouseover', function(e) {{
    var av = e.target.closest('.calp-avatar[data-tech-name]');
    if (!av) {{ tooltip.style.display = 'none'; return; }}
    ttName.textContent  = av.dataset.techName || '';
    ttStatus.textContent = av.dataset.techAvail || '';
    ttStatus.className  = 'calp-tooltip-status ' + (av.dataset.avail || '');
    var acts = parseInt(av.dataset.techActs || '0');
    ttActs.textContent  = acts ? acts + ' actividad' + (acts > 1 ? 'es' : '') : 'Sin actividades';
    tooltip.style.display = 'block';
  }});
  document.addEventListener('mousemove', function(e) {{
    var av = e.target.closest('.calp-avatar[data-tech-name]');
    if (!av) {{ tooltip.style.display = 'none'; return; }}
    tooltip.style.left = (e.clientX + 14) + 'px';
    tooltip.style.top  = (e.clientY - 10) + 'px';
  }});
  document.addEventListener('mouseout', function(e) {{
    if (!e.target.closest('.calp-avatar[data-tech-name]')) tooltip.style.display = 'none';
  }});

  /* ── Detail panel ───────────────────────────────────────────────── */
  function closeDetail() {{
    document.getElementById('calpDetailPanel').classList.remove('visible');
    document.getElementById('calpNoSelection').style.display = '';
    grid.querySelectorAll('.calp-day-cell.selected').forEach(function(c) {{
      c.classList.remove('selected');
    }});
    document.querySelectorAll('.calp-mini-day.selected-mini').forEach(function(m) {{
      m.classList.remove('selected-mini');
    }});
  }}

  function showDetail(dayNum, dowIdx) {{
    var data = CALP_DAY_DATA[dayNum];
    if (!data) return;

    document.getElementById('calpDetailDate').textContent =
      CALP_DOW[dowIdx] + ', ' + dayNum + ' de ' + CALP_MONTHS[calpMonth - 1] + ' ' + calpYear;

    /* Técnicos */
    var techsEl = document.getElementById('calpDetailTechs');
    techsEl.innerHTML = '';
    (data.techs || []).forEach(function(t) {{
      var statusTxt = CALP_AVAIL_LABEL[t.avail] || t.avail;
      var card = document.createElement('div');
      card.className = 'calp-detail-tech-card';
      card.innerHTML =
        '<div class="calp-detail-tech-avatar" style="background:' + t.color + '">' + (t.initials || '?') + '</div>' +
        '<div class="calp-detail-tech-info">' +
          '<div class="calp-detail-tech-name">' + (t.name || '') + '</div>' +
          '<div class="calp-detail-tech-status ' + (t.avail || '') + '">' + statusTxt + '</div>' +
        '</div>';
      techsEl.appendChild(card);
    }});

    /* Actividades */
    var actsEl = document.getElementById('calpDetailActs');
    actsEl.innerHTML = '';
    var acts = data.acts || [];
    var titleEl = document.createElement('div');
    titleEl.className = 'calp-detail-acts-title';
    titleEl.textContent = 'Actividades' + (acts.length ? ' (' + acts.length + ')' : '');
    actsEl.appendChild(titleEl);

    if (acts.length === 0) {{
      var empty = document.createElement('div');
      empty.className = 'calp-detail-empty';
      empty.textContent = 'Sin actividades programadas';
      actsEl.appendChild(empty);
    }} else {{
      acts.forEach(function(a) {{
        var dotColor = CALP_TYPE_COLOR[a.type] || '#64748b';
        var icon = CALP_TYPE_ICON[a.type] || '📌';
        var timeStr = '';
        if (!a.all_day && a.hour_start !== null && a.hour_start !== undefined) {{
          timeStr = String(a.hour_start).padStart(2,'0') + ':00';
          if (a.hour_end) timeStr += '–' + String(a.hour_end).padStart(2,'0') + ':00';
        }}
        var actDiv = document.createElement('div');
        actDiv.className = 'calp-detail-act';
        actDiv.innerHTML =
          '<div class="calp-detail-act-dot" style="background:' + dotColor + '"></div>' +
          '<div class="calp-detail-act-info">' +
            '<div class="calp-detail-act-name">' + icon + ' ' + (a.pname || '') + '</div>' +
            '<div class="calp-detail-act-tech">' +
              (a.tech_name || a.uname || '') +
              (timeStr ? ' · ' + timeStr : '') +
            '</div>' +
          '</div>';
        actsEl.appendChild(actDiv);
      }});
    }}

    /* Eventos personales */
    var pevents = data.pevents || [];
    if (pevents.length > 0) {{
      var pevTitle = document.createElement('div');
      pevTitle.className = 'calp-detail-acts-title';
      pevTitle.style.marginTop = '10px';
      pevTitle.textContent = 'Eventos personales (' + pevents.length + ')';
      actsEl.appendChild(pevTitle);
      var PICON = {{training:'🎓',vendor:'🤝',presentation:'📢',personal:'👤',other:'📌'}};
      pevents.forEach(function(ev) {{
        var icon = PICON[ev.event_type] || '📌';
        var pevDiv = document.createElement('div');
        pevDiv.className = 'calp-detail-act';
        pevDiv.style.borderLeft = '2px solid #d97706';
        pevDiv.innerHTML =
          '<div class="calp-detail-act-dot" style="background:#d97706"></div>' +
          '<div class="calp-detail-act-info">' +
            '<div class="calp-detail-act-name">' + icon + ' ' + (ev.title || '') + '</div>' +
            '<div class="calp-detail-act-tech">' + (ev.uname || '') + '</div>' +
          '</div>';
        actsEl.appendChild(pevDiv);
      }});
    }}

    document.getElementById('calpNoSelection').style.display = 'none';
    document.getElementById('calpDetailPanel').classList.add('visible');
  }}

  /* Clic en celda */
  grid.addEventListener('click', function(e) {{
    if (e.target.closest('.calp-avatar')) return;
    var cell = e.target.closest('.calp-day-cell:not(.other-month):not(.weekend)');
    if (!cell) return;
    var dayNum = parseInt(cell.dataset.day || '0');
    var dowIdx = parseInt(cell.dataset.dow || '0');
    if (!dayNum) return;

    if (cell.classList.contains('selected')) {{
      cell.classList.remove('selected');
      closeDetail();
      return;
    }}
    grid.querySelectorAll('.calp-day-cell.selected').forEach(function(c) {{
      c.classList.remove('selected');
    }});
    cell.classList.add('selected');
    showDetail(dayNum, dowIdx);

    /* Resaltar mini-cal */
    document.querySelectorAll('.calp-mini-day').forEach(function(m) {{
      m.classList.remove('selected-mini');
    }});
    document.querySelectorAll('.calp-mini-day:not(.other)').forEach(function(m) {{
      if (parseInt(m.textContent) === dayNum) m.classList.add('selected-mini');
    }});
  }});

  /* Cerrar panel */
  var closeBtn = document.getElementById('calpDetailClose');
  if (closeBtn) closeBtn.addEventListener('click', closeDetail);

  /* Animación escalonada */
  grid.querySelectorAll('.calp-day-cell').forEach(function(cell, i) {{
    cell.style.animationDelay = Math.min(i * 6, 100) + 'ms';
  }});
}})();
</script>"""

    return _shell("calendar", user, content, title="Calendario")


# ── Week view ──────────────────────────────────────────────────────────────────

def _calendar_week(user, week_start_str):
    today = _date.today()
    try:
        ws = _date.fromisoformat(week_start_str) if week_start_str else today - timedelta(days=today.weekday())
    except ValueError:
        ws = today - timedelta(days=today.weekday())
    ws = ws - timedelta(days=ws.weekday())
    we = ws + timedelta(days=6)
    prev_ws = str(ws - timedelta(days=7))
    next_ws = str(ws + timedelta(days=7))
    this_ws = str(today - timedelta(days=today.weekday()))
    days    = [ws + timedelta(days=i) for i in range(7)]
    day_strs= [str(d) for d in days]
    week_label = f"{_MONTH_NAMES[ws.month-1]} {ws.day} – {_MONTH_NAMES[we.month-1]} {we.day}, {we.year}"

    techs   = _load_techs()
    avail   = _avail_map(day_strs)
    is_admin= user.get("role") == "admin"

    acts = rs(q("""SELECT a.*,u.display_name uname,p.name pname
        FROM activities a JOIN users u ON u.id=a.user_id JOIN projects p ON p.id=a.project_id
        WHERE a.activity_date BETWEEN ? AND ?
        ORDER BY a.activity_date,a.hour_start""", (str(ws), str(we))))

    act_map = {}
    for a in acts:
        act_map.setdefault((a["user_id"], a["activity_date"]), []).append(a)

    week_pevents = rs(q("""SELECT pe.*,u.display_name uname
        FROM personal_events pe JOIN users u ON u.id=pe.user_id
        WHERE pe.event_date<=? AND (pe.date_end='' OR pe.date_end IS NULL OR pe.date_end>=?)
        ORDER BY pe.event_date""", (str(we), str(ws))))
    # pev_week_map: {date_str: [event, ...]} + pev_user_days_w for availability override
    pev_week_map: dict = {}
    pev_user_days_w: set = set()
    for ev in week_pevents:
        try:
            start_d = _date.fromisoformat(ev["event_date"])
            end_d   = _date.fromisoformat(ev["date_end"]) if ev.get("date_end") else start_d
        except ValueError:
            continue
        cur_d = start_d
        while cur_d <= end_d:
            d_s = str(cur_d)
            if str(ws) <= d_s <= str(we):
                pev_week_map.setdefault(d_s, []).append(ev)
                pev_user_days_w.add((ev["user_id"], d_s))
            cur_d += timedelta(days=1)

    # Build column count: 1 (tech name) + 7 days
    col_tmpl = "110px " + " ".join(["1fr"] * 7)

    # Day headers row
    def _wsl_day_th(d):
        is_tc   = (d == today)
        is_wknd = (d.weekday() >= 5)
        num_style = "color:var(--muted)"
        if is_wknd: num_style += ";color:var(--warn,#f59e0b)"
        num_html = (f'<div class="wsl-today-num">{d.day}</div>' if is_tc
                    else f'<div class="wsl-date" style="{num_style}">{d.day}</div>')
        return (f'<div class="wsl-head">'
                f'<div class="wsl-dow">{_DOW_SHORT[d.weekday()]}</div>'
                f'{num_html}</div>')

    day_headers = (f'<div class="wsl-head" style="min-width:110px;text-align:left;padding-left:8px">'
                   f'<a href="{BP}/calendar?year={ws.year}&month={ws.month}" '
                   f'style="font-size:10px;color:var(--muted)">← Mes</a></div>'
                   + "".join(_wsl_day_th(d) for d in days))

    # Tech rows
    rows_html = ""
    visible_techs = [t for t in techs
                     if user.get("role") in ("admin","backoffice") or t["id"] == user.get("id")]

    for t in visible_techs:
        initials = "".join(w[0].upper() for w in t["display_name"].split()[:2])
        tc = _pcolor(t["id"])
        # Tech name cell
        row = (f'<div class="wsl-tech">'
               f'<div class="avatar avatar-sm" style="background:{tc}">{_esc(initials)}</div>'
               f'<div class="wsl-tname">{_esc(t["display_name"])}</div>'
               f'</div>')
        # Day cells
        for d_str in day_strs:
            status = avail.get((t["id"], d_str), "available")
            if (t["id"], d_str) in pev_user_days_w and status in ("available", "remote", ""):
                status = "day_off"
            bg_cls = {"vacation":"vac-bg","day_off":"vac-bg","off":"off-bg",
                      "sick":"off-bg","traveling":"trav-bg"}.get(status, "")
            cell_inner = ""
            for a in act_map.get((t["id"], d_str), []):
                col  = _pcolor(a["project_id"])
                icon = _TYPE_ICON.get(a["type"], "📌")
                hs   = a.get("hour_start") or 0
                he   = a.get("hour_end") or 0
                time_lbl = f"{hs:02d}–{he:02d}" if not a["all_day"] and hs else ""
                cell_inner += (f'<span class="wsl-event" style="background:{col}" '
                               f'title="{_esc(a["pname"])} · {_esc(a["uname"])} · {time_lbl}">'
                               f'{icon} {_esc(a["pname"][:14])}'
                               f'{(" "+time_lbl) if time_lbl else ""}</span>')
            avp = _avail_picker_html(t["id"], d_str, status, is_admin, compact=True)
            # Personal events for this tech + day (only own, or all if admin)
            for pev in pev_week_map.get(d_str, []):
                if pev["user_id"] == t["id"]:
                    icon = _PEVENT_ICON.get(pev.get("event_type","other"), "📌")
                    short = pev["title"][:14] if pev.get("title") else ""
                    pev_tip = _esc(pev["title"]) + " · " + _esc(pev["uname"])
                    cell_inner += (
                        f'<span class="wsl-event" style="background:{_PEVENT_COLOR}" '
                        f'title="{pev_tip}">'
                        f'{icon} {_esc(short)}</span>'
                    )
            cell_inner += f'<div style="text-align:right;margin-top:2px">{avp}</div>'
            row += f'<div class="wsl-cell {bg_cls}">{cell_inner}</div>'
        rows_html += row

    this_week_link = (f'<a href="{BP}/calendar?view=week&week_start={this_ws}" class="btn btn-ghost btn-sm">Esta semana</a>'
                      ) if str(ws) != this_ws else ""
    add_btn  = (f'<button class="btn btn-primary" onclick="document.getElementById(\'act-modal\').classList.add(\'open\')">'
                f'+ Actividad</button>') if is_admin else ""
    pev_btn_week = (
        f'<button class="btn btn-ghost btn-sm" style="border-color:{_PEVENT_COLOR};color:{_PEVENT_COLOR}" '
        f'onclick="document.getElementById(\'pev-modal\').classList.add(\'open\')">🗓 Evento personal</button>'
    )
    act_modal = _activity_modal(str(today)) if is_admin else ""
    act_js    = _activity_js() if is_admin else ""
    pev_modal_week = _personal_event_modal(str(today), is_admin)
    pev_js_week    = _personal_event_js(is_admin)
    cr_panel  = _pending_cr_panel(user)
    right     = _right_panel(user, ws.year, ws.month, today, is_admin)

    content = f"""
{cr_panel}
<div class="cal-layout">
  <div class="cal-main-area">
    <div class="toolbar" style="margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
        <a href="{BP}/calendar?year={ws.year}&month={ws.month}" class="btn btn-ghost btn-sm">Vista mes</a>
        <a href="{BP}/calendar?view=week&week_start={prev_ws}" class="btn btn-ghost btn-sm">‹</a>
        <span style="font-weight:600;font-size:.88rem;white-space:nowrap">{week_label}</span>
        <a href="{BP}/calendar?view=week&week_start={next_ws}" class="btn btn-ghost btn-sm">›</a>
        {this_week_link}
      </div>
      <div style="display:flex;gap:6px">{pev_btn_week} {add_btn}</div>
    </div>
    <div class="week-sl" style="grid-template-columns:{col_tmpl}">
      {day_headers}
      {rows_html}
    </div>
  </div>
  {right}
</div>
{act_modal}
{pev_modal_week}
<script>
var bp={json.dumps(BP)};
{act_js}
{pev_js_week}
{_avail_cr_js()}
</script>"""
    return _shell("calendar", user, content, title="Calendario — Semana")


# ── Day view ───────────────────────────────────────────────────────────────────

def _action_btn(act, user, day_str):
    is_admin = user.get("role") == "admin"
    if is_admin:
        return (f'<button class="btn btn-danger btn-icon" style="font-size:.7rem;margin-left:4px" '
                f'onclick="delActivity({act["id"]})" title="Eliminar">✕</button>')
    if act["user_id"] == user.get("id"):
        return (f'<button class="btn btn-ghost btn-sm" style="font-size:.65rem;padding:2px 6px;margin-left:4px" '
                f'onclick="openCR({act["id"]})" title="Solicitar cambio">↩ Cambio</button>')
    return ""


def _calendar_day(user, day_str):
    try:
        day = _date.fromisoformat(day_str)
    except ValueError:
        return None

    today    = _date.today()
    prev_day = str(day - timedelta(days=1))
    next_day = str(day + timedelta(days=1))
    day_label = f"{_DOW_FULL[day.weekday()]} {day.day} de {_MONTH_NAMES[day.month-1]} {day.year}"
    is_admin  = user.get("role") == "admin"

    techs = _load_techs()
    projs = _load_projs()

    activities = rs(q("""SELECT a.*,u.display_name uname,p.name pname
        FROM activities a JOIN users u ON u.id=a.user_id JOIN projects p ON p.id=a.project_id
        WHERE a.activity_date=?
        ORDER BY a.hour_start,u.display_name""", (day_str,)))

    avail = _avail_map([day_str])

    day_pevents = rs(q("""SELECT pe.*,u.display_name uname
        FROM personal_events pe JOIN users u ON u.id=pe.user_id
        WHERE pe.event_date<=? AND (pe.date_end='' OR pe.date_end IS NULL OR pe.date_end>=?)
        ORDER BY pe.event_date,pe.hour_start""", (day_str, day_str)))
    pev_users_day: set = {ev["user_id"] for ev in day_pevents}

    act_ids = [a["id"] for a in activities]
    cr_pending = set()
    if act_ids:
        ph = ",".join("?" * len(act_ids))
        cr_pending = {r["activity_id"] for r in
                      rs(q(f"SELECT activity_id FROM change_requests WHERE activity_id IN ({ph}) AND status='pending'",
                           tuple(act_ids)))}

    proj_opts_day = _proj_options()
    type_opts_day = _type_options()
    hs_opts       = _hour_select_start()
    he_opts       = _hour_select_end()
    user_opts_day = _user_options()

    slot_map = {}
    for a in activities:
        if a["all_day"] or a["hour_start"] is None or a["hour_end"] is None:
            continue
        for h in range(a["hour_start"], a["hour_end"]):
            key = (a["user_id"], h)
            if key not in slot_map:
                slot_map[key] = a

    allday_map = {}
    for a in activities:
        if a["all_day"]:
            allday_map.setdefault(a["user_id"], []).append(a)

    now_hour = datetime.now().hour if day == today else -1

    visible_techs = [t for t in techs
                     if user.get("role") in ("admin","backoffice") or t["id"] == user.get("id")]

    th_techs = ""
    for t in visible_techs:
        status = avail.get((t["id"], day_str), "available")
        if t["id"] in pev_users_day and status in ("available", "remote", ""):
            status = "day_off"
        bg_sty = ""
        if status == "off":
            bg_sty = "background:var(--border)"
        elif status == "traveling":
            bg_sty = "background:color-mix(in srgb,orange 20%,transparent)"
        elif status == "day_off":
            bg_sty = "background:rgba(124,58,237,.12)"
        initials = "".join(w[0].upper() for w in t["display_name"].split()[:2])
        col = _pcolor(t["id"])
        avp = _avail_picker_html(t["id"], day_str, status, is_admin, compact=False)
        th_techs += (f'<th style="{bg_sty};min-width:90px">'
                     f'<div class="avatar avatar-sm" style="background:{col};margin:0 auto 3px">'
                     f'{_esc(initials)}</div>'
                     f'<div style="font-size:.65rem;margin-bottom:4px">{_esc(t["display_name"].split()[0])}</div>'
                     f'{avp}'
                     f'</th>')

    allday_cells = ""
    has_allday = bool(allday_map)
    for t in visible_techs:
        ads = allday_map.get(t["id"], [])
        cell_inner = ""
        for a in ads:
            col = _pcolor(a["project_id"])
            icon = _TYPE_ICON.get(a["type"], "📌")
            warn = " ⚠️" if a["id"] in cr_pending else ""
            del_or_req = _action_btn(a, user, day_str)
            cell_inner += (f'<div style="background:{col};color:#fff;border-radius:4px;'
                           f'padding:4px 6px;font-size:.72rem;margin-bottom:3px">'
                           f'{icon}{warn} {_esc(a["pname"])}{del_or_req}</div>')
        allday_cells += f'<td style="padding:4px;vertical-align:top">{cell_inner}</td>'

    rows_html = ""
    if has_allday:
        rows_html += f'<tr><td class="hour-label" style="font-size:.65rem">Todo el día</td>{allday_cells}</tr>'

    for h in range(6, 21):
        now_cls = ' class="now-row"' if h == now_hour else ""
        cells = ""
        for t in visible_techs:
            a = slot_map.get((t["id"], h))
            if a:
                col = _pcolor(a["project_id"])
                icon = _TYPE_ICON.get(a["type"], "📌")
                warn = " ⚠️" if a["id"] in cr_pending else ""
                if a["hour_start"] == h:
                    end_str = f'{a["hour_end"]:02d}:00'
                    del_or_req = _action_btn(a, user, day_str)
                    cells += (f'<td{now_cls}><div class="slot-block" style="background:{col}">'
                              f'{icon}{warn} {_esc(a["pname"][:16])}'
                              f'<span style="opacity:.8;font-size:.6rem;display:block">→ {end_str}</span>'
                              f'{del_or_req}</div></td>')
                else:
                    cells += (f'<td{now_cls}><div class="slot-block" style="background:{col};'
                              f'opacity:.35;pointer-events:none">·</div></td>')
            else:
                cells += f'<td{now_cls}></td>'
        hstr = f'{"0" if h<10 else ""}{h}:00'
        rows_html += f'<tr><td class="hour-label">{hstr}</td>{cells}</tr>'

    slot_list = ""
    for a in activities:
        col = _pcolor(a["project_id"])
        initials = "".join(w[0].upper() for w in a["uname"].split()[:2])
        icon = _TYPE_ICON.get(a["type"], "📌")
        time_str = ("Todo el día" if a["all_day"]
                    else f'{a["hour_start"]:02d}:00 → {a["hour_end"]:02d}:00')
        del_or_req = _action_btn(a, user, day_str)
        cr_badge = ('<span style="color:orange;font-size:.7rem"> ⚠️ solicitud pendiente</span>'
                    if a["id"] in cr_pending else "")
        slot_list += (
            f'<div style="display:flex;align-items:flex-start;gap:8px;padding:8px 0;'
            f'border-bottom:1px solid var(--border)">'
            f'<div class="avatar" style="background:{col}">{_esc(initials)}</div>'
            f'<div style="flex:1;min-width:0">'
            f'<div class="fw7" style="font-size:.85rem">{_esc(a["uname"])}</div>'
            f'<div style="font-size:.75rem;color:var(--muted)">'
            f'{icon} {time_str} · {_esc(a["pname"])}</div>'
            f'{("<div style=font-size:.72rem;color:var(--muted)>"+_esc(a["notes"])+"</div>") if a.get("notes") else ""}'
            f'{cr_badge}</div>'
            f'{del_or_req}</div>')
    if not slot_list:
        slot_list = '<p class="muted" style="padding:12px 0;font-size:.85rem;text-align:center">Sin actividades planificadas</p>'

    add_btn_day = (f'<button class="btn btn-primary btn-sm" '
                   f'onclick="document.getElementById(\'slot-modal\').classList.add(\'open\')">'
                   f'+ Actividad</button>') if is_admin else ""
    pev_btn_day = (
        f'<button class="btn btn-ghost btn-sm" style="border-color:{_PEVENT_COLOR};color:{_PEVENT_COLOR}" '
        f'onclick="document.getElementById(\'pev-modal\').classList.add(\'open\')">🗓 Evento personal</button>'
    )
    add_sidebar = (f'<div style="margin-top:12px">'
                   f'<button class="btn btn-primary btn-sm" style="width:100%" '
                   f'onclick="document.getElementById(\'slot-modal\').classList.add(\'open\')">'
                   f'+ Añadir actividad</button></div>') if is_admin else ""

    # Personal events block for day summary sidebar
    pev_slot_list = ""
    for ev in day_pevents:
        icon = _PEVENT_ICON.get(ev.get("event_type","other"), "📌")
        etype_lbl = _PEVENT_LABEL.get(ev.get("event_type","other"), "Otro")
        if ev.get("all_day") or not ev.get("hour_start"):
            time_str = "Todo el día"
        else:
            time_str = f'{ev["hour_start"]:02d}:00 → {ev["hour_end"]:02d}:00'
        can_del = (ev["user_id"] == user.get("id") or is_admin)
        ev_id = ev["id"]
        del_btn = (f'<button class="btn btn-danger btn-icon" style="font-size:.7rem;margin-left:4px" '
                   f'onclick="delPersonalEvent({ev_id})" title="Eliminar">✕</button>') if can_del else ""
        ev_title = _esc(ev["title"])
        ev_uname = _esc(ev["uname"])
        ev_notes = _esc(ev.get("notes",""))
        notes_div = f'<div style="font-size:.72rem;color:var(--muted)">{ev_notes}</div>' if ev.get("notes") else ""
        pev_slot_list += (
            f'<div style="display:flex;align-items:flex-start;gap:8px;padding:8px 0;'
            f'border-bottom:1px solid var(--border);border-left:3px solid {_PEVENT_COLOR};padding-left:8px">'
            f'<div style="flex:1;min-width:0">'
            f'<div class="fw7" style="font-size:.85rem">{icon} {ev_title}</div>'
            f'<div style="font-size:.75rem;color:var(--muted)">'
            f'{_esc(etype_lbl)} · {time_str} · {ev_uname}</div>'
            f'{notes_div}'
            f'</div>{del_btn}</div>'
        )
    pev_modal_day = _personal_event_modal(day_str, is_admin)
    pev_js_day    = _personal_event_js(is_admin)

    slot_modal_html = ""
    if is_admin:
        slot_modal_html = f"""
<div class="modal-bg" id="slot-modal">
<div class="modal" style="max-width:500px">
  <h2>Nueva actividad</h2>
  <div class="form-row">
    <div><label>Técnico</label><select id="sl-user">{user_opts_day}</select></div>
    <div><label>Proyecto</label><select id="sl-proj">{proj_opts_day}</select></div>
  </div>
  <div class="form-row">
    <div><label>Tipo</label><select id="sl-type">{type_opts_day}</select></div>
  </div>
  <div class="form-row">
    <div><label>Hora inicio</label><select id="sl-hs">{hs_opts}</select></div>
    <div><label>Hora fin</label><select id="sl-he">{he_opts}</select></div>
  </div>
  <div class="form-row single">
    <div><label><input type="checkbox" id="sl-allday" onchange="toggleSlotAllDay()"> Todo el día</label></div>
  </div>
  <div class="form-row single"><div><label>Notas</label><input id="sl-notes" placeholder="Opcional"></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost"
      onclick="document.getElementById('slot-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doAddSlot()">Guardar</button>
  </div>
</div></div>"""

    cr_modal_html = ""
    if not is_admin:
        cr_modal_html = """
<div class="modal-bg" id="cr-modal">
<div class="modal" style="max-width:420px">
  <h2>Solicitar cambio</h2>
  <input type="hidden" id="cr-act-id">
  <div class="form-row single">
    <div><label>Tipo</label>
    <select id="cr-type">
      <option value="cancel">Cancelar actividad</option>
      <option value="reschedule">Reagendar</option>
      <option value="modify">Modificar</option>
    </select></div>
  </div>
  <div class="form-row single">
    <div><label>Mensaje para el admin</label>
    <textarea id="cr-msg" rows="3" style="width:100%;resize:vertical"
      placeholder="Explica el motivo..."></textarea></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost"
      onclick="document.getElementById('cr-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doSendCR()">Enviar solicitud</button>
  </div>
</div></div>"""

    cr_panel  = _pending_cr_panel(user)
    right     = _right_panel(user, day.year, day.month, today, is_admin)
    log_modal_day = f"""
<div class="modal-bg" id="log-modal-day">
<div class="modal" style="max-width:460px">
  <h2>Registrar horas</h2>
  <div class="form-row">
    <div><label>Técnico</label><select id="ld-user">{user_opts_day}</select></div>
    <div><label>Proyecto</label><select id="ld-proj">{proj_opts_day}</select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha</label><input type="date" id="ld-date" value="{day_str}"></div>
    <div><label>Horas</label><input type="number" id="ld-hours" min="0.25" max="24" step="0.25" value="1"></div>
  </div>
  <div class="form-row single"><div><label>Descripción</label>
    <input id="ld-desc" placeholder="Qué se hizo..."></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost"
      onclick="document.getElementById('log-modal-day').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doDayLog()">Guardar</button>
  </div>
</div></div>"""
    add_log_btn_day = (f'<button class="btn btn-ghost btn-sm" '
                       f'onclick="document.getElementById(\'log-modal-day\').classList.add(\'open\')">'
                       f'🕐 Registrar horas</button>')

    content = f"""
{cr_panel}
<div class="cal-layout">
  <div class="cal-main-area" style="overflow-y:auto">
    <div class="day-nav">
      <a href="{BP}/calendar/{prev_day}" class="btn btn-ghost btn-sm">← {prev_day}</a>
      <div style="flex:1;text-align:center">
        <h1 style="margin:0">{day_label}</h1>
        <a href="{BP}/calendar?year={day.year}&month={day.month}" class="muted" style="font-size:.8rem">← Volver al mes</a>
      </div>
      <a href="{BP}/calendar/{next_day}" class="btn btn-ghost btn-sm">{next_day} →</a>
    </div>

    <div style="display:grid;grid-template-columns:1fr 280px;gap:18px;align-items:start">

    <div class="card" style="padding:0;overflow:hidden">
      <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <h2 style="margin:0">Horario</h2>
        <div style="display:flex;gap:8px">{pev_btn_day} {add_btn_day} {add_log_btn_day}</div>
      </div>
      <div style="overflow-x:auto">
      <table class="day-matrix">
        <thead><tr><th class="hour-col">Hora</th>{th_techs}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
      </div>
    </div>

    <div>
      <div class="card">
        <h2>Resumen del día</h2>
        {slot_list}
        {add_sidebar}
        {(f'<div style="margin-top:14px;border-top:1px solid var(--border);padding-top:10px"><div style="font-weight:700;font-size:.8rem;color:{_PEVENT_COLOR};margin-bottom:6px">Eventos personales</div>{pev_slot_list}</div>') if pev_slot_list else ""}
      </div>
    </div>

    </div>
  </div>
  {right}
</div>

{slot_modal_html}
{cr_modal_html}
{log_modal_day}
{pev_modal_day}

<script>
var bp={json.dumps(BP)};
var slotDate="{day_str}";
{"document.getElementById('slot-modal').onclick=function(e){if(e.target===this)this.classList.remove('open');};" if is_admin else ""}
{"document.getElementById('cr-modal').onclick=function(e){if(e.target===this)this.classList.remove('open');};" if not is_admin else ""}
function toggleSlotAllDay(){{
  var ad=document.getElementById('sl-allday');
  if(!ad) return;
  document.getElementById('sl-hs').disabled=ad.checked;
  document.getElementById('sl-he').disabled=ad.checked;
}}
function doAddSlot(){{
  var allday=document.getElementById('sl-allday')?document.getElementById('sl-allday').checked:false;
  var hs=parseInt(document.getElementById('sl-hs').value);
  var he=parseInt(document.getElementById('sl-he').value);
  if(!allday&&he<=hs){{Toast.show('La hora fin debe ser posterior a la hora inicio','err');return;}}
  var d={{
    user_id:document.getElementById('sl-user').value,
    project_id:document.getElementById('sl-proj').value,
    activity_date:slotDate,
    type:document.getElementById('sl-type').value,
    all_day:allday?1:0,
    hour_start:allday?null:hs,
    hour_end:allday?null:he,
    notes:document.getElementById('sl-notes').value
  }};
  fetch(bp+'/api/activities',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{
      if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}
      if(res.j.warning){{Toast.show('Aviso: '+res.j.warning,'warn');}}
      location.reload();
    }});
}}
function delActivity(id){{
  ConfirmDialog.show('¿Eliminar esta actividad?','')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/activities/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}
function openCR(id){{
  document.getElementById('cr-act-id').value=id;
  document.getElementById('cr-modal').classList.add('open');
}}
function doSendCR(){{
  var id=document.getElementById('cr-act-id').value;
  var d={{activity_id:parseInt(id),
    type:document.getElementById('cr-type').value,
    message:document.getElementById('cr-msg').value}};
  if(!d.message.trim()){{Toast.show('El mensaje es obligatorio','err');return;}}
  fetch(bp+'/api/change_requests',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}location.reload();}});
}}
(function(){{
  var now=new Date();
  var h=now.getHours();
  var sel=document.getElementById('sl-hs');
  if(sel) for(var i=0;i<sel.options.length;i++){{
    if(parseInt(sel.options[i].value)===h){{sel.selectedIndex=i;break;}}
  }}
  var sel2=document.getElementById('sl-he');
  if(sel2) for(var i=0;i<sel2.options.length;i++){{
    if(parseInt(sel2.options[i].value)===h+1){{sel2.selectedIndex=i;break;}}
  }}
}})();
document.getElementById('log-modal-day').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function doDayLog(){{
  var d={{
    user_id:document.getElementById('ld-user').value,
    project_id:document.getElementById('ld-proj').value,
    log_date:getDateVal('ld-date'),
    hours:parseFloat(document.getElementById('ld-hours').value),
    description:document.getElementById('ld-desc').value
  }};
  fetch(bp+'/api/work_logs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}location.reload();}});
}}
{pev_js_day}
{_avail_cr_js()}
</script>"""
    return _shell("calendar", user, content, title="Calendario")
