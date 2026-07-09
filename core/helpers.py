"""Pure utility functions and constants for NuvoDesk."""
import hashlib, hmac, json, re, mimetypes, os, base64
from datetime import datetime
from core.db import run

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

def _hash(pw: str) -> str:
    """Hash a password with scrypt + random salt. Returns base64-encoded salt||key."""
    salt = os.urandom(16)
    key = hashlib.scrypt(pw.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return base64.b64encode(salt + key).decode()

def _check_pw(pw: str, stored: str) -> bool:
    """Verify password against stored hash (scrypt or legacy SHA-256 hex)."""
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored):
        # legacy SHA-256 — accept but caller should upgrade
        return hmac.compare_digest(hashlib.sha256(pw.encode()).hexdigest(), stored)
    try:
        raw = base64.b64decode(stored)
        salt, key = raw[:16], raw[16:]
        new_key = hashlib.scrypt(pw.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
        return hmac.compare_digest(key, new_key)
    except Exception:
        return False

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

def _fd(d):
    """Format ISO date YYYY-MM-DD → DD-MM-YYYY for display. Returns '—' if empty."""
    if not d or len(d) < 10:
        return d or '—'
    return f"{d[8:10]}-{d[5:7]}-{d[:4]}"

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

def _stock_move(material_id, qty, direction, source, ref_id, user_id, notes="", location_id=None):
    run("INSERT INTO stock_movements (material_id,qty,direction,source,ref_id,user_id,notes,location_id) VALUES (?,?,?,?,?,?,?,?)",
        (material_id, qty, direction, source, ref_id, user_id, notes, location_id))

PROJ_COLORS = ["#2563eb","#16a34a","#d97706","#dc2626","#7c3aed","#0d9488",
               "#db2777","#ea580c","#65a30d","#0284c7"]
def _pcolor(pid): return PROJ_COLORS[int(pid) % len(PROJ_COLORS)]

STATUS_LABEL = {
    "active":"Activo","paused":"Pausado","completed":"Completado","cancelled":"Cancelado",
    "pending_approval":"Pend. firma","quoted":"Presupuestado",
    "pending":"Pendiente","in_progress":"En curso","done":"Hecho","blocked":"Bloqueado",
    "requested":"Solicitado","assigned":"Asignado","consumed":"Consumido",
    "returned":"Devuelto","partial":"Parcial"
}
STATUS_COLOR = {
    "active":"#15803d","paused":"#b45309","completed":"#78716c","cancelled":"#a8a29e",
    "quoted":"#7c3aed",
    "pending":"#78716c","in_progress":"#0f172a","done":"#15803d","blocked":"#dc2626",
    "requested":"#b45309","assigned":"#0f172a","consumed":"#15803d",
    "returned":"#78716c","partial":"#b45309"
}
PRIORITY_COLOR = {"low":"#a8a29e","normal":"#78716c","high":"#b45309","urgent":"#dc2626"}

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

# ── DS v2 helpers ─────────────────────────────────────────────────────────────

_BADGE2_MAP = {
    "active":           "badge-ok",   "done":      "badge-ok",   "consumed": "badge-ok",
    "completed":        "badge-ok",
    "in_progress":      "badge-info", "assigned":  "badge-info", "requested":"badge-info",
    "pending_approval": "badge-info", "quoted":    "badge-info",
    "paused":           "badge-warn", "partial":   "badge-warn",
    "blocked":          "badge-err",  "cancelled": "badge-err",
    "pending":          "badge-warn", "returned":  "badge-warn",
}

def _badge2(status, text=None):
    """Semantic badge using DS v2 tokens."""
    t   = text or STATUS_LABEL.get(status, status)
    cls = _BADGE2_MAP.get(status, "badge-warn")
    return f'<span class="badge {cls}">{_esc(t)}</span>'

def _kpi_card(value, label, variant="brand", icon="", trend=""):
    """KPI card v2 — icono + valor + label + trend."""
    return (
        f'<div class="nd-kpi">'
        f'<div class="nd-kpi-icon {variant}">{icon}</div>'
        f'<div>'
        f'<div class="nd-kpi-val {variant}">{_esc(str(value))}</div>'
        f'<div class="nd-kpi-lbl">{_esc(label)}</div>'
        + (f'<div class="nd-kpi-trend">{_esc(trend)}</div>' if trend else '')
        + '</div></div>'
    )

def _empty_state(icon, title, sub=""):
    return (
        f'<div class="nd-empty">'
        f'<div class="nd-empty-icon">{icon}</div>'
        f'<div class="nd-empty-title">{_esc(title)}</div>'
        + (f'<div class="nd-empty-sub">{_esc(sub)}</div>' if sub else '')
        + '</div>'
    )

# ── SLA helpers ───────────────────────────────────────────────────────────────

_SLA_HOURS = {
    "averia": 4, "instalacion": 72, "mantenimiento": 48,
    "inspeccion": 8, "proyecto": 0,
}

def _sla_status(p):
    """Returns dict(pct, elapsed_h, sla_h, variant) or None if SLA not applicable."""
    if p.get('status') in ('completed', 'cancelled', 'pending_approval', 'quoted'):
        return None
    sla_h = float(p.get('sla_hours') or 0) or _SLA_HOURS.get(p.get('work_type', 'proyecto'), 0)
    if not sla_h:
        return None
    try:
        created = datetime.strptime((p.get('created_at') or '')[:16], '%Y-%m-%d %H:%M')
        elapsed_h = (datetime.now() - created).total_seconds() / 3600
    except Exception:
        return None
    pct = min(elapsed_h / sla_h * 100, 250)
    variant = 'ok' if pct < 70 else ('warn' if pct < 100 else 'err')
    return {'pct': round(pct, 1), 'elapsed_h': round(elapsed_h, 1), 'sla_h': sla_h, 'variant': variant}

def _sla_badge(p):
    """Inline SLA badge for cards/tables."""
    s = _sla_status(p)
    if not s:
        return ''
    icon = '🟢' if s['variant'] == 'ok' else ('🟡' if s['variant'] == 'warn' else '🔴')
    label = f"SLA {s['elapsed_h']:.0f}/{s['sla_h']:.0f}h"
    color = {'ok': 'var(--s-ok)', 'warn': 'var(--s-warn)', 'err': 'var(--s-err)'}[s['variant']]
    return f'<span style="font-size:.72rem;color:{color};font-weight:600" title="SLA: {s["elapsed_h"]}h de {s["sla_h"]}h">{icon} {label}</span>'

def _triage_item(count, label, sub, variant, filter_url):
    """Triage rail item — clicable (C1), cuenta deduplicada por caller (R1)."""
    return (
        f'<a class="nd-triage-item {variant}" href="{_esc(filter_url)}">'
        f'<span class="nd-triage-arr">→</span>'
        f'<div class="nd-triage-count">{count}</div>'
        f'<div class="nd-triage-lbl">{_esc(label)}</div>'
        f'<div class="nd-triage-sub">{_esc(sub)}</div>'
        f'</a>'
    )
