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
            f'<div class="avp-menu" style="display:none;position:absolute;z-index:300;bottom:110%;left:0;'
            f'background:var(--surface,#fff);border:1px solid var(--border);border-radius:8px;'
            f'padding:5px;gap:3px;flex-direction:column;min-width:130px;'
            f'box-shadow:0 4px 16px rgba(0,0,0,.18)">{opts}</div></div>')


def _avail_cr_js():
    """Shared JS for availability picker and change-request resolution."""
    return """
function toggleAvp(btn){
  document.querySelectorAll('.avp-menu').forEach(function(m){m.style.display='none';});
  var m=btn.nextElementSibling;
  m.style.display=(m.style.display==='flex'?'none':'flex');
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


# ── Month view ─────────────────────────────────────────────────────────────────

def _calendar_page(user, year, month):
    today = _date.today()
    if month < 1:  year -= 1; month = 12
    if month > 12: year += 1; month = 1
    first = _date(year, month, 1)
    _, days_in_month = _cal.monthrange(year, month)
    prev_y, prev_m = (year, month-1) if month > 1 else (year-1, 12)
    next_y, next_m = (year, month+1) if month < 12 else (year+1, 1)

    d1 = f"{year:04d}-{month:02d}-01"
    d2 = f"{year:04d}-{month:02d}-{days_in_month:02d}"

    activities = rs(q("""SELECT a.*,u.display_name uname,p.name pname
        FROM activities a JOIN users u ON u.id=a.user_id JOIN projects p ON p.id=a.project_id
        WHERE a.activity_date BETWEEN ? AND ?
        ORDER BY a.activity_date,a.hour_start""", (d1, d2)))

    date_list = [str(first + timedelta(days=i)) for i in range(days_in_month)]
    techs = _load_techs()
    avail = _avail_map(date_list)

    act_map = {d: [] for d in date_list}
    for a in activities:
        if a["activity_date"] in act_map:
            act_map[a["activity_date"]].append(a)

    pending_cr = {r["activity_id"] for r in
                  rs(q("SELECT activity_id FROM change_requests WHERE status='pending'"))}

    is_admin = user.get("role") == "admin"

    day_headers = "".join(
        f'<th class="{"today-col" if str(first+timedelta(days=i))==str(today) else ""}">'
        f'<a href="{BP}/calendar/{str(first+timedelta(days=i))}" style="color:inherit;text-decoration:none">'
        f'{(first+timedelta(days=i)).day}</a></th>'
        for i in range(days_in_month))

    matrix_rows = ""
    for t in techs:
        if user.get("role") not in ("admin","backoffice") and t["id"] != user.get("id"):
            continue
        initials = "".join(w[0].upper() for w in t["display_name"].split()[:2])
        col = _pcolor(t["id"])
        row_cells = (f'<td><div class="avatar avatar-sm" style="background:{col};margin:0 auto 3px">'
                     f'{_esc(initials)}</div>'
                     f'<div style="font-size:.65rem;white-space:nowrap">'
                     f'{_esc(t["display_name"].split()[0])}</div></td>')
        for i in range(days_in_month):
            d_str = str(first + timedelta(days=i))
            is_tc = (first + timedelta(days=i) == today)
            td_cls = ' class="today-col"' if is_tc else ""
            status = avail.get((t["id"], d_str), "available")
            _bg_val = _AVAIL_BG.get(status, "")
            bg = f"background:{_bg_val}" if _bg_val else ""
            day_acts = [a for a in act_map.get(d_str, []) if a["user_id"] == t["id"]]
            chips = ""
            for a in day_acts[:2]:
                pcol = _pcolor(a["project_id"])
                icon = _TYPE_ICON.get(a["type"], "📌")
                warn = " ⚠️" if a["id"] in pending_cr else ""
                chips += (f'<span title="{_esc(a["pname"])}" '
                          f'style="display:block;font-size:.6rem;background:{pcol};color:#fff;'
                          f'border-radius:3px;padding:1px 3px;margin-bottom:1px;overflow:hidden;'
                          f'white-space:nowrap;text-overflow:ellipsis">'
                          f'{icon}{warn} {_esc(a["pname"][:10])}</span>')
            if len(day_acts) > 2:
                chips += f'<span style="font-size:.6rem;color:var(--muted)">+{len(day_acts)-2}</span>'
            hrs_day = sum(
                (a["hour_end"] - a["hour_start"])
                for a in day_acts
                if not a["all_day"] and a["hour_start"] is not None and a["hour_end"] is not None)
            hrs_txt = (f'<span style="font-size:.55rem;color:var(--muted);display:block;'
                       f'text-align:right">{hrs_day}h</span>') if hrs_day else ""
            avp = _avail_picker_html(t["id"], d_str, status, is_admin, compact=True)
            row_cells += (f'<td{td_cls}>'
                          f'<a href="{BP}/calendar/{d_str}" '
                          f'style="display:block;min-height:28px;padding:2px;{bg};text-decoration:none;color:inherit">'
                          f'{chips}{hrs_txt}</a>'
                          f'<div style="text-align:right;padding:0 2px 2px">{avp}</div>'
                          f'</td>')
        matrix_rows += f"<tr>{row_cells}</tr>"

    today_monday = str(today - timedelta(days=today.weekday()))
    add_btn = (f'<button class="btn btn-primary" onclick="document.getElementById(\'act-modal\').classList.add(\'open\')">'
               f'+ Actividad</button>') if is_admin else ""
    act_modal = _activity_modal(str(today)) if is_admin else ""
    act_js    = _activity_js() if is_admin else ""

    no_rows = '<tr><td colspan="32" style="text-align:center;padding:24px;color:var(--muted)">Sin actividades este mes</td></tr>'
    cr_panel = _pending_cr_panel(user)
    content = f"""
{cr_panel}
<div class="toolbar">
  <h1>🗓 Calendario</h1>
  <div style="display:flex;gap:8px;align-items:center">
    <a href="{BP}/calendar?view=week&week_start={today_monday}" class="btn btn-ghost btn-sm">Vista semana</a>
    {add_btn}
  </div>
</div>

<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px">
  <div style="display:flex;align-items:center;gap:10px">
    <a href="{BP}/calendar?year={prev_y}&month={prev_m}" class="btn btn-ghost btn-sm">← {_MONTH_NAMES[prev_m-1]}</a>
    <h2 style="margin:0;min-width:160px;text-align:center">{_MONTH_NAMES[month-1]} {year}</h2>
    <a href="{BP}/calendar?year={next_y}&month={next_m}" class="btn btn-ghost btn-sm">{_MONTH_NAMES[next_m-1]} →</a>
  </div>
  <a href="{BP}/calendar?year={today.year}&month={today.month}" class="btn btn-ghost btn-sm">Hoy</a>
</div>

<div class="card" style="padding:0;overflow:hidden">
  <div style="overflow-x:auto">
  <table class="matrix">
    <thead><tr><th class="tech-col">Técnico</th>{day_headers}</tr></thead>
    <tbody>{matrix_rows if matrix_rows else no_rows}</tbody>
  </table>
  </div>
</div>

<div style="margin-top:10px;font-size:.75rem;color:var(--muted)">
  ⚡ Presencial &nbsp; 🌐 Online &nbsp; 👥 Reunión &nbsp; ✈️ Viaje &nbsp; 📌 Otro &nbsp;|&nbsp;
  ⚠️ Solicitud pendiente &nbsp;|&nbsp; fondo rayado = desplazado · gris = libre &nbsp;
  <span style="background:#dbeafe;border-radius:3px;padding:1px 5px">🏖 Vacaciones</span> &nbsp;
  <span style="background:#ede9fe;border-radius:3px;padding:1px 5px">📅 Día libre</span> &nbsp;
  <span style="background:#fee2e2;border-radius:3px;padding:1px 5px">🤒 Baja</span>
</div>

{act_modal}

<script>
var bp={json.dumps(BP)};
{act_js}
{_avail_cr_js()}
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
    days = [ws + timedelta(days=i) for i in range(7)]
    day_strs = [str(d) for d in days]
    week_label = f"{_MONTH_NAMES[ws.month-1]} {ws.day} – {_MONTH_NAMES[we.month-1]} {we.day}, {we.year}"

    techs  = _load_techs()
    projs  = _load_projs()
    avail  = _avail_map(day_strs)
    is_admin = user.get("role") == "admin"

    acts = rs(q("""SELECT a.*,u.display_name uname,p.name pname
        FROM activities a JOIN users u ON u.id=a.user_id JOIN projects p ON p.id=a.project_id
        WHERE a.activity_date BETWEEN ? AND ?
        ORDER BY a.activity_date,a.hour_start""", (str(ws), str(we))))

    wlogs = rs(q("""SELECT wl.*,u.display_name uname,p.name pname
        FROM work_logs wl JOIN users u ON u.id=wl.user_id JOIN projects p ON p.id=wl.project_id
        WHERE wl.log_date BETWEEN ? AND ?
        ORDER BY wl.log_date""", (str(ws), str(we))))

    act_map = {}
    for a in acts:
        act_map.setdefault((a["user_id"], a["activity_date"]), []).append(a)

    log_map = {}
    for wl in wlogs:
        log_map.setdefault((wl["user_id"], wl["log_date"]), []).append(wl)

    def _day_th(d):
        is_tc = (d == today)
        sty = ' style="background:color-mix(in srgb,var(--primary) 12%,transparent)"' if is_tc else ""
        return (f'<th{sty}>'
                f'<div style="font-weight:700">{_DOW_SHORT[d.weekday()]}</div>'
                f'<div style="font-size:.75rem">'
                f'<a href="{BP}/calendar/{d}" style="color:inherit">{d.day}/{d.month}</a>'
                f'</div></th>')

    day_ths = "".join(_day_th(d) for d in days)

    def _act_cell(uid, d_str):
        acts_cell = act_map.get((uid, d_str), [])
        status = avail.get((uid, d_str), "available")
        bg = ""
        if status == "off":
            bg = "background:var(--border)"
        elif status == "traveling":
            bg = "background:repeating-linear-gradient(45deg,transparent,transparent 3px,rgba(255,165,0,.15) 3px,rgba(255,165,0,.15) 6px)"
        inner = ""
        hrs_plan = 0
        for a in acts_cell:
            if not a["all_day"] and a["hour_start"] is not None and a["hour_end"] is not None:
                hrs_plan += (a["hour_end"] - a["hour_start"])
            col = _pcolor(a["project_id"])
            icon = _TYPE_ICON.get(a["type"], "📌")
            hs = a.get("hour_start") or 0
            he = a.get("hour_end") or 0
            inner += (f'<div style="font-size:.65rem;background:{col};color:#fff;border-radius:3px;'
                      f'padding:2px 4px;margin-bottom:2px;white-space:nowrap;overflow:hidden;'
                      f'text-overflow:ellipsis" title="{_esc(a["pname"])} · {hs:02d}:00–{he:02d}:00">'
                      f'{icon} {_esc(a["pname"][:14])}</div>')
        if hrs_plan:
            pct = min(100, int(hrs_plan / 8 * 100))
            bar_col = "#ef4444" if pct >= 100 else "#f59e0b" if pct >= 75 else "#22c55e"
            inner += (f'<div style="font-size:.6rem;color:var(--muted);text-align:right;margin-top:2px">'
                      f'{hrs_plan}h / 8h</div>'
                      f'<div style="height:4px;background:var(--border);border-radius:2px;margin-top:2px">'
                      f'<div style="height:100%;width:{pct}%;background:{bar_col};border-radius:2px"></div>'
                      f'</div>')
        avp = _avail_picker_html(uid, d_str, status, is_admin, compact=True)
        inner += f'<div style="text-align:right;margin-top:3px">{avp}</div>'
        return f'<td style="vertical-align:top;padding:4px;min-width:90px;{bg}">{inner}</td>'

    def _log_cell(uid, d_str):
        logs_cell = log_map.get((uid, d_str), [])
        hrs = sum(l["hours"] for l in logs_cell)
        inner = ""
        for l in logs_cell:
            col = _pcolor(l["project_id"])
            inner += (f'<div style="font-size:.65rem;background:{col};color:#fff;border-radius:3px;'
                      f'padding:2px 4px;margin-bottom:2px;white-space:nowrap;overflow:hidden;'
                      f'text-overflow:ellipsis" title="{_esc(l["pname"])}: {l["hours"]}h">'
                      f'{l["hours"]}h {_esc(l["pname"][:10])}'
                      f'<button onclick="delWorkLog({l["id"]})" style="float:right;background:none;'
                      f'border:none;color:#fff;cursor:pointer;padding:0 2px;font-size:.7rem">✕</button>'
                      f'</div>')
        uid_js = json.dumps(uid)
        date_js = json.dumps(d_str)
        add_btn_html = (f'<button onclick="openLogModal({uid_js},{date_js})" '
                        f'style="width:100%;font-size:.6rem;padding:2px;margin-top:2px;background:none;'
                        f'border:1px dashed var(--border);border-radius:3px;cursor:pointer;'
                        f'color:var(--muted)">+ horas</button>')
        if hrs:
            inner += f'<div style="font-size:.6rem;font-weight:700;text-align:right">{hrs}h total</div>'
        return f'<td style="vertical-align:top;padding:4px">{inner}{add_btn_html}</td>'

    plan_rows = ""
    log_rows  = ""
    plan_totals = {d: 0 for d in day_strs}
    log_totals  = {d: 0.0 for d in day_strs}

    for t in techs:
        if user.get("role") not in ("admin","backoffice") and t["id"] != user.get("id"):
            continue
        initials = "".join(w[0].upper() for w in t["display_name"].split()[:2])
        col = _pcolor(t["id"])
        th_cell = (f'<td style="white-space:nowrap">'
                   f'<div class="avatar avatar-sm" style="background:{col};display:inline-flex;margin-right:4px">'
                   f'{_esc(initials)}</div>'
                   f'<span style="font-size:.75rem">{_esc(t["display_name"])}</span></td>')
        plan_row = th_cell
        log_row  = th_cell
        for d_str in day_strs:
            plan_row += _act_cell(t["id"], d_str)
            log_row  += _log_cell(t["id"], d_str)
            plan_totals[d_str] += sum(
                (a["hour_end"] - a["hour_start"])
                for a in act_map.get((t["id"], d_str), [])
                if not a["all_day"] and a["hour_end"] and a["hour_start"])
            log_totals[d_str] += sum(l["hours"] for l in log_map.get((t["id"], d_str), []))
        plan_rows += f"<tr>{plan_row}</tr>"
        log_rows  += f"<tr>{log_row}</tr>"

    plan_foot = "<td><strong>Total</strong></td>" + "".join(
        f'<td style="text-align:center;font-size:.75rem;font-weight:700">{plan_totals[d]}h</td>'
        for d in day_strs)
    log_foot = "<td><strong>Total</strong></td>" + "".join(
        f'<td style="text-align:center;font-size:.75rem;font-weight:700">{round(log_totals[d],1)}h</td>'
        for d in day_strs)

    def _table(tbody, tfoot):
        if not tbody:
            return '<p class="muted" style="text-align:center;padding:24px">Sin datos esta semana</p>'
        return (f'<div style="overflow-x:auto"><table class="matrix" style="min-width:600px">'
                f'<thead><tr><th style="min-width:120px">Técnico</th>{day_ths}</tr></thead>'
                f'<tbody>{tbody}</tbody>'
                f'<tfoot><tr style="background:var(--surface)">{tfoot}</tr></tfoot>'
                f'</table></div>')

    user_opts_wk = _user_options()
    proj_opts_wk = _proj_options()
    this_week_link = (f'<a href="{BP}/calendar?view=week&week_start={this_ws}" class="btn btn-ghost btn-sm">'
                      f'Esta semana</a>') if str(ws) != this_ws else ""

    add_act_btn = (f'<button class="btn btn-primary" onclick="document.getElementById(\'act-modal\').classList.add(\'open\')">'
                   f'+ Actividad</button>') if is_admin else ""
    act_modal = _activity_modal(str(today)) if is_admin else ""
    act_js    = _activity_js() if is_admin else ""
    cr_panel  = _pending_cr_panel(user)

    content = f"""
{cr_panel}
<div class="toolbar">
  <h1>🗓 Semana</h1>
  <div style="display:flex;gap:8px">
    <a href="{BP}/calendar?year={ws.year}&month={ws.month}" class="btn btn-ghost btn-sm">Vista mes</a>
    {add_act_btn}
  </div>
</div>

<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap">
  <a href="{BP}/calendar?view=week&week_start={prev_ws}" class="btn btn-ghost btn-sm">← Semana anterior</a>
  <span style="font-weight:700;flex:1;text-align:center">{week_label}</span>
  <a href="{BP}/calendar?view=week&week_start={next_ws}" class="btn btn-ghost btn-sm">Semana siguiente →</a>
  {this_week_link}
</div>

<div class="tabs" style="margin-bottom:12px">
  <button class="tab-btn active" id="tab-plan" onclick="switchTab('plan')">📅 Planificado</button>
  <button class="tab-btn" id="tab-reg" onclick="switchTab('reg')">🕐 Registrado</button>
</div>

<div id="view-plan">
  <div class="card" style="padding:0">{_table(plan_rows, plan_foot)}</div>
</div>
<div id="view-reg" style="display:none">
  <div class="card" style="padding:0">{_table(log_rows, log_foot)}</div>
</div>

{act_modal}

<!-- MODAL registrar horas -->
<div class="modal-bg" id="log-modal">
<div class="modal" style="max-width:460px">
  <h2>Registrar horas</h2>
  <div class="form-row">
    <div><label>Técnico</label><select id="lm-user">{user_opts_wk}</select></div>
    <div><label>Proyecto</label><select id="lm-proj">{proj_opts_wk}</select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha</label><input type="date" id="lm-date"></div>
    <div><label>Horas</label><input type="number" id="lm-hours" min="0.25" max="24" step="0.25" value="1"></div>
  </div>
  <div class="form-row single"><div><label>Descripción</label>
    <input id="lm-desc" placeholder="Qué se hizo..."></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost"
      onclick="document.getElementById('log-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doCreateLog()">Guardar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
{act_js}
document.getElementById('log-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function switchTab(t){{
  document.getElementById('view-plan').style.display=t==='plan'?'':'none';
  document.getElementById('view-reg').style.display=t==='reg'?'':'none';
  document.getElementById('tab-plan').classList.toggle('active',t==='plan');
  document.getElementById('tab-reg').classList.toggle('active',t==='reg');
}}
function openLogModal(uid,date){{
  setDateVal('lm-date',date);
  var sel=document.getElementById('lm-user');
  for(var i=0;i<sel.options.length;i++){{if(sel.options[i].value==uid){{sel.selectedIndex=i;break;}}}}
  document.getElementById('log-modal').classList.add('open');
}}
function doCreateLog(){{
  var d={{
    user_id:document.getElementById('lm-user').value,
    project_id:document.getElementById('lm-proj').value,
    log_date:getDateVal('lm-date'),
    hours:parseFloat(document.getElementById('lm-hours').value),
    description:document.getElementById('lm-desc').value
  }};
  fetch(bp+'/api/work_logs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}});}})
    .then(function(res){{if(!res.ok){{Toast.show(res.j.error||'Error','err');return;}}location.reload();}});
}}
function delWorkLog(id){{
  ConfirmDialog.show('¿Eliminar este registro de horas?','')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/work_logs/'+id,{{method:'DELETE'}}).then(function(r){{if(r.ok)location.reload();}});
    }});
}}
{_avail_cr_js()}
</script>"""
    return _shell("calendar", user, content, title="Calendario")


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
        bg_sty = ""
        if status == "off":
            bg_sty = "background:var(--border)"
        elif status == "traveling":
            bg_sty = "background:color-mix(in srgb,orange 20%,transparent)"
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
    add_sidebar = (f'<div style="margin-top:12px">'
                   f'<button class="btn btn-primary btn-sm" style="width:100%" '
                   f'onclick="document.getElementById(\'slot-modal\').classList.add(\'open\')">'
                   f'+ Añadir actividad</button></div>') if is_admin else ""

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
    <div style="display:flex;gap:8px">{add_btn_day} {add_log_btn_day}</div>
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
  </div>
</div>

</div>

{slot_modal_html}
{cr_modal_html}
{log_modal_day}

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
{_avail_cr_js()}
</script>"""
    return _shell("calendar", user, content, title="Calendario")
