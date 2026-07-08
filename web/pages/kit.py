"""Kit técnico — vista global del maletín de obra por proyecto."""
import json
from core.db import BP, q, q1, rs
from core.helpers import _esc, _badge2, _kpi_card, _empty_state
from web.layout import _shell

def _kit_page(user):
    _KIT_CATS = {
        "sfp_10g":("SFP 10G","rc-sfp10g"), "sfp_1g":("SFP 1G","rc-sfp1g"),
        "glc":("GLC/SFP","rc-glc"), "fiber_patch":("Fibra óptica","rc-fiber"),
        "patchcord_rj45":("Patch RJ45","rc-patchrj45"), "cisco_cable":("Cable Cisco","rc-cisco"),
        "stack_cable":("Cable STACK","rc-stack"), "poe_injector":("Inyector POE","rc-poe"),
        "other":("Otro","rc-other"),
    }
    _KIT_ST = {
        "pending":    ("⏳ Pendiente",  "rec-status-pending"),
        "brought":    ("✅ Llevado",    "rec-status-brought"),
        "not_needed": ("— No necesario","rec-status-not_needed"),
    }

    projects_with_kit = rs(q("""
        SELECT p.id,p.name,p.client,p.status,
            COUNT(pk.id) total_items,
            SUM(CASE WHEN pk.status='pending' THEN 1 ELSE 0 END) pending_items
        FROM projects p JOIN project_kit pk ON pk.project_id=p.id
        GROUP BY p.id
        ORDER BY CASE p.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                 SUM(CASE WHEN pk.status='pending' THEN 1 ELSE 0 END) DESC"""))

    total_recs   = q1("SELECT COUNT(*) FROM project_kit")[0]
    pending_recs = q1("SELECT COUNT(*) FROM project_kit WHERE status='pending'")[0]
    brought_recs = q1("SELECT COUNT(*) FROM project_kit WHERE status='brought'")[0]

    proj_cards_html = ""
    for proj in projects_with_kit:
        recs = rs(q("""SELECT pk.*,u.display_name uname
            FROM project_kit pk LEFT JOIN users u ON u.id=pk.added_by
            WHERE pk.project_id=? ORDER BY pk.status='pending' DESC, pk.created_at DESC""", (proj['id'],)))

        items_html = ""
        for kr in recs:
            cat_lbl, cat_cls = _KIT_CATS.get(kr.get("category","other"), ("Otro","rc-other"))
            st_lbl, st_cls   = _KIT_ST.get(kr.get("status","pending"), ("⏳ Pendiente","rec-status-pending"))
            notes_txt = f' · {_esc(kr["notes"])}' if kr.get("notes") else ""
            qty_unit  = f'{_esc(str(kr["quantity"]))} {_esc(kr["unit"])}'
            krid      = kr["id"]
            if kr.get("status","pending") == "pending":
                actions = (f'<button class="btn btn-ghost btn-icon" title="Marcar como llevado" '
                    f'onclick="kitSetStatus({krid},\'brought\')">✅</button>'
                    f'<button class="btn btn-ghost btn-icon" title="No necesario" '
                    f'onclick="kitSetStatus({krid},\'not_needed\')">✗</button>')
            else:
                actions = (f'<button class="btn btn-ghost btn-icon" title="Volver a pendiente" '
                    f'onclick="kitSetStatus({krid},\'pending\')">↩</button>')
            items_html += (
                f'<div class="rec-item">'
                f'<div style="padding-top:3px"><span class="rec-cat {cat_cls}">{cat_lbl}</span></div>'
                f'<div class="ri-main">'
                f'<div class="ri-name">{_esc(kr["item_name"])}</div>'
                f'<div class="ri-meta">{qty_unit}{notes_txt}</div>'
                f'</div>'
                f'<div class="ri-actions">'
                f'<span class="{st_cls}">{st_lbl}</span>'
                f'{actions}'
                f'<button class="btn btn-danger btn-icon" onclick="delKitRec({krid})">✕</button>'
                f'</div></div>')

        if proj["pending_items"]:
            pending_badge = (f'<span class="badge badge-warn">'
                f'{proj["pending_items"]} pendiente{"s" if proj["pending_items"]!=1 else ""}</span>')
        else:
            pending_badge = '<span class="badge badge-ok">✓ Listo</span>'

        proj_cards_html += f"""<div class="rec-proj-card">
  <h3>
    <a href="{BP}/projects/{proj['id']}" style="color:inherit;text-decoration:none">{_esc(proj['name'])}</a>
    <span class="proj-badge">{_esc(proj['client'])}</span>
    {_badge2(proj['status'])}
    {pending_badge}
    <span style="margin-left:auto;font-size:.72rem;color:var(--muted);font-weight:400">{proj['total_items']} items</span>
  </h3>
  {items_html}
</div>"""

    if not proj_cards_html:
        proj_cards_html = _empty_state(
            "🧰",
            "Sin items en el maletín",
            'Abre un proyecto activo, ve a la pestaña <strong>Recursos → Maletín de obra</strong> y añade los items que el equipo de campo debería llevar.'
        )

    content = f"""
<div class="toolbar">
  <h1>🧰 Maletín de obra</h1>
</div>
<p class="muted" style="font-size:.87rem;margin-bottom:20px;line-height:1.6">
  Vista global del material preparado por proyecto.
  El equipo de campo marca cada ítem como <em>llevado</em> o <em>no necesario</em>.
</p>

<div class="nd-kpi-strip" style="margin-bottom:24px">
  {_kpi_card(total_recs,   "Items totales",  "brand", "🧰")}
  {_kpi_card(pending_recs, "Pendientes",      "warn",  "⏳")}
  {_kpi_card(brought_recs, "Llevados",        "ok",    "✅")}
</div>

{proj_cards_html}

<script>
var bp={json.dumps(BP)};
function kitSetStatus(id,status){{
  fetch(bp+'/api/project_kit/'+id,{{method:'PATCH',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{status:status}})}})
    .then(function(r){{if(r.ok)location.reload();}});
}}
function delKitRec(id){{
  ConfirmDialog.show('¿Eliminar este item del maletín?','')
    .then(function(ok){{
      if(!ok)return;
      fetch(bp+'/api/project_kit/'+id,{{method:'DELETE'}})
        .then(function(r){{if(r.ok)location.reload();}});
    }});
}}
</script>"""
    return _shell("kit", user, content, title="Kit técnico")
