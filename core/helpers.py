"""Pure utility functions and constants for NuvoDesk."""
import hashlib, json, re, mimetypes, os
from datetime import datetime
from core.db import run


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _esc(s) -> str:
    if s is None: return ""
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def _jattr(obj) -> str:
    return json.dumps(obj).replace('"', '&quot;')

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def _fmt_size(b):
    if b < 1024: return f"{b} B"
    if b < 1048576: return f"{b//1024} KB"
    return f"{b/1048576:.1f} MB"

def _fmt_duration(secs):
    if not secs or secs < 0: return "0h 00m"
    return f"{int(secs//3600)}h {int((secs%3600)//60):02d}m"

def _parse_multipart(h):
    ct   = h.headers.get('Content-Type','')
    cl   = int(h.headers.get('Content-Length',0))
    body = h.rfile.read(cl)
    boundary = ''
    for part in ct.split(';'):
        s = part.strip()
        if s.startswith('boundary='):
            boundary = s[9:].strip('"')
    if not boundary:
        return {}, {}
    delim = ('--' + boundary).encode()
    fields, files = {}, {}
    for raw in body.split(delim)[1:]:
        if raw.strip() in (b'--', b'--\r\n', b''):
            continue
        if b'\r\n\r\n' in raw:
            hdr_raw, content = raw.split(b'\r\n\r\n', 1)
        elif b'\n\n' in raw:
            hdr_raw, content = raw.split(b'\n\n', 1)
        else:
            continue
        if content.endswith(b'\r\n'):
            content = content[:-2]
        name, fname, mime_part = '', None, ''
        for line in hdr_raw.decode('utf-8','replace').splitlines():
            if ':' not in line:
                continue
            k, _, v = line.partition(':')
            k = k.strip().lower()
            if k == 'content-disposition':
                for item in v.split(';'):
                    item = item.strip()
                    if item.startswith('name='):
                        name = item[5:].strip('"')
                    elif item.startswith('filename='):
                        fname = item[9:].strip('"')
            elif k == 'content-type':
                mime_part = v.strip()
        if fname is not None:
            files[name] = {'filename': fname, 'data': content, 'mime': mime_part}
        else:
            try:
                fields[name] = content.decode('utf-8')
            except Exception:
                fields[name] = ''
    return fields, files

def _stock_move(material_id, qty, direction, source, ref_id, user_id, notes=""):
    run("INSERT INTO stock_movements (material_id,qty,direction,source,ref_id,user_id,notes) VALUES (?,?,?,?,?,?,?)",
        (material_id, qty, direction, source, ref_id, user_id, notes))

PROJ_COLORS = ["#2563eb","#16a34a","#d97706","#dc2626","#7c3aed","#0d9488",
               "#db2777","#ea580c","#65a30d","#0284c7"]
def _pcolor(pid): return PROJ_COLORS[int(pid) % len(PROJ_COLORS)]

STATUS_LABEL = {
    "active":"Activo","paused":"Pausado","completed":"Completado","cancelled":"Cancelado",
    "pending":"Pendiente","in_progress":"En curso","done":"Hecho","blocked":"Bloqueado",
    "requested":"Solicitado","assigned":"Asignado","consumed":"Consumido",
    "returned":"Devuelto","partial":"Parcial"
}
STATUS_COLOR = {
    "active":"#15803d","paused":"#b45309","completed":"#1558c2","cancelled":"#6b7280",
    "pending":"#64748b","in_progress":"#1558c2","done":"#15803d","blocked":"#dc2626",
    "requested":"#b45309","assigned":"#1558c2","consumed":"#15803d",
    "returned":"#6d28d9","partial":"#b45309"
}
PRIORITY_COLOR = {"low":"#64748b","normal":"#1558c2","high":"#b45309","urgent":"#dc2626"}

WORK_TYPES = {
    'averia':        {'name': 'Avería',        'color': '#dc2626', 'icon': '⚡'},
    'instalacion':   {'name': 'Instalación',   'color': '#2563eb', 'icon': '🔧'},
    'mantenimiento': {'name': 'Mantenimiento', 'color': '#d97706', 'icon': '🔨'},
    'inspeccion':    {'name': 'Inspección',    'color': '#7c3aed', 'icon': '🔍'},
    'proyecto':      {'name': 'Proyecto',      'color': '#0d9488', 'icon': '📋'},
}

def _wt_badge(wt):
    info = WORK_TYPES.get(wt or 'proyecto', WORK_TYPES['proyecto'])
    c = info['color']
    return f'<span class="badge" style="background:{c}22;color:{c}">{info["icon"]} {info["name"]}</span>'

def _badge(status, text=None):
    t = text or STATUS_LABEL.get(status, status)
    c = STATUS_COLOR.get(status, "#64748b")
    return f'<span class="badge" style="background:{c}22;color:{c}">{_esc(t)}</span>'

def _pbadge(priority):
    labels = {"low":"Baja","normal":"Normal","high":"Alta","urgent":"Urgente"}
    t = labels.get(priority, priority)
    c = PRIORITY_COLOR.get(priority, "#64748b")
    return f'<span style="color:{c};font-size:.78rem;font-weight:600">▲ {t}</span>'
