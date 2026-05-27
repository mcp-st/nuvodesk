"""Login and misc pages."""
import os, json, re, mimetypes, calendar as _cal
from datetime import datetime, date as _date, timedelta
from core.db import PORT, BP, DATA_DIR, DB_PATH, FILES_DIR, q, q1, run, rs, r2d
from core.helpers import (
    _hash, _esc, _jattr, _now, _fmt_size, _fmt_duration, _parse_multipart, _stock_move,
    PROJ_COLORS, _pcolor, STATUS_LABEL, STATUS_COLOR, PRIORITY_COLOR,
    WORK_TYPES, _wt_badge, _badge, _pbadge,
)
from web.layout import _shell

def _login_page(err=""):
    err_html = f'<div class="alert alert-red">{_esc(err)}</div>' if err else ""
    return f"""<!doctype html>
<html lang="es" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NuvoDesk</title>
<link rel="stylesheet" href="{BP}/assets/styles/app.css">
<style>
body{{
  display:flex;align-items:center;justify-content:center;min-height:100dvh;
  background:var(--bg);
  background-image:radial-gradient(circle at 20% 20%,rgba(67,97,238,.1) 0%,transparent 50%),
                   radial-gradient(circle at 80% 80%,rgba(114,9,183,.08) 0%,transparent 50%)
}}
.login-wrap{{display:flex;width:min(900px,98vw);min-height:520px;border-radius:24px;overflow:hidden;box-shadow:var(--shadow-lg);border:1px solid var(--border)}}
.login-brand{{
  flex:1;
  background:radial-gradient(circle at 70% 10%,rgba(255,255,255,.10) 0%,transparent 55%),
             linear-gradient(150deg,#1e1b4b 0%,#3730a3 60%,#4f46e5 100%);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:48px;text-align:center;color:#fff;
}}
.login-brand .brand-mark{{
  width:72px;height:72px;background:rgba(255,255,255,.2);border-radius:20px;
  display:flex;align-items:center;justify-content:center;
  font-size:2.2rem;font-weight:900;margin-bottom:22px;backdrop-filter:blur(10px);
  border:1.5px solid rgba(255,255,255,.3);box-shadow:0 8px 32px rgba(0,0,0,.15)
}}
.login-brand h2{{font-size:1.9rem;font-weight:800;letter-spacing:-.4px;margin-bottom:8px}}
.login-brand p{{opacity:.92;font-size:.95rem;line-height:1.6;max-width:240px}}
.login-brand .features{{margin-top:32px;text-align:left;width:100%;max-width:260px}}
.login-brand .feat{{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:.87rem;opacity:.9}}
.login-brand .feat-dot{{width:7px;height:7px;border-radius:50%;background:rgba(255,255,255,.6);flex-shrink:0}}
.login-form-side{{
  width:min(380px,100%);background:var(--bg2);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:48px 40px
}}
.login-form-side .form-logo{{
  width:44px;height:44px;background:var(--grad);border-radius:12px;
  display:flex;align-items:center;justify-content:center;
  font-size:1.3rem;font-weight:900;color:#fff;margin-bottom:20px;
  box-shadow:0 4px 14px rgba(67,97,238,.35)
}}
.login-form-side h1{{font-size:1.5rem;font-weight:800;margin-bottom:4px;letter-spacing:-.3px;text-align:center}}
.login-form-side .sub{{color:var(--muted);font-size:.85rem;margin-bottom:32px;text-align:center}}
.login-form-side form{{width:100%}}
.login-form-side .btn{{width:100%;justify-content:center;padding:12px;font-size:.9rem;margin-top:4px}}
@media(max-width:600px){{
  .login-brand{{display:none}}
  .login-wrap{{width:95vw;min-height:auto}}
  .login-form-side{{width:100%;padding:32px 24px}}
}}
</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-brand">
    <div class="brand-mark">N</div>
    <h2>NuvoDesk</h2>
    <p>Gestión de proyectos de campo para equipos de telecomunicaciones</p>
    <div class="features">
      <div class="feat"><div class="feat-dot"></div>Seguimiento de proyectos en tiempo real</div>
      <div class="feat"><div class="feat-dot"></div>Control de tiempos y jornadas</div>
      <div class="feat"><div class="feat-dot"></div>Gestión de inventario y materiales</div>
      <div class="feat"><div class="feat-dot"></div>App móvil disponible</div>
    </div>
  </div>
  <div class="login-form-side">
    <div class="form-logo">N</div>
    <h1>Bienvenido</h1>
    <p class="sub">Accede a tu cuenta de NuvoDesk</p>
    {err_html}
    <form method="POST" action="{BP}/api/login">
      <div class="field"><label>Usuario</label>
        <input name="username" autofocus autocomplete="username" placeholder="Tu usuario"></div>
      <div class="field"><label>Contraseña</label>
        <input type="password" name="password" autocomplete="current-password" placeholder="••••••••"></div>
      <button type="submit" class="btn btn-primary">Entrar →</button>
    </form>
  </div>
</div>
</body></html>"""

# ── dashboard ─────────────────────────────────────────────────────────────────

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
