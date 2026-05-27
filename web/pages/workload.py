"""Workload page."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
)
from web.layout import _shell

def _workload_page(user, week_str=""):
    today = _date.today()
    if week_str:
        try:
            ref = _date.fromisoformat(week_str)
        except ValueError:
            ref = today
    else:
        ref = today
    # Monday of the selected week
    mon = ref - timedelta(days=ref.weekday())
    days = [mon + timedelta(days=i) for i in range(7)]
    prev_mon = str(mon - timedelta(days=7))
    next_mon = str(mon + timedelta(days=7))
    dow_names = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]

    techs = rs(q("SELECT id,display_name FROM users WHERE active=1 AND role IN ('technician','admin','backoffice') ORDER BY display_name"))
    if not techs:
        techs = rs(q("SELECT id,display_name FROM users WHERE active=1 ORDER BY display_name"))

    day_strs = [str(d) for d in days]
    entries = rs(q(f"""SELECT te.user_id, date(te.started_at) entry_date,
        p.id pid, p.name pname, p.work_type,
        SUM(CASE WHEN te.ended_at IS NOT NULL
            THEN (julianday(te.ended_at)-julianday(te.started_at))*3600 ELSE 0 END) total_h
        FROM time_entries te JOIN projects p ON p.id=te.project_id
        WHERE date(te.started_at) >= ? AND date(te.started_at) <= ?
        GROUP BY te.user_id, date(te.started_at), p.id
        ORDER BY te.user_id, entry_date""",
        (day_strs[0], day_strs[6])))

    by_user_day: dict = {}
    for e in entries:
        key = (e['user_id'], e['entry_date'])
        by_user_day.setdefault(key, []).append(e)

    # header row
    hd_html = '<div class="wl-name wl-hd" style="font-size:.7rem">Técnico</div>'
    for i, d in enumerate(days):
        is_today = d == today
        style = "background:#dbeafe;color:#1d4ed8" if is_today else ""
        hd_html += f'<div class="wl-hd" style="{style}">{dow_names[i]}<br><span style="font-weight:400">{d.day}/{d.month}</span></div>'

    grid_cols = "160px " + " ".join(["1fr"]*7)
    rows_html = ""
    for tech in techs:
        row = f'<div class="wl-name">{_esc(tech["display_name"])}</div>'
        for d in days:
            is_today = d == today
            day_entries = by_user_day.get((tech['id'], str(d)), [])
            cell_content = ""
            for e in day_entries:
                wt = e.get('work_type') or 'proyecto'
                wt_info = WORK_TYPES.get(wt, WORK_TYPES['proyecto'])
                c = wt_info['color']
                h = int(e['total_h'] // 60) if e['total_h'] else 0
                m = int(e['total_h'] % 60) if e['total_h'] else 0
                dur = f"{h}h{m:02d}m" if e['total_h'] else "—"
                pname = e['pname']
                cell_content += (f'<a href="{BP}/projects/{e["pid"]}" '
                    f'class="wl-entry" style="background:{c}" '
                    f'title="{_esc(pname)}">{_esc(pname[:16])} {dur}</a>')
            today_cls = " wl-today" if is_today else ""
            row += f'<div class="wl-cell{today_cls}">{cell_content}</div>'
        rows_html += row

    week_label = f"{days[0].day}/{days[0].month} – {days[6].day}/{days[6].month}/{days[6].year}"
    content = f"""
<div class="toolbar">
  <h1>📊 Cargas de trabajo</h1>
</div>
<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap">
  <a href="{BP}/workload?week={prev_mon}" class="btn btn-ghost btn-sm">← Semana anterior</a>
  <span class="fw7" style="min-width:180px;text-align:center">{week_label}</span>
  <a href="{BP}/workload?week={next_mon}" class="btn btn-ghost btn-sm">Semana siguiente →</a>
  <a href="{BP}/workload" class="btn btn-ghost btn-sm">Hoy</a>
</div>
<div class="card" style="padding:0;overflow:hidden">
  <div class="wl-wrap">
    <div class="wl-grid" style="grid-template-columns:{grid_cols}">
      {hd_html}
      {rows_html}
    </div>
  </div>
</div>
<p class="muted" style="font-size:.78rem;margin-top:8px">
  Muestra jornadas registradas (temporizador) por técnico y día. Sin registros = celda vacía.
</p>"""
    return _shell("workload", user, content)

# ── download page ─────────────────────────────────────────────────────────────
def _download_page(user):
    bp = BP
    apk_size = ""
    apk_path = os.path.join(os.path.dirname(__file__), "data/files/nuvodesk.apk")
    if os.path.exists(apk_path):
        apk_size = f" ({_fmt_size(os.path.getsize(apk_path))})"

    content = f"""
<div class="page-hd">
  <h1>📲 Descargar App</h1>
  <p class="muted">Instala NuvoDesk en tu dispositivo móvil</p>
</div>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;max-width:900px">

  <!-- Android -->
  <div class="card" style="border-top:4px solid #3ddc84">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="font-size:2.5rem">🤖</div>
      <div>
        <div style="font-weight:700;font-size:1.15rem">Android</div>
        <div class="muted" style="font-size:.82rem">Versión 1.0 · mínimo Android 7.0</div>
      </div>
    </div>
    <p style="font-size:.88rem;color:var(--fg);margin-bottom:16px">
      Aplicación nativa WebView que carga NuvoDesk directamente.
      Las sesiones y cookies se mantienen entre aperturas.
    </p>
    <a href="{bp}/data/files/nuvodesk.apk" class="btn btn-primary"
       style="display:inline-flex;gap:8px;text-decoration:none;margin-bottom:12px">
      ⬇ Descargar APK{apk_size}
    </a>
    <div style="background:#f8fafc;border-radius:8px;padding:14px;font-size:.82rem;color:var(--muted)">
      <strong style="color:var(--fg);display:block;margin-bottom:6px">📋 Instrucciones de instalación</strong>
      <ol style="margin:0;padding-left:18px;line-height:1.8">
        <li>Descarga el archivo APK</li>
        <li>En Ajustes → Seguridad → activa <em>«Fuentes desconocidas»</em></li>
        <li>Abre el APK descargado y pulsa Instalar</li>
        <li>La app aparecerá en tu pantalla de inicio</li>
      </ol>
    </div>
  </div>

  <!-- iOS / PWA -->
  <div class="card" style="border-top:4px solid #007aff">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="font-size:2.5rem">🍎</div>
      <div>
        <div style="font-weight:700;font-size:1.15rem">iPhone / iPad</div>
        <div class="muted" style="font-size:.82rem">PWA · iOS 16.4+ recomendado</div>
      </div>
    </div>
    <p style="font-size:.88rem;color:var(--fg);margin-bottom:16px">
      En iOS no se pueden distribuir APK. Usa la función
      <strong>«Añadir a pantalla de inicio»</strong> de Safari para
      instalarla como app nativa (PWA).
    </p>
    <div style="background:#f0f7ff;border-radius:8px;padding:14px;font-size:.82rem;color:var(--fg)">
      <strong style="display:block;margin-bottom:8px">📋 Instalar en iPhone / iPad</strong>
      <ol style="margin:0;padding-left:18px;line-height:2">
        <li>Abre <strong>Safari</strong> y ve a <code>dev.nupro.es/nuvodesk</code></li>
        <li>Pulsa el icono de compartir <strong>⬆</strong> (barra inferior)</li>
        <li>Selecciona <strong>«Añadir a pantalla de inicio»</strong></li>
        <li>Confirma el nombre y pulsa <strong>Añadir</strong></li>
      </ol>
      <div style="margin-top:10px;padding:8px;background:#fff3cd;border-radius:6px;font-size:.78rem">
        ⚠️ Usa siempre Safari — otros navegadores no permiten instalar PWA en iOS
      </div>
    </div>
  </div>

  <!-- Android PWA -->
  <div class="card" style="border-top:4px solid #4285f4">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="font-size:2.5rem">🌐</div>
      <div>
        <div style="font-weight:700;font-size:1.15rem">PWA (todos los dispositivos)</div>
        <div class="muted" style="font-size:.82rem">Sin instalación · siempre actualizado</div>
      </div>
    </div>
    <p style="font-size:.88rem;color:var(--fg);margin-bottom:16px">
      Usa NuvoDesk desde el navegador como si fuera una app.
      Chrome en Android muestra automáticamente el banner de instalación.
    </p>
    <div style="background:#f8fafc;border-radius:8px;padding:14px;font-size:.82rem;color:var(--muted)">
      <strong style="color:var(--fg);display:block;margin-bottom:6px">📋 Instalar en Android (Chrome)</strong>
      <ol style="margin:0;padding-left:18px;line-height:1.8">
        <li>Abre Chrome y visita NuvoDesk</li>
        <li>Pulsa el menú <strong>⋮</strong> (tres puntos)</li>
        <li>Selecciona <strong>«Añadir a pantalla de inicio»</strong></li>
        <li>La app quedará instalada sin descargar nada</li>
      </ol>
    </div>
  </div>

</div>

<div class="card" style="max-width:900px;margin-top:4px;background:#f0fff4;border:1px solid #86efac">
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-size:1.4rem">✅</span>
    <div style="font-size:.85rem">
      <strong>Versión actual:</strong> NuvoDesk 1.0 · APK debug build ·
      La sesión se comparte con el navegador (mismas cookies HTTPS).
    </div>
  </div>
</div>
"""
    return _shell("download", user, content)


# ── HTTP handler ──────────────────────────────────────────────────────────────
