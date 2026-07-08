"""Shell layout and navigation for NuvoDesk."""
import json
from core.db import BP
from core.helpers import _esc

# D3 brand mark: cloud outline (nuvo) + triple-ring LED pulse (link UP)
_LOGO_SVG = (
    '<svg viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg" '
    'style="width:100%;height:100%;display:block">'
    '<path d="M9 31C6 31 4 28.8 4 26c0-2.8 2-5 4.8-5.3C9.2 15.8 13.5 12 18.6 12'
    'c3.1 0 5.9 1.4 7.8 3.5 1.5-1.4 3.5-2.3 5.7-2.3 4.4 0 8 3.4 8.2 7.7'
    '.1 0 .1 0 .2 0C43 21.2 46 24.2 46 28c0 2.8-2.2 3.8-5 3.8H9z"'
    ' stroke="white" stroke-width="2.5" fill="rgba(255,255,255,.07)"/>'
    '<line x1="27" y1="32" x2="27" y2="37" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>'
    '<circle cx="27" cy="44" r="10" stroke="#22c55e" stroke-width="1" fill="none" opacity=".2"/>'
    '<circle cx="27" cy="44" r="6.5" stroke="#22c55e" stroke-width="1.5" fill="none" opacity=".45"/>'
    '<circle cx="27" cy="44" r="3.5" fill="#22c55e"/>'
    '</svg>'
)

_NAV_ICONS = {
    "dashboard":     '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "projects":      '<svg class="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="12" y2="17"/></svg>',
    "calendar":      '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    "inventory":     '<svg class="icon" viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27,6.96 12,12.01 20.73,6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
    "kit":           '<svg class="icon" viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    "field":         '<svg class="icon" viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/><circle cx="5" cy="19" r="2" fill="currentColor"/></svg>',
    "clients":       '<svg class="icon" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><polyline points="23,21 23,19 19,19" stroke-width="2"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "profitability": '<svg class="icon" viewBox="0 0 24 24"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
    "users":         '<svg class="icon" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "map":           '<svg class="icon" viewBox="0 0 24 24"><polygon points="1,6 1,22 8,18 16,22 23,18 23,2 16,6 8,2"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>',
    "download":      '<svg class="icon" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2z"/><path d="M12 8v8"/><path d="m8 12 4 4 4-4"/></svg>',
    "settings":      '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
}

# Sidebar 3 grupos — cada grupo: (label, [keys], admin_only)
_NAV_GROUPS = [
    ("Trabajo",  ["dashboard", "projects", "calendar", "map"],    False),
    ("Recursos", ["inventory", "kit", "clients"],                 False),
    ("Admin",    ["profitability", "users", "settings"],          True),
]

_NAV_URLS = {
    "dashboard":     "/",
    "projects":      "/projects",
    "field":         "/field",
    "calendar":      "/calendar",
    "inventory":     "/inventory",
    "kit":           "/kit",
    "clients":       "/clients",
    "map":           "/map",
    "profitability": "/profitability",
    "users":         "/users",
    "settings":      "/settings",
    "download":      "/download",
}
_NAV_LABELS = {
    "dashboard":     "Dashboard",      "projects":      "Proyectos",
    "field":         "Modo campo",     "calendar":      "Calendario",
    "inventory":     "Inventario",     "kit":           "Kit campo",
    "clients":       "Clientes",       "map":           "Mapa",
    "profitability": "Rentabilidad",   "users":         "Usuarios",
    "settings":      "Configuración",  "download":      "App móvil",
}
_BOTTOM_NAV_KEYS = {"dashboard", "projects", "calendar", "inventory"}

# ── Nuevos componentes JS (strings literales — no f-strings) ─────────────────

_NEW_COMPONENTS_JS = r"""
/* ── Toast v2 (máx 4) ── */
var Toast=(function(){
  var MAX=4;
  var IC={success:'✅',warning:'⚠️',danger:'❌',info:'ℹ️',ok:'✅',err:'❌',warn:'⚠️'};
  function show(msg,type,dur){
    var c=document.getElementById('nd-toasts');
    if(!c)return;
    type=type||'info'; dur=dur||3000;
    if(c.children.length>=MAX) c.firstElementChild.remove();
    var t=document.createElement('div');
    t.className='nd-toast nd-toast-'+type;
    t.innerHTML='<span class="nd-ti">'+(IC[type]||'ℹ️')+'</span>'
      +'<span class="nd-tm">'+msg+'</span>'
      +'<button class="nd-tc" onclick="this.closest(\'.nd-toast\').remove()">×</button>';
    c.appendChild(t);
    requestAnimationFrame(function(){requestAnimationFrame(function(){t.classList.add('visible');});});
    setTimeout(function(){
      t.classList.remove('visible');
      setTimeout(function(){if(t.parentNode)t.remove();},280);
    },dur);
  }
  return {show:show};
})();

/* ── Modal singleton con focus trap WCAG 2.1.2 ── */
var Modal=(function(){
  var _cur=null,_prev=null;
  var SEL='a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  function _trap(el){
    var items=Array.from(el.querySelectorAll(SEL));
    if(items.length) items[0].focus();
    function _tab(e){
      if(e.key!=='Tab') return;
      var f=document.activeElement,fi=items[0],la=items[items.length-1];
      if(e.shiftKey){if(f===fi){e.preventDefault();la.focus();}}
      else{if(f===la){e.preventDefault();fi.focus();}}
    }
    el.addEventListener('keydown',_tab);
    el._ndtc=function(){el.removeEventListener('keydown',_tab);};
  }
  function open(id){
    var b=document.getElementById(id);
    if(!b) return;
    _prev=document.activeElement;
    _cur=id;
    b.classList.add('open');
    var m=b.querySelector('.nd-modal,.modal');
    if(m) setTimeout(function(){_trap(m);},50);
  }
  function close(id){
    var b=document.getElementById(id||_cur);
    if(!b) return;
    b.classList.remove('open');
    var m=b.querySelector('.nd-modal,.modal');
    if(m&&m._ndtc){m._ndtc();delete m._ndtc;}
    if(_prev){try{_prev.focus();}catch(e){}_prev=null;}
    var cid=id||_cur;
    if(_cur===cid) _cur=null;
    b.dispatchEvent(new CustomEvent('nd-modal-closed',{bubbles:true}));
  }
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&_cur) close(_cur);});
  document.addEventListener('click',function(e){
    if(e.target.classList&&(e.target.classList.contains('nd-modal-bg')||e.target.classList.contains('modal-bg')))
      close(e.target.id);
  });
  return {open:open,close:close};
})();

/* ── ConfirmDialog — ESC resuelve Promise(false) [C3] ── */
var ConfirmDialog=(function(){
  var _res=null;
  function _get(id){return document.getElementById(id);}
  var bg=_get('nd-confirm'),msg=_get('nd-confirm-msg'),ttl=_get('nd-confirm-title');
  var ok=_get('nd-confirm-ok'),cancel=_get('nd-confirm-cancel'),x=_get('nd-confirm-x');
  function cleanup(v){Modal.close('nd-confirm');if(_res){_res(v);_res=null;}}
  if(ok) ok.onclick=function(){cleanup(true);};
  if(cancel) cancel.onclick=function(){cleanup(false);};
  if(x) x.onclick=function(){cleanup(false);};
  if(bg) bg.addEventListener('nd-modal-closed',function(){if(_res){_res(false);_res=null;}});
  function show(message,title,okCls){
    if(!bg) return Promise.resolve(false);
    if(msg) msg.textContent=message||'¿Confirmar esta acción?';
    if(ttl) ttl.textContent=title||'¿Confirmar?';
    if(ok) ok.className='btn '+(okCls||'btn-danger')+' btn-sm';
    Modal.open('nd-confirm');
    return new Promise(function(res){_res=res;});
  }
  return {show:show};
})();

/* ── Overflow menu con flip detection [R4] ── */
function ndOverflow(btn){
  var w=btn.closest('.nd-ovfl-wrap');
  if(!w) return;
  var d=w.querySelector('.nd-ovfl-drop');
  var wasOpen=d.classList.contains('open');
  document.querySelectorAll('.nd-ovfl-drop.open').forEach(function(el){
    el.classList.remove('open','flip-left','flip-up');
  });
  if(!wasOpen){
    d.classList.add('open');
    requestAnimationFrame(function(){
      var r=d.getBoundingClientRect();
      if(r.right>window.innerWidth-8) d.classList.add('flip-left');
      if(r.bottom>window.innerHeight-8) d.classList.add('flip-up');
    });
  }
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.nd-ovfl-wrap'))
    document.querySelectorAll('.nd-ovfl-drop.open').forEach(function(el){
      el.classList.remove('open','flip-left','flip-up');
    });
});

/* ── Ctrl+K → foco al buscador ── */
document.addEventListener('keydown',function(e){
  if((e.metaKey||e.ctrlKey)&&e.key==='k'){
    e.preventDefault();
    var si=document.getElementById('search-inp');
    if(si){si.focus();si.select();}
  }
});
"""


def _shell(page, user, content, extra_head="", title=""):
    bp = BP
    is_admin = user.get("role") == "admin"

    # Construir sidebar en 3 grupos
    sidebar_links = ""
    bottom_links  = ""
    for group_label, keys, admin_only in _NAV_GROUPS:
        if admin_only and not is_admin:
            continue
        items_html = ""
        for key in keys:
            if key in ("users", "settings") and not is_admin:
                continue
            url    = bp + _NAV_URLS.get(key, "/")
            label  = _NAV_LABELS.get(key, key)
            ic     = _NAV_ICONS.get(key, "")
            active = " active" if page == key else ""
            aria   = ' aria-current="page"' if page == key else ""
            items_html += (
                f'<a href="{url}" class="nav-item{active}"{aria}>'
                f'<span class="nav-item-icon" aria-hidden="true">{ic}</span>'
                f'<span class="nav-item-label">{label}</span>'
                f'</a>\n'
            )
            if key in _BOTTOM_NAV_KEYS:
                bottom_links += (
                    f'<a href="{url}" class="{active.strip()}"{aria}>'
                    f'<span class="nav-item-icon" aria-hidden="true">{ic}</span>'
                    f'<span>{label}</span>'
                    f'</a>\n'
                )
        sidebar_links += (
            f'<div class="nav-group-lbl">{group_label}</div>'
            f'{items_html}'
        )

    role_lbl = {"admin":"Admin","technician":"Técnico","backoffice":"Backoffice"}.get(
        user.get("role",""), user.get("role",""))
    initial  = _esc((user.get("display_name","?") or "?")[0].upper())
    uname    = _esc(user.get("display_name",""))
    page_title = f"NuvoDesk — {title}" if title else "NuvoDesk"

    return f"""<!doctype html>
<html lang="es" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="NuvoDesk">
<meta name="theme-color" content="#2563eb">
<link rel="manifest" href="{bp}/manifest.webmanifest">
<link rel="stylesheet" href="{bp}/assets/styles/app.css">
<title>{_esc(page_title)}</title>
{extra_head}
</head>
<body>
<script>
(function(){{
  var t=localStorage.getItem('nd_theme')||'light';
  document.documentElement.setAttribute('data-theme',t);
}})();
</script>

<!-- Toast container -->
<div id="nd-toasts"></div>

<!-- ConfirmDialog (en shell — disponible en todas las páginas) -->
<div class="nd-modal-bg" id="nd-confirm" role="dialog" aria-modal="true" aria-labelledby="nd-confirm-title">
  <div class="nd-modal">
    <div class="nd-modal-hd">
      <span class="nd-modal-title" id="nd-confirm-title">¿Confirmar?</span>
      <button class="nd-modal-x" id="nd-confirm-x" aria-label="Cerrar">×</button>
    </div>
    <div class="nd-modal-body" id="nd-confirm-msg"></div>
    <div class="nd-modal-ft">
      <button class="btn btn-ghost btn-sm" id="nd-confirm-cancel">Cancelar</button>
      <button class="btn btn-danger btn-sm" id="nd-confirm-ok">Confirmar</button>
    </div>
  </div>
</div>

<div class="sidebar-overlay" id="sidebarOverlay"></div>
<button class="hamburger" id="hamburger" onclick="toggleSidebar()" aria-label="Abrir menú">
  <svg class="icon" viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
</button>
<div class="app-shell">
  <aside class="sidebar" id="sidebar" role="navigation" aria-label="Navegación principal">
    <a href="{bp}/" class="sidebar-logo">
      <div class="logo-mark" aria-hidden="true">{_LOGO_SVG}</div>
      <div class="logo-text">
        <div class="logo-name">NuvoDesk</div>
        <div class="logo-sub">by Nuvolink</div>
      </div>
    </a>
    <div class="sidebar-search">
      <div class="search-wrap">
        <span class="search-icon" aria-hidden="true">
          <svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        </span>
        <input id="search-inp" class="search-input" type="search"
               placeholder="Buscar… (Ctrl+K)" autocomplete="off" aria-label="Buscar">
      </div>
      <div id="search-results" class="search-drop"></div>
    </div>
    <div class="nav-scroll">
      <div class="nav-section">
        {sidebar_links}
      </div>
    </div>
    <div class="sidebar-footer">
      <div class="notif-wrapper" id="notifWrapper">
        <a href="{bp}/notifications" class="notif-btn{' active' if page == 'notifications' else ''}" aria-label="Notificaciones" style="display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;color:var(--{'text' if page != 'notifications' else 'primary'});border-radius:6px;position:relative;text-decoration:none">
          <span style="position:relative;display:inline-flex">
            <svg class="icon" viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            <span id="notif-badge" style="display:none;position:absolute;top:-4px;right:-4px;background:var(--red,#dc2626);color:#fff;border-radius:50%;font-size:.6rem;width:16px;height:16px;align-items:center;justify-content:center;font-weight:700"></span>
          </span>
          <span class="nav-item-label">Notificaciones</span>
        </a>
        <div class="notif-hover-panel" id="notifHoverPanel">
          <div style="padding:8px 12px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border)">
            <span style="font-size:.8rem;font-weight:600">Notificaciones</span>
            <a href="{bp}/notifications" style="font-size:.75rem;color:var(--primary);text-decoration:none">Ver todas</a>
          </div>
          <div id="notif-list" style="padding:4px 0"></div>
        </div>
      </div>
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

/* ── Tema ── */
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

/* ── Sidebar ── */
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

/* ── Búsqueda ── */
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

/* ── Notificaciones ── */
var _notifLoaded=false;
function _loadNotifHover(){{
  if(_notifLoaded) return;
  _notifLoaded=true;
  fetch(bp+'/api/notifications')
    .then(function(r){{return r.json();}})
    .then(function(d){{
      var badge=document.getElementById('notif-badge');
      if(d.unread>0){{badge.style.display='flex';badge.textContent=d.unread>9?'9+':d.unread;}}
      else badge.style.display='none';
      var list=document.getElementById('notif-list');
      if(!d.notifications.length){{
        list.innerHTML='<div style="padding:16px;text-align:center;font-size:.82rem;color:var(--muted)">Sin notificaciones</div>';
        return;
      }}
      list.innerHTML=d.notifications.slice(0,6).map(function(n){{
        var bg=n.read?'':'background:color-mix(in srgb,var(--primary) 8%,transparent)';
        var t=(n.title||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
        var b2=(n.body||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
        return '<a href="'+(n.url||bp+'/notifications')+'" '
          +'style="display:block;padding:10px 14px;border-bottom:1px solid var(--border);text-decoration:none;color:var(--text);'+bg+'">'
          +'<div style="font-size:.8rem;font-weight:600">'+t+'</div>'
          +'<div style="font-size:.75rem;color:var(--muted)">'+b2+'</div>'
          +'<div style="font-size:.7rem;color:var(--muted);margin-top:2px">'+n.created_at.slice(0,16)+'</div>'
          +'</a>';
      }}).join('');
    }}).catch(function(){{}});
}}
var _nw=document.getElementById('notifWrapper');
if(_nw) _nw.addEventListener('mouseenter',_loadNotifHover);
fetch(bp+'/api/notifications')
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if(d.unread>0){{
      var b=document.getElementById('notif-badge');
      b.style.display='flex'; b.textContent=d.unread>9?'9+':d.unread;
    }}
  }}).catch(function(){{}});
</script>

<!-- Componentes DS v2: Toast, Modal, ConfirmDialog, Overflow, Ctrl+K -->
<script>{_NEW_COMPONENTS_JS}</script>
</body>
</html>"""

# ── login ─────────────────────────────────────────────────────────────────────
