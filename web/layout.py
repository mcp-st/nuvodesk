"""Shell layout and navigation for NuvoDesk."""
import json
from core.db import BP, q1, r2d
from core.helpers import _esc

_NAV_ICONS = {
    "dashboard":  '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "projects":   '<svg class="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="12" y2="17"/></svg>',
    "workload":   '<svg class="icon" viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    "calendar":   '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    "inventory":  '<svg class="icon" viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27,6.96 12,12.01 20.73,6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
    "kit":        '<svg class="icon" viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    "users":      '<svg class="icon" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "download":   '<svg class="icon" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2z"/><path d="M12 8v8"/><path d="m8 12 4 4 4-4"/></svg>',
}

def _shell(page, user, content, extra_head=""):
    bp = BP
    nav = [
        ("dashboard", f"{bp}/",          "Dashboard"),
        ("projects",  f"{bp}/projects",  "Proyectos"),
        ("workload",  f"{bp}/workload",  "Cargas"),
        ("calendar",  f"{bp}/calendar",  "Calendario"),
        ("inventory", f"{bp}/inventory", "Inventario"),
        ("kit",       f"{bp}/kit",       "Kit campo"),
        ("users",     f"{bp}/users",     "Usuarios"),
        ("download",  f"{bp}/download",  "App móvil"),
    ]
    sidebar_links = ""
    bottom_links = ""
    for key, url, label in nav:
        if key == "users" and user.get("role") != "admin":
            continue
        active = ' active' if page == key else ""
        aria   = ' aria-current="page"' if page == key else ""
        ic     = _NAV_ICONS.get(key, "")
        sidebar_links += (
            f'<a href="{url}" class="nav-item{active}"{aria}>'
            f'<span class="nav-item-icon" aria-hidden="true">{ic}</span>'
            f'<span class="nav-item-label">{label}</span>'
            f'</a>\n'
        )
        bottom_links += (
            f'<a href="{url}" class="{active.strip()}"{aria}>'
            f'<span class="nav-item-icon" aria-hidden="true">{ic}</span>'
            f'<span>{label}</span>'
            f'</a>\n'
        )

    role_lbl = {"admin":"Admin","technician":"Técnico","backoffice":"Backoffice"}.get(
        user.get("role",""), user.get("role",""))
    initial  = _esc((user.get("display_name","?") or "?")[0].upper())
    uname    = _esc(user.get("display_name",""))

    # Active timer indicator
    active_te = r2d(q1("""SELECT te.id, te.started_at, te.project_id,
        p.name pname FROM time_entries te
        JOIN projects p ON p.id=te.project_id
        WHERE te.user_id=? AND te.ended_at IS NULL
        LIMIT 1""", (user.get("id"),))) if user.get("id") else None

    if active_te:
        started_iso = (active_te.get("started_at") or "").replace(" ", "T")
        pname_esc   = _esc((active_te.get("pname") or "")[:28])
        te_pid      = active_te.get("project_id", 0)
        timer_widget = f"""
<div class="sidebar-timer" id="sidebar-timer">
  <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
    <span class="timer-pulse"></span>
    <span style="font-size:.7rem;font-weight:700;color:var(--green,#15803d);text-transform:uppercase;letter-spacing:.05em">Jornada activa</span>
  </div>
  <div style="font-size:.78rem;font-weight:600;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="{pname_esc}">{pname_esc}</div>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
    <span id="st-elapsed" style="font-size:.85rem;font-weight:700;font-variant-numeric:tabular-nums;color:var(--green,#15803d)">—</span>
    <button onclick="stopTimerGlobal({te_pid})" class="btn btn-sm" style="padding:2px 8px;font-size:.72rem;background:var(--red,#dc2626);color:#fff;border:none;border-radius:4px;cursor:pointer">⏹ Parar</button>
  </div>
</div>
<script>
(function(){{
  var start=new Date("{started_iso}");
  function tick(){{
    var el=document.getElementById('st-elapsed');
    if(!el) return;
    var diff=Math.floor((Date.now()-start.getTime())/1000);
    var h=Math.floor(diff/3600),m=Math.floor((diff%3600)/60),s=diff%60;
    el.textContent=(h>0?h+'h ':'')+String(m).padStart(2,'0')+'m '+String(s).padStart(2,'0')+'s';
  }}
  tick(); setInterval(tick,1000);
}})();
function stopTimerGlobal(pid){{
  var btn=document.querySelector('#sidebar-timer button');
  if(btn){{ btn.disabled=true; btn.textContent='Parando…'; }}
  fetch(bp+'/api/projects/'+pid+'/time/stop',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}})
    .then(function(){{ location.reload(); }})
    .catch(function(){{ if(btn){{ btn.disabled=false; btn.textContent='⏹ Parar'; }} }});
}}
</script>"""
    else:
        timer_widget = ""

    return f"""<!doctype html>
<html lang="es" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="NuvoDesk">
<meta name="theme-color" content="#4361ee">
<link rel="manifest" href="{bp}/manifest.webmanifest">
<link rel="stylesheet" href="{bp}/assets/styles/app.css">
<title>NuvoDesk</title>
{extra_head}
</head>
<body>
<script>
(function(){{
  var t=localStorage.getItem('nd_theme')||'light';
  document.documentElement.setAttribute('data-theme',t);
}})();
</script>
<div class="sidebar-overlay" id="sidebarOverlay"></div>
<button class="hamburger" id="hamburger" onclick="toggleSidebar()" aria-label="Abrir menú">
  <svg class="icon" viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
</button>
<div class="app-shell">
  <aside class="sidebar" id="sidebar" role="navigation" aria-label="Navegación principal">
    <a href="{bp}/" class="sidebar-logo">
      <div class="logo-mark" aria-hidden="true">N</div>
      <div class="logo-text">
        <div class="logo-name">NuvoDesk</div>
        <div class="logo-sub">Nuvolink · Telecoms</div>
      </div>
    </a>
    <div class="sidebar-search">
      <div class="search-wrap">
        <span class="search-icon" aria-hidden="true">
          <svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        </span>
        <input id="search-inp" class="search-input" type="search"
               placeholder="Buscar proyectos, tareas..." autocomplete="off" aria-label="Buscar">
      </div>
      <div id="search-results" class="search-drop"></div>
    </div>
    <div class="nav-scroll">
      <div class="nav-section">
        <div class="nav-label">Principal</div>
        {sidebar_links}
      </div>
    </div>
    {timer_widget}
    <div class="sidebar-footer">
      <button class="theme-toggle" id="themeToggle" onclick="toggleTheme()" aria-label="Cambiar tema">
        <span class="nav-item-icon" aria-hidden="true">
          <svg class="icon" id="themeIcon" viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/></svg>
        </span>
        <span class="nav-item-label theme-label">Modo oscuro</span>
      </button>
      <div class="user-row">
        <div class="user-avatar">{initial}</div>
        <div class="user-info">
          <div class="user-name">{uname}</div>
          <div class="user-role">{role_lbl}</div>
        </div>
        <a href="{bp}/logout" class="logout-btn" aria-label="Cerrar sesión">
          <svg class="icon" viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16,17 21,12 16,7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        </a>
      </div>
    </div>
  </aside>
  <div class="workspace">
    <div class="main-content" id="main">{content}</div>
  </div>
</div>
<nav id="bottom-nav" aria-label="Navegación móvil">{bottom_links}</nav>
<script>
var bp={json.dumps(BP)};
function _applyThemeIcon(t){{
  var ic=document.getElementById('themeIcon');
  var lbl=document.querySelector('.theme-label');
  if(!ic) return;
  if(t==='dark'){{
    ic.innerHTML='<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
    if(lbl) lbl.textContent='Modo claro';
  }} else {{
    ic.innerHTML='<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/>';
    if(lbl) lbl.textContent='Modo oscuro';
  }}
}}
(function(){{
  var t=localStorage.getItem('nd_theme')||'light';
  _applyThemeIcon(t);
}})();
function toggleTheme(){{
  var cur=document.documentElement.getAttribute('data-theme')||'light';
  var next=cur==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',next);
  localStorage.setItem('nd_theme',next);
  _applyThemeIcon(next);
}}
function toggleSidebar(){{
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebarOverlay').classList.toggle('visible');
}}
function closeSidebar(){{
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('visible');
}}
document.getElementById('sidebarOverlay').addEventListener('click',closeSidebar);
document.querySelectorAll('.sidebar .nav-item').forEach(function(a){{
  a.addEventListener('click',function(){{if(window.innerWidth<=767) closeSidebar();}});
}});
var _st=null;
var _si=document.getElementById('search-inp');
if(_si) _si.addEventListener('input',function(){{
  clearTimeout(_st);
  var q=this.value.trim();
  var drop=document.getElementById('search-results');
  if(q.length<2){{drop.classList.remove('open');return;}}
  _st=setTimeout(function(){{
    fetch(bp+'/api/search?q='+encodeURIComponent(q))
      .then(function(r){{return r.json();}})
      .then(function(d){{_renderSearch(d);}});
  }},250);
}});
function _renderSearch(results){{
  var el=document.getElementById('search-results');
  if(!results.length){{
    el.innerHTML='<div class="search-item" style="color:#94a3b8;cursor:default">Sin resultados</div>';
    el.classList.add('open');return;
  }}
  el.innerHTML=results.map(function(r){{
    var url=bp+(r.type==='proyecto'?'/projects/'+r.id:
                r.type==='tarea'?'/projects/'+r.pid:'/inventory');
    var t=(r.title||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
    var s=(r.sub||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
    return '<a class="search-item" href="'+url+'">'
      +'<div class="search-item-type">'+r.type+'</div>'
      +'<div class="search-item-title">'+t+'</div>'
      +(s?'<div class="search-item-sub">'+s+'</div>':'')
      +'</a>';
  }}).join('');
  el.classList.add('open');
}}
document.addEventListener('click',function(e){{
  if(!e.target.closest('.sidebar-search'))
    document.getElementById('search-results').classList.remove('open');
}});
</script>
</body>
</html>"""

# ── login ─────────────────────────────────────────────────────────────────────
