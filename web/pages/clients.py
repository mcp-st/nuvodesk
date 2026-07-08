"""Histórico de clientes."""
import json
from core.db import BP, q, q1, rs, r2d
from core.helpers import _esc, _badge2, _pbadge, _kpi_card, _empty_state, _fmt_duration
from web.layout import _shell


def _clients_page(user):
    clients = rs(q("""
        SELECT p.client,
               COUNT(p.id)                                              total_projects,
               SUM(CASE WHEN p.status='active'    THEN 1 ELSE 0 END)   n_active,
               SUM(CASE WHEN p.status='completed' THEN 1 ELSE 0 END)   n_done,
               SUM(CASE WHEN p.status='cancelled' THEN 1 ELSE 0 END)   n_cancel,
               COALESCE(SUM(pl.hours),0)                                total_hours,
               MAX(p.updated_at)                                        last_activity,
               SUM(CASE WHEN p.priority='urgent'  THEN 1 ELSE 0 END)   n_urgent
        FROM projects p
        LEFT JOIN project_logs pl ON pl.project_id=p.id
        GROUP BY p.client
        ORDER BY MAX(p.updated_at) DESC"""))

    if not clients:
        return _shell("clients", user,
            _empty_state("👤", "Sin clientes", "Los clientes aparecen automáticamente al crear proyectos."),
            title="Clientes")

    rows = ""
    for c in clients:
        h = round(float(c['total_hours'] or 0), 1)
        last = (c['last_activity'] or '')[:10]
        active_badge = (f'<span class="badge badge-ok">{c["n_active"]} activo{"s" if c["n_active"]!=1 else ""}</span>'
                        if c['n_active'] else '<span class="muted">—</span>')
        rows += (
            f'<tr>'
            f'<td class="fw7"><a href="{BP}/clients/{_esc(c["client"])}" style="color:var(--text)">'
            f'{_esc(c["client"])}</a></td>'
            f'<td style="text-align:center">{c["total_projects"]}</td>'
            f'<td>{active_badge}</td>'
            f'<td class="muted" style="text-align:center">{c["n_done"]}</td>'
            f'<td class="muted">{h}h</td>'
            f'<td class="muted col-m-hide">{last}</td>'
            f'<td><a href="{BP}/clients/{_esc(c["client"])}" class="btn btn-ghost btn-sm">→</a></td>'
            f'</tr>'
        )

    content = f"""
<div class="toolbar"><h1>👤 Clientes</h1></div>
<div class="card">
  <div class="tbl-wrap">
    <table><thead><tr>
      <th>Cliente</th><th style="text-align:center">Proyectos</th>
      <th>Activos</th><th style="text-align:center">Completados</th>
      <th>Horas</th><th class="col-m-hide">Última actividad</th><th></th>
    </tr></thead><tbody>{rows}</tbody></table>
  </div>
</div>"""
    return _shell("clients", user, content, title="Clientes")


def _client_detail(user, client_name):
    projects = rs(q("""SELECT p.*,u.display_name tech FROM projects p
        LEFT JOIN users u ON u.id=p.assigned_to
        WHERE p.client=? ORDER BY p.updated_at DESC""", (client_name,)))
    if not projects:
        return None

    total_h_r = q1("""SELECT COALESCE(SUM(pl.hours),0) FROM project_logs pl
        JOIN projects p ON p.id=pl.project_id WHERE p.client=?""", (client_name,))
    total_h = round(float(total_h_r[0] or 0), 1)

    avg_res = q1("""SELECT AVG(julianday(completed_date)-julianday(created_at))*24
        FROM projects WHERE client=? AND status='completed' AND completed_date!=''""",
                 (client_name,))
    avg_h = round(float(avg_res[0] or 0), 1) if avg_res and avg_res[0] else None

    wtype_dist = rs(q("""SELECT work_type, COUNT(*) n FROM projects
        WHERE client=? GROUP BY work_type ORDER BY n DESC""", (client_name,)))

    n_active = sum(1 for p in projects if p['status'] == 'active')
    n_done   = sum(1 for p in projects if p['status'] == 'completed')

    kpis = (
        '<div class="nd-kpi-strip" style="margin-bottom:20px">'
        + _kpi_card(len(projects), "Proyectos", "brand", "📁")
        + _kpi_card(n_active, "Activos", "warn", "🔄")
        + _kpi_card(n_done, "Completados", "ok", "✅")
        + _kpi_card(f"{total_h}h", "Horas invertidas", "info", "⏱")
        + '</div>'
    )

    type_pills = " ".join(
        f'<span class="chip">{_esc(r["work_type"] or "proyecto")} × {r["n"]}</span>'
        for r in wtype_dist)

    proj_rows = "".join(
        f'<tr><td><a href="{BP}/projects/{p["id"]}" class="fw7">{_esc(p["name"])}</a></td>'
        f'<td>{_badge2(p["status"])}</td>'
        f'<td>{_pbadge(p["priority"])}</td>'
        f'<td class="muted">{_esc(p["tech"] or "—")}</td>'
        f'<td class="muted col-m-hide">{_esc((p["due_date"] or "—")[:10])}</td>'
        f'<td class="muted col-m-hide">{_esc((p["updated_at"] or "")[:10])}</td>'
        f'<td><a href="{BP}/projects/{p["id"]}" class="btn btn-ghost btn-icon">→</a></td></tr>'
        for p in projects)

    content = f"""
<div class="toolbar">
  <div>
    <h1>👤 {_esc(client_name)}</h1>
    {"<p class='muted' style='font-size:.85rem;margin-top:2px'>Resolución media: <strong>"+str(avg_h)+"h</strong></p>" if avg_h else ""}
  </div>
  <a href="{BP}/clients" class="btn btn-ghost btn-sm">← Clientes</a>
</div>
{kpis}
{"<div style='margin-bottom:16px;display:flex;gap:6px;flex-wrap:wrap'>"+type_pills+"</div>" if type_pills else ""}
<div class="card">
  <h2 style="margin-bottom:12px">Historial de proyectos ({len(projects)})</h2>
  <div class="tbl-wrap">
    <table><thead><tr>
      <th>Proyecto</th><th>Estado</th><th>Prioridad</th><th>Técnico</th>
      <th class="col-m-hide">Límite</th><th class="col-m-hide">Actualizado</th><th></th>
    </tr></thead><tbody>{proj_rows}</tbody></table>
  </div>
</div>"""

    return _shell("clients", user, content, title=client_name)
