"""Calendar pages."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
)
from web.layout import _shell

def _calendar_page(user, year, month):
    today = _date.today()
    # clamp month
    if month < 1: year -= 1; month = 12
    if month > 12: year += 1; month = 1
    first = _date(year, month, 1)
    _, days_in_month = _cal.monthrange(year, month)
    last = _date(year, month, days_in_month)

    # prev/next
    prev_y, prev_m = (year, month-1) if month > 1 else (year-1, 12)
    next_y, next_m = (year, month+1) if month < 12 else (year+1, 1)

    # load assignments: project_members with date ranges
    raw_members = rs(q("""
        SELECT pm.id, pm.project_id, pm.user_id, pm.start_date, pm.end_date,
               u.display_name uname, p.name pname, p.status pstatus
        FROM project_members pm
        JOIN users u ON u.id=pm.user_id
        JOIN projects p ON p.id=pm.project_id
        WHERE p.status NOT IN ('cancelled')
    """))

    # expand each member into days within this month
    # day_map: day_str → list of {uid, uname, pid, pname}
    day_map = {str(first + timedelta(days=i)): [] for i in range(days_in_month)}

    for mb in raw_members:
        s_str = mb['start_date'] or str(first)
        e_str = mb['end_date'] or str(last)
        try: s = _date.fromisoformat(s_str)
        except: s = first
        try: e = _date.fromisoformat(e_str)
        except: e = last
        s = max(s, first)
        e = min(e, last)
        if s > e: continue
        cur = s
        while cur <= e:
            k = str(cur)
            if k in day_map:
                day_map[k].append({"uid": mb['user_id'], "uname": mb['uname'],
                                   "pid": mb['project_id'], "pname": mb['pname']})
            cur += timedelta(days=1)

    # ── all active users ──
    all_users = rs(q("SELECT id,display_name FROM users WHERE active=1 AND role!='backoffice' ORDER BY display_name"))
    user_opts = "".join(f'<option value="{u["id"]}">{_esc(u["display_name"])}</option>' for u in all_users)

    # ── active projects ──
    all_projs = rs(q("SELECT id,name FROM projects WHERE status IN ('active','paused') ORDER BY name"))
    proj_opts = "".join(f'<option value="{p["id"]}">{_esc(p["name"])}</option>' for p in all_projs)

    # ── calendar grid ──
    dow_labels = "".join(f'<div class="cal-dow">{d}</div>' for d in ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"])

    # pad start
    first_dow = first.weekday()  # 0=Mon
    cells = ['<div class="cal-day other-month"></div>'] * first_dow

    for i in range(days_in_month):
        day = first + timedelta(days=i)
        day_str = str(day)
        is_today = (day == today)
        today_cls = " today" if is_today else ""
        chips = ""
        seen = set()
        for ent in day_map[day_str]:
            k = (ent['uid'], ent['pid'])
            if k in seen: continue
            seen.add(k)
            col = _pcolor(ent['pid'])
            initials = "".join(w[0].upper() for w in ent['uname'].split()[:2])
            chips += (f'<span class="cal-chip" style="background:{col}" '
                      f'title="{_esc(ent["uname"])} → {_esc(ent["pname"])}">'
                      f'{_esc(initials)} {_esc(ent["pname"][:12])}</span>')
        cells.append(f'<a href="{BP}/calendar/{day_str}" class="cal-day{today_cls}"><div class="cal-day-num">{day.day}</div>{chips}</a>')

    # pad end to complete the last week
    while len(cells) % 7 != 0:
        cells.append('<div class="cal-day other-month"></div>')

    grid_html = dow_labels + "".join(cells)

    # ── matrix view: technicians × days ──
    # rows = technicians, cols = each day of month
    # Only show technicians with at least one assignment this month
    tech_ids = sorted({ent['uid'] for dl in day_map.values() for ent in dl})
    tech_names = {mb['user_id']: mb['uname'] for mb in raw_members}
    for u in all_users:
        tech_names[u['id']] = u['display_name']

    matrix_html = ""
    if tech_ids:
        day_headers = "".join(
            f'<th class={"today-col" if str(first+timedelta(days=i))==str(today) else ""}>{(first+timedelta(days=i)).day}</th>'
            for i in range(days_in_month))
        matrix_html = f'<div class="matrix-wrap"><table class="matrix"><thead><tr><th class="tech-col">Técnico</th>{day_headers}</tr></thead><tbody>'
        for uid in tech_ids:
            uname = tech_names.get(uid, str(uid))
            initials = "".join(w[0].upper() for w in uname.split()[:2])
            col = _pcolor(uid)
            row = f'<td><div class="avatar avatar-sm" style="background:{col};margin:auto">{_esc(initials)}</div> <span style="font-size:.75rem">{_esc(uname)}</span></td>'
            for i in range(days_in_month):
                day_str = str(first + timedelta(days=i))
                is_tc = (first + timedelta(days=i) == today)
                entries = [e for e in day_map[day_str] if e['uid'] == uid]
                if entries:
                    e0 = entries[0]
                    col_p = _pcolor(e0['pid'])
                    cell = f'<span class="matrix-cell" style="background:{col_p}" title="{_esc(e0["pname"])}">{_esc(e0["pname"][:6])}</span>'
                else:
                    cell = ""
                td_cls = ' class="today-col"' if is_tc else ""
                row += f'<td{td_cls}>{cell}</td>'
            matrix_html += f'<tr>{row}</tr>'
        matrix_html += '</tbody></table></div>'
    else:
        matrix_html = '<p class="muted" style="text-align:center;padding:24px">Sin asignaciones este mes</p>'

    month_names = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                   "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    month_label = f"{month_names[month-1]} {year}"

    content = f"""
<div class="toolbar">
  <h1>🗓 Calendario de personal</h1>
  <button class="btn btn-primary" onclick="document.getElementById('assign-modal').classList.add('open')">+ Asignación</button>
</div>

<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px">
  <div style="display:flex;align-items:center;gap:10px">
    <a href="{BP}/calendar?year={prev_y}&month={prev_m}" class="btn btn-ghost btn-sm">← {month_names[prev_m-1]}</a>
    <h2 style="margin:0;min-width:160px;text-align:center">{month_label}</h2>
    <a href="{BP}/calendar?year={next_y}&month={next_m}" class="btn btn-ghost btn-sm">{month_names[next_m-1]} →</a>
  </div>
  <a href="{BP}/calendar?year={today.year}&month={today.month}" class="btn btn-ghost btn-sm">Hoy</a>
</div>

<div class="card" style="padding:16px">
  <h2 style="margin-bottom:12px">Vista mensual</h2>
  <div class="cal-grid">{grid_html}</div>
</div>

<div class="card" style="padding:16px">
  <h2 style="margin-bottom:12px">Carga por técnico — {month_label}</h2>
  {matrix_html}
</div>

<!-- MODAL nueva asignación -->
<div class="modal-bg" id="assign-modal">
<div class="modal" style="max-width:480px">
  <h2>Nueva asignación de personal</h2>
  <div class="form-row single">
    <div><label>Técnico</label><select id="ca-user">{user_opts}</select></div>
  </div>
  <div class="form-row single">
    <div><label>Proyecto</label><select id="ca-proj">{proj_opts}</select></div>
  </div>
  <div class="form-row">
    <div><label>Fecha inicio</label><input type="date" id="ca-start" value="{first}"></div>
    <div><label>Fecha fin</label><input type="date" id="ca-end" value="{last}"></div>
  </div>
  <div class="form-row single">
    <div><label>Notas</label><input id="ca-notes" placeholder="Turno, rol específico..."></div>
  </div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('assign-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doCreateAssign()">Guardar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
document.getElementById('assign-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function doCreateAssign(){{
  var pid=document.getElementById('ca-proj').value;
  var d={{user_id:document.getElementById('ca-user').value,
    start_date:document.getElementById('ca-start').value,
    end_date:document.getElementById('ca-end').value,
    notes:document.getElementById('ca-notes').value}};
  fetch(bp+'/api/projects/'+pid+'/members',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
</script>"""
    return _shell("calendar", user, content)

# ── calendar day detail ────────────────────────────────────────────────────────
def _calendar_day(user, day_str):
    try:
        day = _date.fromisoformat(day_str)
    except ValueError:
        return None

    today = _date.today()
    prev_day = str(day - timedelta(days=1))
    next_day = str(day + timedelta(days=1))

    month_names = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                   "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    dow_names   = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    day_label   = f"{dow_names[day.weekday()]} {day.day} de {month_names[day.month-1]} {day.year}"

    # load slots for this day
    slots = rs(q("""SELECT ss.*,u.display_name uname,p.name pname
        FROM schedule_slots ss
        JOIN users u ON u.id=ss.user_id
        JOIN projects p ON p.id=ss.project_id
        WHERE ss.slot_date=?
        ORDER BY ss.hour_start, u.display_name""", (day_str,)))

    # all active technicians (columns)
    techs = rs(q("SELECT id,display_name FROM users WHERE active=1 AND show_in_planning=1 ORDER BY display_name"))
    # active projects for modal
    projs = rs(q("SELECT id,name FROM projects WHERE status IN ('active','paused') ORDER BY name"))

    tech_opts = "".join(f'<option value="{t["id"]}">{_esc(t["display_name"])}</option>' for t in techs)
    proj_opts = "".join(f'<option value="{p["id"]}">{_esc(p["name"])}</option>' for p in projs)
    hour_opts_start = "".join(f'<option value="{h}">{"0"+str(h) if h<10 else h}:00</option>' for h in range(6,20))
    hour_opts_end   = "".join(f'<option value="{h}" {"selected" if h==9 else ""}>{"0"+str(h) if h<10 else h}:00</option>' for h in range(7,21))

    # build matrix: hours 6..20 × techs
    now_hour = datetime.now().hour if day == today else -1
    tech_ids = [t['id'] for t in techs]

    # slot lookup: (tech_id, hour) → slot
    slot_map = {}
    for s in slots:
        for h in range(s['hour_start'], s['hour_end']):
            key = (s['user_id'], h)
            if key not in slot_map:
                slot_map[key] = s

    # Generate matrix HTML
    # Header row
    th_techs = "".join(
        f'<th><div class="avatar avatar-sm" style="background:{_pcolor(t["id"])};margin:0 auto 3px">'
        f'{"".join(w[0].upper() for w in t["display_name"].split()[:2])}</div>'
        f'<div style="font-size:.65rem">{_esc(t["display_name"].split()[0])}</div></th>'
        for t in techs)

    rows_html = ""
    for h in range(6, 21):
        now_cls = ' class="now-row"' if h == now_hour else ''
        cells = ""
        for tid in tech_ids:
            s = slot_map.get((tid, h))
            if s:
                col = _pcolor(s['project_id'])
                pshort = _esc(s['pname'][:14])
                if s['hour_start'] == h:
                    end_str = f'{s["hour_end"]:02d}:00'
                    cells += (f'<td{now_cls}><div class="slot-block" style="background:{col}">'
                              f'{pshort}'
                              f'<br><span style="opacity:.8;font-size:.6rem">→ {end_str}</span>'
                              f'<button class="slot-del" onclick="delSlot({s["id"]})">✕</button>'
                              f'</div></td>')
                else:
                    cells += (f'<td{now_cls}><div class="slot-block" style="background:{col};opacity:.7">'
                              f'<span style="opacity:.6">·</span></div></td>')
            else:
                cells += f'<td{now_cls}></td>'
        hstr = f'{"0" if h<10 else ""}{h}:00'
        rows_html += f'<tr><td class="hour-label">{hstr}</td>{cells}</tr>'

    # slots list (sidebar summary)
    slot_list = ""
    for s in slots:
        col = _pcolor(s['project_id'])
        initials = "".join(w[0].upper() for w in s['uname'].split()[:2])
        slot_list += (
            f'<div style="display:flex;align-items:center;gap:8px;padding:8px 0;'
            f'border-bottom:1px solid var(--border)">'
            f'<div class="avatar" style="background:{col}">{_esc(initials)}</div>'
            f'<div style="flex:1">'
            f'<div class="fw7" style="font-size:.85rem">{_esc(s["uname"])}</div>'
            f'<div style="font-size:.75rem;color:var(--muted)">{s["hour_start"]:02d}:00 → {s["hour_end"]:02d}:00 · {_esc(s["pname"])}</div>'
            f'{("<div style=font-size:.72rem;color:var(--muted)>"+_esc(s["notes"])+"</div>") if s.get("notes") else ""}'
            f'</div>'
            f'<button class="btn btn-danger btn-icon" style="font-size:.7rem" onclick="delSlot({s["id"]})">✕</button>'
            f'</div>')

    if not slot_list:
        slot_list = '<p class="muted" style="padding:12px 0;font-size:.85rem;text-align:center">Sin franjas asignadas</p>'

    content = f"""
<div class="day-nav">
  <a href="{BP}/calendar/{prev_day}" class="btn btn-ghost btn-sm">← {prev_day}</a>
  <div style="flex:1;text-align:center">
    <h1 style="margin:0">{day_label}</h1>
    <a href="{BP}/calendar?year={day.year}&month={day.month}" class="muted" style="font-size:.8rem">
      ← Volver al mes
    </a>
  </div>
  <a href="{BP}/calendar/{next_day}" class="btn btn-ghost btn-sm">{next_day} →</a>
</div>

<div style="display:grid;grid-template-columns:1fr 280px;gap:18px;align-items:start">

<div class="card" style="padding:0;overflow:hidden">
  <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
    <h2 style="margin:0">Horario hora a hora</h2>
    <button class="btn btn-primary btn-sm" onclick="document.getElementById('slot-modal').classList.add('open')">+ Franja horaria</button>
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
    <div style="margin-top:12px">
      <button class="btn btn-primary btn-sm" style="width:100%" onclick="document.getElementById('slot-modal').classList.add('open')">+ Añadir franja</button>
    </div>
  </div>
</div>

</div>

<!-- MODAL nueva franja -->
<div class="modal-bg" id="slot-modal">
<div class="modal" style="max-width:460px">
  <h2>Nueva franja horaria</h2>
  <div class="form-row single"><div><label>Técnico</label><select id="sl-user">{tech_opts}</select></div></div>
  <div class="form-row single"><div><label>Proyecto</label><select id="sl-proj">{proj_opts}</select></div></div>
  <div class="form-row">
    <div><label>Hora inicio</label><select id="sl-start">{hour_opts_start}</select></div>
    <div><label>Hora fin</label><select id="sl-end">{hour_opts_end}</select></div>
  </div>
  <div class="form-row single"><div><label>Notas (opcional)</label>
    <input id="sl-notes" placeholder="Reunión, desplazamiento, tarea..."></div></div>
  <div class="modal-foot">
    <button type="button" class="btn btn-ghost" onclick="document.getElementById('slot-modal').classList.remove('open')">Cancelar</button>
    <button class="btn btn-primary" onclick="doAddSlot()">Guardar</button>
  </div>
</div></div>

<script>
var bp={json.dumps(BP)};
var slotDate="{day_str}";
document.getElementById('slot-modal').onclick=function(e){{if(e.target===this)this.classList.remove('open');}};
function doAddSlot(){{
  var hs=parseInt(document.getElementById('sl-start').value);
  var he=parseInt(document.getElementById('sl-end').value);
  if(he<=hs){{alert('La hora fin debe ser posterior a la hora inicio');return;}}
  fetch(bp+'/api/schedule_slots',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{user_id:document.getElementById('sl-user').value,
      project_id:document.getElementById('sl-proj').value,
      slot_date:slotDate,hour_start:hs,hour_end:he,
      notes:document.getElementById('sl-notes').value}})}})
    .then(function(r){{if(r.ok)location.reload();else r.json().then(function(j){{alert(j.error||'Error');}});}});
}}
function delSlot(id){{
  if(!confirm('¿Eliminar esta franja?')) return;
  fetch(bp+'/api/schedule_slots/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
// pre-select hour based on current time
(function(){{
  var now=new Date();
  var h=now.getHours();
  var sel=document.getElementById('sl-start');
  for(var i=0;i<sel.options.length;i++){{
    if(parseInt(sel.options[i].value)===h){{sel.selectedIndex=i;break;}}
  }}
  var sel2=document.getElementById('sl-end');
  for(var i=0;i<sel2.options.length;i++){{
    if(parseInt(sel2.options[i].value)===h+1){{sel2.selectedIndex=i;break;}}
  }}
}})();
</script>"""
    return _shell("calendar", user, content)

# ── workload view ────────────────────────────────────────────────────────────
