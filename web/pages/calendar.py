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


# ── Month view ─────────────────────────────────────────────────────────────────

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

    activities = rs(q("""SELECT a.*,u.display_name uname,p.name pname
        FROM activities a JOIN users u ON u.id=a.user_id JOIN projects p ON p.id=a.project_id
        WHERE a.activity_date BETWEEN ? AND ?
        ORDER BY a.activity_date,a.hour_start""", (d1, d2)))

    date_list = [str(first + timedelta(days=i)) for i in range(dim)]
    avail = _avail_map(date_list)
    techs = _load_techs()

    act_map = {}
    for a in activities:
        act_map.setdefault(a["activity_date"], []).append(a)

    pending_cr = {r["activity_id"] for r in rs(q("SELECT activity_id FROM change_requests WHERE status='pending'"))}
    is_admin = user.get("role") == "admin"

    # Grid starts on the Monday of the week containing the 1st
    grid_start = first - timedelta(days=first.weekday())

    dow_headers = "".join(
        f'<div class="cal-dow" style="{"color:var(--warn,#f59e0b)" if i >= 5 else ""}">{d}</div>'
        for i, d in enumerate(_DOW_SHORT))

    # Generate 6 rows × 7 cols = 42 cells
    cells_html = ""
    cur = grid_start
    for _ in range(42):
        d_str = str(cur)
        in_m     = (cur.month == month)
        is_tod   = (cur == today)
        is_wkend = (cur.weekday() >= 5)

        cls = "cal-cell"
        if not in_m:          cls += " other-m"
        if is_tod:             cls += " today-c"
        if is_wkend and in_m: cls += " wkend"

        dn_html = f'<div class="cal-dn">{cur.day}</div>'

        # Availability dots (only for days in month)
        dots = ""
        if in_m:
            avail_count = 0
            for t in techs:
                st = avail.get((t["id"], d_str), "available")
                if st in ("available", ""):
                    avail_count += 1
                else:
                    col = _AVAIL_COLOR.get(st, "#16a34a")
                    dots += f'<div class="cal-adot" style="background:{col}" title="{_esc(t["display_name"])}: {_AVAIL_LABEL.get(st,st)}"></div>'
            if avail_count:
                dots += f'<div class="cal-adot" style="background:#16a34a" title="{avail_count} disponible{"s" if avail_count!=1 else ""}"></div>'
        dots_html = f'<div class="cal-adots">{dots}</div>' if dots else ""

        # Activity chips
        day_acts = act_map.get(d_str, []) if in_m else []
        chips = ""
        for a in day_acts[:2]:
            col  = _pcolor(a["project_id"])
            icon = _TYPE_ICON.get(a["type"], "📌")
            warn = " ⚠️" if a["id"] in pending_cr else ""
            chips += (f'<div class="cal-chip" style="background:{col}" '
                      f'title="{_esc(a["pname"])} — {_esc(a["uname"])}">'
                      f'{icon}{warn} {_esc(a["pname"][:13])}</div>')
        if len(day_acts) > 2:
            chips += f'<div class="cal-more">+{len(day_acts)-2} más</div>'

        cells_html += (f'<a href="{BP}/calendar/{d_str}" class="{cls}">'
                       f'{dn_html}{dots_html}{chips}</a>')
        cur += timedelta(days=1)

    today_monday = str(today - timedelta(days=today.weekday()))
    add_btn  = (f'<button class="btn btn-primary" onclick="document.getElementById(\'act-modal\').classList.add(\'open\')">'
                f'+ Actividad</button>') if is_admin else ""
    act_modal = _activity_modal(str(today)) if is_admin else ""
    act_js    = _activity_js() if is_admin else ""
    cr_panel  = _pending_cr_panel(user)
    right     = _right_panel(user, year, month, today, is_admin)

    content = f"""
{cr_panel}
<div class="cal-layout">
  <div class="cal-main-area">
    <div class="toolbar" style="margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:6px">
        <a href="{BP}/calendar?view=week&week_start={today_monday}" class="btn btn-ghost btn-sm">Vista semana</a>
      </div>
      <div style="display:flex;align-items:center;gap:6px">
        <a href="{BP}/calendar?year={prev_y}&month={prev_m}" class="btn btn-ghost btn-sm">‹</a>
        <h2 style="margin:0;font-size:1rem;min-width:145px;text-align:center">{_MONTH_NAMES[month-1]} {year}</h2>
        <a href="{BP}/calendar?year={next_y}&month={next_m}" class="btn btn-ghost btn-sm">›</a>
        <a href="{BP}/calendar?year={today.year}&month={today.month}" class="btn btn-ghost btn-sm">Hoy</a>
      </div>
      {add_btn}
    </div>
    <div class="cal-grid-wrap">
      <div class="cal-grid">
        {dow_headers}
        {cells_html}
      </div>
    </div>
  </div>
  {right}
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
            cell_inner += f'<div style="text-align:right;margin-top:2px">{avp}</div>'
            row += f'<div class="wsl-cell {bg_cls}">{cell_inner}</div>'
        rows_html += row

    this_week_link = (f'<a href="{BP}/calendar?view=week&week_start={this_ws}" class="btn btn-ghost btn-sm">Esta semana</a>'
                      ) if str(ws) != this_ws else ""
    add_btn  = (f'<button class="btn btn-primary" onclick="document.getElementById(\'act-modal\').classList.add(\'open\')">'
                f'+ Actividad</button>') if is_admin else ""
    act_modal = _activity_modal(str(today)) if is_admin else ""
    act_js    = _activity_js() if is_admin else ""
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
      {add_btn}
    </div>
    <div class="week-sl" style="grid-template-columns:{col_tmpl}">
      {day_headers}
      {rows_html}
    </div>
  </div>
  {right}
</div>
{act_modal}
<script>
var bp={json.dumps(BP)};
{act_js}
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
  </div>
  {right}
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
