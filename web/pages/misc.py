"""Login and misc pages."""

# Brand mark SVG — D3: cloud outline (nuvo) + triple-ring LED pulse (link UP)
_BRAND_SVG = (
    '<svg viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%">'
    '<path d="M9 31C6 31 4 28.8 4 26c0-2.8 2-5 4.8-5.3C9.2 15.8 13.5 12 18.6 12c3.1 0 5.9 1.4 7.8 3.5'
    ' 1.5-1.4 3.5-2.3 5.7-2.3 4.4 0 8 3.4 8.2 7.7.1 0 .1 0 .2 0C43 21.2 46 24.2 46 28'
    ' c0 2.8-2.2 3.8-5 3.8H9z" stroke="white" stroke-width="2.5" fill="rgba(255,255,255,.07)"/>'
    '<line x1="27" y1="32" x2="27" y2="37" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>'
    '<circle cx="27" cy="44" r="10" stroke="#22c55e" stroke-width="1" fill="none" opacity=".2"/>'
    '<circle cx="27" cy="44" r="6.5" stroke="#22c55e" stroke-width="1.5" fill="none" opacity=".45"/>'
    '<circle cx="27" cy="44" r="3.5" fill="#22c55e"/>'
    '</svg>'
)

_LOGIN_CSS = """
body{display:flex;align-items:center;justify-content:center;min-height:100dvh;background:var(--bg);padding:16px;box-sizing:border-box}
.login-wrap{display:flex;width:min(900px,100%);min-height:520px;border-radius:20px;overflow:hidden;
  box-shadow:var(--shadow-lg);border:1px solid var(--border)}
.login-brand{
  flex:1;background:linear-gradient(145deg,#06101f 0%,#0c1f3d 55%,#0a2e56 100%);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:52px 44px;text-align:center;color:#fff;position:relative;overflow:hidden
}
.login-brand::before{
  content:'';position:absolute;top:-80px;right:-80px;width:280px;height:280px;border-radius:50%;
  background:radial-gradient(circle,rgba(0,150,214,.12) 0%,transparent 70%);pointer-events:none
}
.login-brand::after{
  content:'';position:absolute;bottom:-60px;left:-60px;width:200px;height:200px;border-radius:50%;
  background:radial-gradient(circle,rgba(34,197,94,.07) 0%,transparent 70%);pointer-events:none
}
.brand-mark{
  width:76px;height:76px;background:rgba(255,255,255,.07);border-radius:20px;
  display:flex;align-items:center;justify-content:center;
  margin-bottom:24px;border:1px solid rgba(255,255,255,.1);padding:12px;
  box-shadow:0 4px 20px rgba(0,0,0,.25)
}
.login-brand h2{font-size:2rem;font-weight:900;letter-spacing:-.6px;margin-bottom:4px;color:#fff}
.login-brand .tagline{
  font-size:.72rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;
  color:#00bceb;margin:0;opacity:.9
}
.login-form-side{
  width:min(380px,100%);background:var(--bg2);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:52px 44px
}
.form-logo{
  width:40px;height:40px;background:linear-gradient(135deg,#06101f,#0a2e56);
  border-radius:11px;display:flex;align-items:center;justify-content:center;
  margin-bottom:18px;padding:7px;box-shadow:0 2px 8px rgba(6,16,31,.35)
}
.login-form-side h1{font-size:1.5rem;font-weight:800;margin-bottom:4px;letter-spacing:-.3px;text-align:center;color:var(--text)}
.login-form-side .sub{color:var(--muted);font-size:.85rem;margin-bottom:28px;text-align:center}
.login-form-side form{width:100%}
.login-form-side .field{margin-bottom:14px}
.login-form-side .field label{display:block;font-size:.8rem;font-weight:600;color:var(--text);margin-bottom:6px}
.login-form-side .field input{width:100%;box-sizing:border-box}
.login-form-side .btn-primary{width:100%;justify-content:center;margin-top:6px}
@media(max-width:640px){
  .login-brand{display:none}
  .login-wrap{min-height:auto;border-radius:16px;width:100%}
  .login-form-side{width:100%;padding:40px 28px}
}
"""
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
<style>{_LOGIN_CSS}</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-brand">
    <div class="brand-mark">{_BRAND_SVG}</div>
    <h2>NuvoDesk</h2>
    <p class="tagline">by Nuvolink</p>
  </div>
  <div class="login-form-side">
    <div class="form-logo">{_BRAND_SVG}</div>
    <h1>Bienvenido</h1>
    <p class="sub">Accede a tu cuenta de NuvoDesk</p>
    {err_html}
    <form method="POST" action="{BP}/api/login">
      <div class="field">
        <label>Usuario</label>
        <input name="username" autofocus autocomplete="username">
      </div>
      <div class="field">
        <label>Contraseña</label>
        <input type="password" name="password" autocomplete="current-password">
      </div>
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
    return _shell("download", user, content, title="Descargas")


def _set_password_page(token, err=""):
    err_html = f'<div class="alert alert-red">{_esc(err)}</div>' if err else ""
    return f"""<!doctype html>
<html lang="es" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NuvoDesk — Activar cuenta</title>
<link rel="stylesheet" href="{BP}/assets/styles/app.css">
<style>{_LOGIN_CSS}</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-brand">
    <div class="brand-mark">{_BRAND_SVG}</div>
    <h2>NuvoDesk</h2>
    <p class="tagline">by Nuvolink</p>
  </div>
  <div class="login-form-side">
    <div class="form-logo">{_BRAND_SVG}</div>
    <h1>Activar cuenta</h1>
    <p class="sub">Crea tu contraseña de acceso</p>
    {err_html}
    <div id="success-msg" class="alert" style="display:none;background:var(--green-dim,#f0fdf4);color:var(--green,#166534)">
      Contraseña establecida. <a href="{BP}/login" style="font-weight:700">Ir al login →</a>
    </div>
    <form id="set-pw-form" style="width:100%">
      <input type="hidden" id="sp-token" value="{_esc(token)}">
      <div class="field">
        <label>Nueva contraseña</label>
        <input type="password" id="sp-pw" autocomplete="new-password" required minlength="6">
      </div>
      <div class="field">
        <label>Repetir contraseña</label>
        <input type="password" id="sp-pw2" autocomplete="new-password" required>
      </div>
      <button type="submit" class="btn btn-primary" id="sp-btn">Activar cuenta →</button>
    </form>
  </div>
</div>
<script>
document.getElementById('set-pw-form').onsubmit=function(e){{
  e.preventDefault();
  var pw=document.getElementById('sp-pw').value;
  var pw2=document.getElementById('sp-pw2').value;
  if(pw!==pw2){{alert('Las contraseñas no coinciden.');return;}}
  var token=document.getElementById('sp-token').value;
  document.getElementById('sp-btn').disabled=true;
  fetch('{BP}/api/set-password',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{token:token,password:pw}})}})
  .then(function(r){{return r.json().then(function(j){{return{{ok:r.ok,j:j}};}})}})
  .then(function(x){{
    if(x.ok){{
      document.getElementById('set-pw-form').style.display='none';
      document.getElementById('success-msg').style.display='block';
    }} else {{
      alert(x.j.error||'Error al establecer la contraseña.');
      document.getElementById('sp-btn').disabled=false;
    }}
  }});
}};
</script>
</body></html>"""


# ── HTTP handler ──────────────────────────────────────────────────────────────
