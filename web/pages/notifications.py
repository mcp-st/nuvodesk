"""Notifications page."""
from core.db import BP, q, run, rs
from core.helpers import _esc
from web.layout import _shell


def _notifications_page(user):
    uid = user["id"]
    notifs = rs(q(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
        (uid,)
    ))
    unread = sum(1 for n in notifs if not n["read"])

    # Mark all as read on page load
    run("UPDATE notifications SET read=1 WHERE user_id=? AND read=0", (uid,))

    bp = BP

    if not notifs:
        body = f"""
<div style="max-width:640px;margin:0 auto;padding:32px 16px">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:24px">
    <h1 style="font-size:1.3rem;font-weight:700;margin:0">Notificaciones</h1>
  </div>
  <div style="text-align:center;padding:64px 0;color:var(--muted)">
    <svg style="width:48px;height:48px;stroke:var(--muted);fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;margin-bottom:16px" viewBox="0 0 24 24">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
      <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>
    <div style="font-size:.95rem">Sin notificaciones</div>
  </div>
</div>"""
        return _shell("notifications", user, body)

    unread_badge = (
        f'<span style="background:var(--red,#dc2626);color:#fff;border-radius:9999px;'
        f'font-size:.7rem;font-weight:700;padding:2px 8px;margin-left:8px">{unread}</span>'
        if unread else ""
    )

    rows = ""
    for n in notifs:
        was_unread = not n["read"]  # captured before bulk mark-read above
        # Re-check from original list
        was_unread = not n["read"]
        bg = "background:color-mix(in srgb,var(--primary) 6%,transparent);border-left:3px solid var(--primary)" if was_unread else "border-left:3px solid transparent"
        title = _esc(n["title"] or "")
        body_txt = _esc(n["body"] or "")
        ts = (n["created_at"] or "")[:16].replace("T", " ")
        href = _esc(n["url"] or "#")
        nid = n["id"]

        rows += f"""
<div style="display:flex;align-items:flex-start;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border);{bg}">
  <div style="flex:1;min-width:0">
    <div style="font-size:.875rem;font-weight:{'700' if was_unread else '500'};color:var(--text);margin-bottom:2px">{title}</div>
    <div style="font-size:.8rem;color:var(--muted);margin-bottom:4px">{body_txt}</div>
    <div style="font-size:.7rem;color:var(--muted)">{ts}</div>
  </div>
  <div style="display:flex;gap:6px;flex-shrink:0;align-items:center">
    {'<a href="' + href + '" style="font-size:.75rem;color:var(--primary);text-decoration:none;white-space:nowrap;padding:4px 8px;border:1px solid var(--primary);border-radius:6px">Ver</a>' if href != '#' else ''}
    <button onclick="deleteNotif({nid},this)" style="background:none;border:none;cursor:pointer;color:var(--muted);padding:4px;border-radius:4px;line-height:1;font-size:1rem" title="Eliminar">
      <svg style="width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
  </div>
</div>"""

    content = f"""
<div style="max-width:640px;margin:0 auto;padding:32px 16px">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;gap:12px">
    <h1 style="font-size:1.3rem;font-weight:700;margin:0">Notificaciones{unread_badge}</h1>
    <button onclick="deleteAll()" style="font-size:.8rem;color:var(--muted);background:none;border:1px solid var(--border);border-radius:6px;padding:6px 12px;cursor:pointer">
      Eliminar todas
    </button>
  </div>
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:12px;overflow:hidden">
    {rows}
  </div>
</div>
<script>
var bp={repr(bp)};
function deleteNotif(id,btn){{
  fetch(bp+'/api/notifications/'+id,{{method:'DELETE'}})
    .then(function(r){{if(r.ok) btn.closest('[style*="border-bottom"]').remove();}});
}}
function deleteAll(){{
  ConfirmDialog.show('¿Eliminar todas las notificaciones?','')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/notifications',{{method:'DELETE'}})
        .then(function(r){{if(r.ok) location.reload();}});
    }});
}}
</script>"""

    return _shell("notifications", user, content, title="Notificaciones")
