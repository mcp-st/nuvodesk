"""Project report pages."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
)
from web.layout import _shell

def _project_report(user, pid):
    p = r2d(q1("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to WHERE p.id=?""", (pid,)))
    if not p: return None
    tasks = rs(q("SELECT * FROM tasks WHERE project_id=? ORDER BY status,priority DESC", (pid,)))
    assignments = rs(q("""SELECT a.*,m.name mat_name,m.code mat_code,m.unit mat_unit
        FROM assignments a JOIN materials m ON m.id=a.material_id
        WHERE a.project_id=? ORDER BY m.name""", (pid,)))
    logs = rs(q("""SELECT l.*,u.display_name uname
        FROM project_logs l JOIN users u ON u.id=l.user_id
        WHERE l.project_id=? ORDER BY l.created_at""", (pid,)))
    time_summary_r = rs(q("""SELECT u.display_name uname,
        COUNT(DISTINCT date(te.started_at)) days,
        COALESCE(SUM(CASE WHEN te.ended_at IS NOT NULL
            THEN (julianday(te.ended_at)-julianday(te.started_at))*86400 ELSE 0 END),0) total_secs
        FROM time_entries te JOIN users u ON u.id=te.user_id
        WHERE te.project_id=? AND te.ended_at IS NOT NULL
        GROUP BY u.id ORDER BY total_secs DESC""", (pid,)))
    extras_r = rs(q("""SELECT we.*,u.display_name uname
        FROM wo_extras we LEFT JOIN users u ON u.id=we.added_by
        WHERE we.project_id=? ORDER BY we.created_at""", (pid,)))
    equipment_r = rs(q("""SELECT ei.*,u.display_name uname
        FROM equipment_items ei LEFT JOIN users u ON u.id=ei.added_by
        WHERE ei.project_id=? ORDER BY ei.created_at""", (pid,)))
    ph_row = q1("SELECT COALESCE(SUM(hours),0),COALESCE(SUM(hours*technicians),0) FROM project_logs WHERE project_id=?", (pid,))
    h_logged = ph_row[0] if ph_row else 0
    ph_logged = ph_row[1] if ph_row else 0
    h_est = p.get("estimated_hours") or 0
    task_done = sum(1 for t in tasks if t['status']=='done')
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    st_label = STATUS_LABEL.get(p['status'], p['status'])
    pri_label = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(p['priority'],p['priority'])

    t_rows = ""
    for s, slbl in [("blocked","🔴 Bloqueado"),("in_progress","🔵 En curso"),
                    ("pending","⚪ Pendiente"),("done","✅ Hecho")]:
        for t in [x for x in tasks if x['status']==s]:
            pril = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(t['priority'],'')
            desc_part = f'<br><small style="color:#64748b">{_esc(t["description"])}</small>' if t.get("description") else ""
            t_rows += (f'<tr><td>{_esc(t["title"])}{desc_part}</td>'
                f'<td>{slbl}</td><td>{pril}</td>'
                f'<td>{_esc((t["due_date"] or "—")[:10])}</td></tr>')

    m_rows = "".join(
        f'<tr><td><code>{_esc(a["mat_code"])}</code> {_esc(a["mat_name"])}</td>'
        f'<td style="text-align:center">{a["qty_requested"]}</td>'
        f'<td style="text-align:center">{a["qty_assigned"]}</td>'
        f'<td style="text-align:center">{a["qty_consumed"]}</td>'
        f'<td style="text-align:center">{a["qty_returned"]}</td>'
        f'<td>{STATUS_LABEL.get(a["status"],a["status"])}</td>'
        f'<td>{_esc(a["mat_unit"])}</td></tr>' for a in assignments)

    log_html = ""
    for l in logs:
        techs = int(l.get('technicians') or 1)
        ph = (l['hours'] or 0) * techs
        if l['hours']:
            h_str = f' · {l["hours"]}h'
            if techs > 1:
                h_str += f' × {techs} técnicos = <strong>{ph:.1f} person-h</strong>'
        else:
            h_str = ""
        log_html += (f'<div style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #e2e8f0">'
            f'<div style="font-size:.78rem;color:#64748b;margin-bottom:4px">'
            f'<strong>{_esc(l["uname"])}</strong> — {_esc(l["created_at"][:16])}{h_str}</div>'
            f'<div style="line-height:1.55;white-space:pre-wrap;font-size:.9rem">{_esc(l["body"])}</div></div>')

    wt_info = WORK_TYPES.get(p.get('work_type') or 'proyecto', WORK_TYPES['proyecto'])
    total_time_secs = sum(ts['total_secs'] for ts in time_summary_r)
    meta = [("Tipo de trabajo", f'{wt_info["icon"]} {wt_info["name"]}'),
            ("Cliente",p.get("client","")),("Referencia",p.get("reference","")),
            ("Dirección",p.get("address","")),("Técnico",p.get("tech","")),
            ("Contacto obra",p.get("contact_name","")),("Teléfono",p.get("contact_phone","")),
            ("Inicio",(p.get("start_date") or "")[:10]),("Límite",(p.get("due_date") or "")[:10]),
            ("Estado",st_label),("Prioridad",pri_label),
            ("Horas estimadas",f'{h_est}h' if h_est else ""),
            ("Tiempo total registrado", _fmt_duration(total_time_secs) if total_time_secs else "—"),
            ("Horas diario",f'{h_logged}h' + (f' → {ph_logged:.1f} person-horas' if ph_logged != h_logged else "")),
            ("Tareas completadas",f'{task_done}/{len(tasks)}')]
    meta_html = "".join(
        f'<div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid #f0f4f8;font-size:.88rem">'
        f'<span style="min-width:160px;color:#64748b;font-weight:600">{_esc(k)}</span>'
        f'<span>{_esc(str(v))}</span></div>'
        for k,v in meta if v)

    tasks_section = ('<p style="color:#64748b">Sin tareas registradas</p>' if not tasks else
        f'<div class="tbl-wrap"><table style="font-size:.87rem"><thead><tr>'
        f'<th>Tarea</th><th>Estado</th><th>Prioridad</th><th>Vencimiento</th>'
        f'</tr></thead><tbody>{t_rows}</tbody></table></div>')
    mats_section = ('<p style="color:#64748b">Sin materiales asignados</p>' if not assignments else
        f'<div class="tbl-wrap"><table style="font-size:.87rem"><thead><tr>'
        f'<th>Material</th><th style="text-align:center">Solic.</th>'
        f'<th style="text-align:center">Asgn.</th><th style="text-align:center">Cons.</th>'
        f'<th style="text-align:center">Dev.</th><th>Estado</th><th>Ud</th>'
        f'</tr></thead><tbody>{m_rows}</tbody></table></div>')
    logs_section = ('<p style="color:#64748b">Sin entradas en el diario</p>' if not logs else
        f'<div>{log_html}</div>')

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe — {_esc(p["name"])}</title>
<style>
{_css()}
body{{display:block;background:#f0f4f8}}
.rpage{{max-width:860px;margin:0 auto;padding:32px;background:#fff;box-shadow:0 0 40px rgba(0,0,0,.08)}}
.rhead{{display:flex;justify-content:space-between;align-items:flex-start;
  margin-bottom:28px;padding-bottom:20px;border-bottom:3px solid #0f1f35}}
.rhead h1{{font-size:1.4rem;margin-bottom:4px}}
.rlogo{{font-weight:800;font-size:1rem;color:#0f1f35;text-align:right}}
.rlogo span{{display:block;font-size:.58rem;color:#64748b;letter-spacing:2px;text-transform:uppercase;margin-top:2px}}
.rsec{{margin-bottom:26px}}
.rsec h2{{font-size:.95rem;font-weight:700;color:#1a2536;margin-bottom:10px;
  padding-bottom:6px;border-bottom:1.5px solid #dce4ee;text-transform:uppercase;letter-spacing:.5px}}
@media print{{
  body{{background:#fff!important}}
  .no-print{{display:none!important}}
  .rpage{{padding:0;max-width:100%;box-shadow:none}}
  @page{{margin:1.5cm}}
}}
</style>
</head>
<body>
<div class="no-print" style="background:#0f1f35;padding:10px 20px;display:flex;align-items:center;justify-content:space-between;gap:10px">
  <a href="{BP}/projects/{pid}" style="color:#4db6ac;font-size:.88rem">← Volver al proyecto</a>
  <div style="display:flex;gap:8px">
    <a href="{BP}/projects/{pid}/report.md" download
       style="background:rgba(255,255,255,.12);color:#e2e8f0;border:none;padding:6px 14px;
              border-radius:6px;cursor:pointer;font-size:.83rem;font-weight:600;text-decoration:none">
      ⬇ Descargar MD</a>
    <button onclick="window.print()"
       style="background:#4db6ac;color:#fff;border:none;padding:6px 14px;
              border-radius:6px;cursor:pointer;font-size:.83rem;font-weight:600">
      🖨 Guardar PDF</button>
  </div>
</div>
<div class="rpage">
  <div class="rhead">
    <div>
      <h1>{_esc(p["name"])}</h1>
      <div style="color:#64748b;font-size:.9rem">{_esc(p.get("description",""))}</div>
    </div>
    <div class="rlogo">NuvoDesk<span>Nuvolink · Telecoms</span>
      <div style="font-size:.7rem;color:#94a3b8;margin-top:5px">Generado: {now_str}</div>
    </div>
  </div>
  <div class="rsec">
    <h2>Información del proyecto</h2>
    {meta_html}
  </div>
  <div class="rsec">
    <h2>Tareas ({len(tasks)})</h2>
    {tasks_section}
  </div>
  <div class="rsec">
    <h2>Materiales ({len(assignments)})</h2>
    {mats_section}
  </div>
  <div class="rsec">
    <h2>Diario de obra ({len(logs)} entradas · {h_logged}h{f" / {ph_logged:.1f} person-h" if ph_logged != h_logged else ""})</h2>
    {logs_section}
  </div>
  {'<div class="rsec"><h2>Resumen de tiempos por técnico</h2><table style="font-size:.87rem;width:100%;border-collapse:collapse"><thead><tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Técnico</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Días</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Tiempo total</th></tr></thead><tbody>' + "".join(f"<tr><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(ts['uname'])}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8'>{ts['days']}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8;font-weight:700'>{_fmt_duration(ts['total_secs'])}</td></tr>" for ts in time_summary_r) + '</tbody></table></div>' if time_summary_r else ''}
  {'<div class="rsec"><h2>Extras / Materiales fuera de scope (' + str(len(extras_r)) + ')</h2><table style="font-size:.87rem;width:100%;border-collapse:collapse"><thead><tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Descripción</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Cant.</th><th style="padding:6px 10px;border-bottom:2px solid #dce4ee">Ud</th><th style="padding:6px 10px;border-bottom:2px solid #dce4ee">Notas</th></tr></thead><tbody>' + "".join(f"<tr><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(ex['description'])}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8'>{ex['quantity']}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(ex['unit'])}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8;color:#64748b'>{_esc(ex.get('notes','') or '')}</td></tr>" for ex in extras_r) + '</tbody></table></div>' if extras_r else ''}
  {'<div class="rsec"><h2>Equipos instalados (' + str(len(equipment_r)) + ')</h2><table style="font-size:.87rem;width:100%;border-collapse:collapse"><thead><tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Marca</th><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #dce4ee">Modelo</th><th style="padding:6px 10px;border-bottom:2px solid #dce4ee">Nº Serie</th><th style="text-align:center;padding:6px 10px;border-bottom:2px solid #dce4ee">Cant.</th></tr></thead><tbody>' + "".join(f"<tr><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(eq.get('brand','') or '')}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8'>{_esc(eq['model'])}</td><td style='padding:6px 10px;border-bottom:1px solid #f0f4f8;font-family:monospace;font-size:.82rem'>{_esc(eq.get('serial_number','') or '')}</td><td style='text-align:center;padding:6px 10px;border-bottom:1px solid #f0f4f8'>{eq['quantity']}</td></tr>" for eq in equipment_r) + '</tbody></table></div>' if equipment_r else ''}
</div>
</body></html>"""

def _project_albaran(user, pid):
    p = r2d(q1("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to WHERE p.id=?""", (pid,)))
    if not p: return None
    tasks      = rs(q("SELECT * FROM tasks WHERE project_id=? ORDER BY status DESC", (pid,)))
    equipment  = rs(q("SELECT * FROM equipment_items WHERE project_id=? ORDER BY created_at", (pid,)))
    assignments= rs(q("""SELECT a.*,m.name mat_name,m.code mat_code,m.unit mat_unit
        FROM assignments a JOIN materials m ON m.id=a.material_id
        WHERE a.project_id=? AND a.qty_consumed>0 ORDER BY m.name""", (pid,)))
    time_rows  = rs(q("""SELECT u.display_name uname,
        COALESCE(SUM(CASE WHEN te.ended_at IS NOT NULL
            THEN (julianday(te.ended_at)-julianday(te.started_at))*86400 ELSE 0 END),0) total_secs
        FROM time_entries te JOIN users u ON u.id=te.user_id
        WHERE te.project_id=? AND te.ended_at IS NOT NULL GROUP BY u.id""", (pid,)))
    sig_file   = r2d(q1("""SELECT filename FROM project_files WHERE project_id=?
        AND original_name='Firma cliente' ORDER BY created_at DESC LIMIT 1""", (pid,)))
    now_str    = datetime.now().strftime("%d/%m/%Y %H:%M")
    st_label   = {"active":"Activo","paused":"Pausado","completed":"Completado","cancelled":"Cancelado"}.get(p['status'], p['status'])
    pri_label  = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(p['priority'], p['priority'])
    task_done  = sum(1 for t in tasks if t['status']=='done')
    total_h    = sum(r['total_secs'] for r in time_rows) / 3600

    task_rows = "".join(
        f"<tr><td style='padding:5px 8px;border-bottom:1px solid #eee'>"
        f"{'✅' if t['status']=='done' else ('🔴' if t['status']=='blocked' else '⬜')} {_esc(t['title'])}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #eee;color:#64748b;font-size:.82rem'>"
        f"{'Hecho' if t['status']=='done' else ('Bloqueado' if t['status']=='blocked' else 'Pendiente')}"
        f"</td></tr>" for t in tasks)

    mat_rows = "".join(
        f"<tr><td style='padding:5px 8px;border-bottom:1px solid #eee'>{_esc(a['mat_name'])}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #eee;text-align:center'>{a['qty_consumed']}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #eee'>{_esc(a['mat_unit'])}</td></tr>" for a in assignments)

    eq_rows = "".join(
        f"<tr><td style='padding:5px 8px;border-bottom:1px solid #eee'>{_esc(e.get('brand','') or '')}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #eee'>{_esc(e['model'])}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #eee;font-family:monospace;font-size:.8rem'>{_esc(e.get('serial_number','') or '')}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #eee;text-align:center'>{e['quantity']}</td></tr>" for e in equipment)

    time_rows_html = "".join(
        f"<tr><td style='padding:5px 8px;border-bottom:1px solid #eee'>{_esc(r['uname'])}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #eee;text-align:center'>{_fmt_duration(r['total_secs'])}</td></tr>" for r in time_rows)

    sig_html = ""
    if sig_file:
        sig_url = f"{BP}/api/projects/{pid}/files/{sig_file['filename']}"
        sig_html = f'<div style="margin-top:32px;padding-top:16px;border-top:2px solid #e2e8f0"><p style="color:#64748b;font-size:.82rem;margin-bottom:8px">Firma del cliente / Conforme</p><img src="{sig_url}" style="max-width:280px;border:1px solid #e2e8f0;border-radius:4px"></div>'

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Albarán — {_esc(p["name"])}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:Arial,sans-serif;font-size:13px;color:#1e293b;background:#fff;padding:28px 36px}}
h1{{font-size:1.3rem;margin-bottom:4px}}
h2{{font-size:.95rem;font-weight:700;color:#1558c2;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.04em}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;padding:5px 8px;background:#f1f5f9;font-size:.8rem}}
.hdr{{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:16px;border-bottom:2px solid #1558c2;margin-bottom:18px}}
.logo{{text-align:right;font-size:.8rem;color:#64748b}}
.logo strong{{display:block;font-size:1rem;color:#1558c2}}
.meta{{display:grid;grid-template-columns:1fr 1fr;gap:4px 24px;margin-bottom:4px}}
.meta span:nth-child(odd){{color:#64748b;font-size:.8rem}}
.meta span:nth-child(even){{font-weight:600}}
.kpi-row{{display:flex;gap:24px;margin:12px 0;padding:10px 16px;background:#f8fafc;border-radius:6px}}
.kpi{{text-align:center}}.kpi .v{{font-size:1.3rem;font-weight:700;color:#1558c2}}.kpi .l{{font-size:.72rem;color:#64748b}}
@media print{{body{{padding:12px 16px}}button{{display:none}}}}
</style></head><body>
<div style="display:flex;justify-content:flex-end;margin-bottom:12px;gap:8px">
  <button onclick="window.print()" style="background:#1558c2;color:#fff;border:none;padding:6px 14px;border-radius:5px;cursor:pointer;font-size:.82rem">🖨 Imprimir / PDF</button>
</div>
<div class="hdr">
  <div>
    <h1>{_esc(p["name"])}</h1>
    <div style="color:#64748b;font-size:.82rem;margin-top:2px">Albarán de trabajo · {now_str}</div>
    {f'<div style="margin-top:4px"><span style="background:#dcfce7;color:#15803d;border-radius:4px;padding:2px 8px;font-size:.75rem;font-weight:700">{st_label}</span></div>' if p['status'] else ''}
  </div>
  <div class="logo"><strong>Nuvolink · Telecoms</strong>NuvoDesk v3<br>Generado: {now_str}</div>
</div>
<div class="meta">
  <span>Cliente</span><span>{_esc(p.get("client","") or "—")}</span>
  <span>Referencia</span><span>{_esc(p.get("reference","") or "—")}</span>
  <span>Dirección</span><span>{_esc(p.get("address","") or "—")}</span>
  <span>Técnico</span><span>{_esc(p.get("tech","") or "—")}</span>
  <span>Contacto</span><span>{_esc(p.get("contact_name","") or "—")}{(" · " + _esc(p.get("contact_phone","") or "")) if p.get("contact_phone") else ""}</span>
  <span>Prioridad</span><span>{pri_label}</span>
  <span>Fecha inicio</span><span>{_esc((p.get("start_date") or "—")[:10])}</span>
  <span>Fecha límite</span><span>{_esc((p.get("due_date") or "—")[:10])}</span>
</div>
<div class="kpi-row">
  <div class="kpi"><div class="v">{task_done}/{len(tasks)}</div><div class="l">Tareas completadas</div></div>
  <div class="kpi"><div class="v">{round(total_h,1)}h</div><div class="l">Horas trabajadas</div></div>
  <div class="kpi"><div class="v">{len(equipment)}</div><div class="l">Equipos instalados</div></div>
</div>
{"<h2>Tareas</h2><table><thead><tr><th>Tarea</th><th>Estado</th></tr></thead><tbody>" + task_rows + "</tbody></table>" if tasks else ""}
{"<h2>Materiales consumidos</h2><table><thead><tr><th>Material</th><th style='text-align:center'>Cant.</th><th>Ud</th></tr></thead><tbody>" + mat_rows + "</tbody></table>" if mat_rows else ""}
{"<h2>Equipos instalados</h2><table><thead><tr><th>Marca</th><th>Modelo</th><th>Nº Serie</th><th style='text-align:center'>Cant.</th></tr></thead><tbody>" + eq_rows + "</tbody></table>" if equipment else ""}
{"<h2>Tiempos por técnico</h2><table><thead><tr><th>Técnico</th><th style='text-align:center'>Tiempo</th></tr></thead><tbody>" + time_rows_html + "</tbody></table>" if time_rows else ""}
{sig_html}
</body></html>"""

def _project_report_md(user, pid):
    p = r2d(q1("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to WHERE p.id=?""", (pid,)))
    if not p: return None
    tasks = rs(q("SELECT * FROM tasks WHERE project_id=? ORDER BY status,priority DESC", (pid,)))
    assignments = rs(q("""SELECT a.*,m.name mat_name,m.code mat_code,m.unit mat_unit
        FROM assignments a JOIN materials m ON m.id=a.material_id
        WHERE a.project_id=? ORDER BY m.name""", (pid,)))
    logs = rs(q("""SELECT l.*,u.display_name uname
        FROM project_logs l JOIN users u ON u.id=l.user_id
        WHERE l.project_id=? ORDER BY l.created_at""", (pid,)))
    time_summary_r = rs(q("""SELECT u.display_name uname,
        COUNT(DISTINCT date(te.started_at)) days,
        COALESCE(SUM(CASE WHEN te.ended_at IS NOT NULL
            THEN (julianday(te.ended_at)-julianday(te.started_at))*86400 ELSE 0 END),0) total_secs
        FROM time_entries te JOIN users u ON u.id=te.user_id
        WHERE te.project_id=? AND te.ended_at IS NOT NULL
        GROUP BY u.id ORDER BY total_secs DESC""", (pid,)))
    extras_r = rs(q("""SELECT we.*,u.display_name uname
        FROM wo_extras we LEFT JOIN users u ON u.id=we.added_by
        WHERE we.project_id=? ORDER BY we.created_at""", (pid,)))
    equipment_r = rs(q("""SELECT ei.*,u.display_name uname
        FROM equipment_items ei LEFT JOIN users u ON u.id=ei.added_by
        WHERE ei.project_id=? ORDER BY ei.created_at""", (pid,)))
    kit_r = rs(q("""SELECT pk.*,u.display_name uname
        FROM project_kit pk LEFT JOIN users u ON u.id=pk.added_by
        WHERE pk.project_id=? ORDER BY pk.category,pk.item_name""", (pid,)))
    ph_row = q1("SELECT COALESCE(SUM(hours),0),COALESCE(SUM(hours*technicians),0) FROM project_logs WHERE project_id=?", (pid,))
    h_logged = ph_row[0] if ph_row else 0
    ph_logged = ph_row[1] if ph_row else 0
    h_est = p.get("estimated_hours") or 0
    task_done = sum(1 for t in tasks if t['status']=='done')
    total_time_secs = sum(ts['total_secs'] for ts in time_summary_r)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    st_label = STATUS_LABEL.get(p['status'], p['status'])

    def md_table(headers, rows):
        sep = "|".join("---" for _ in headers)
        head = "| " + " | ".join(headers) + " |"
        return head + "\n|" + sep + "|\n" + "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows)

    lines = [
        f"# {p['name']}",
        f"> Informe generado: {now_str}  ",
        f"> NuvoDesk · Nuvolink Telecoms",
        "",
        "## Información del proyecto",
        "",
    ]
    meta_fields = [
        ("Cliente", p.get("client","")), ("Referencia", p.get("reference","")),
        ("Dirección", p.get("address","")), ("Técnico responsable", p.get("tech","")),
        ("Contacto obra", p.get("contact_name","")), ("Teléfono", p.get("contact_phone","")),
        ("Inicio", (p.get("start_date") or "")[:10]), ("Límite", (p.get("due_date") or "")[:10]),
        ("Estado", st_label),
        ("Horas estimadas", f"{h_est}h" if h_est else ""),
        ("Horas diario", f"{h_logged}h" + (f" → {ph_logged:.1f} person-horas" if ph_logged != h_logged else "")),
        ("Tiempo total (timer)", _fmt_duration(total_time_secs) if total_time_secs else "—"),
        ("Tareas completadas", f"{task_done}/{len(tasks)}"),
    ]
    for k, v in meta_fields:
        if v: lines.append(f"- **{k}:** {v}")
    lines += ["", "## Tareas", ""]
    if tasks:
        lines.append(md_table(["Tarea","Estado","Prioridad","Vencimiento"],
            [(t['title'], STATUS_LABEL.get(t['status'],t['status']),
              {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}.get(t['priority'],''),
              (t['due_date'] or '—')[:10]) for t in tasks]))
    else:
        lines.append("_Sin tareas registradas._")
    if time_summary_r:
        lines += ["", "## Resumen de tiempos por técnico", ""]
        lines.append(md_table(["Técnico","Días","Tiempo total"],
            [(ts['uname'], ts['days'], _fmt_duration(ts['total_secs'])) for ts in time_summary_r]))
    if assignments:
        lines += ["", "## Materiales asignados", ""]
        lines.append(md_table(["Material","Solic.","Asgn.","Cons.","Dev.","Estado","Ud"],
            [(f"[{a['mat_code']}] {a['mat_name']}", a['qty_requested'], a['qty_assigned'],
              a['qty_consumed'], a['qty_returned'], STATUS_LABEL.get(a['status'],a['status']), a['mat_unit'])
             for a in assignments]))
    if extras_r:
        lines += ["", "## Extras / Fuera de scope", ""]
        lines.append(md_table(["Descripción","Cant.","Ud","Notas"],
            [(ex['description'], ex['quantity'], ex['unit'], ex.get('notes','') or '') for ex in extras_r]))
    if equipment_r:
        lines += ["", "## Equipos instalados", ""]
        lines.append(md_table(["Marca","Modelo","Nº Serie","Cant."],
            [(eq.get('brand',''), eq['model'], eq.get('serial_number','') or '', eq['quantity']) for eq in equipment_r]))
    if kit_r:
        _KIT_CATS = {
            "sfp_10g":"SFP 10G","sfp_1g":"SFP 1G","glc":"GLC/SFP",
            "fiber_patch":"Fibra óptica","patchcord_rj45":"Patch RJ45",
            "cisco_cable":"Cable Cisco","stack_cable":"Cable STACK",
            "poe_injector":"Inyector POE","other":"Otro",
        }
        lines += ["", "## Recomendaciones de material (Kit)", ""]
        lines.append(md_table(["Categoría","Descripción","Cantidad","Estado"],
            [(_KIT_CATS.get(k['category'],'Otro'), k['item_name'],
              f"{k['quantity']} {k['unit']}",
              {"pending":"Pendiente","brought":"Llevado","not_needed":"No necesario"}.get(k['status'],''))
             for k in kit_r]))
    if logs:
        lines += ["", "## Diario de obra", ""]
        for l in logs:
            techs = int(l.get('technicians') or 1)
            ph = (l['hours'] or 0) * techs
            h_str = ""
            if l['hours']:
                h_str = f" · {l['hours']}h"
                if techs > 1: h_str += f" × {techs} téc. = **{ph:.1f} ph**"
            lines.append(f"### {l['created_at'][:16]} — {l['uname']}{h_str}")
            lines.append("")
            lines.append(l['body'])
            lines.append("")
    return "\n".join(lines)

# ── calendar ─────────────────────────────────────────────────────────────────
