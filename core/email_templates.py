"""HTML email templates for NuvoDesk."""

_FONT = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_PRIORITY_LABEL = {"urgent": "Urgente", "high": "Alta", "normal": "Normal", "low": "Baja"}
_PRIORITY_COLOR  = {"urgent": "#dc2626", "high": "#ea580c", "normal": "#2563eb", "low": "#64748b"}
_STATUS_LABEL = {"active": "Activo", "paused": "Pausado", "completed": "Completado", "cancelled": "Cancelado"}


def _base(title: str, preheader: str, body_html: str, footer_extra: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;{_FONT}">
<!-- preheader hidden -->
<div style="display:none;max-height:0;overflow:hidden;color:#f1f5f9">{preheader}&nbsp;&#8203;&nbsp;&#8203;</div>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f1f5f9">
<tr><td align="center" style="padding:32px 16px">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">

  <!-- HEADER -->
  <tr><td style="background:#0f172a;padding:22px 32px;border-radius:12px 12px 0 0">
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td>
          <span style="color:#fff;font-size:1.15rem;font-weight:800;letter-spacing:-.3px">NuvoDesk</span>
          <span style="color:#64748b;font-size:.7rem;font-weight:600;text-transform:uppercase;
            letter-spacing:1.5px;margin-left:10px;vertical-align:middle">by Nuvolink</span>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- BODY -->
  <tr><td style="background:#ffffff;padding:36px 32px 28px">
    {body_html}
  </td></tr>

  <!-- FOOTER -->
  <tr><td style="background:#f8fafc;padding:18px 32px;border-radius:0 0 12px 12px;
    border-top:1px solid #e2e8f0;text-align:center">
    <p style="margin:0;font-size:.72rem;color:#94a3b8;line-height:1.6">
      NuvoDesk · Nuvolink Telecomunicaciones<br>
      Este mensaje es generado automáticamente, no respondas a este correo.
      {footer_extra}
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _btn(label: str, url: str, color: str = "#0f172a") -> str:
    return (f'<a href="{url}" style="display:inline-block;background:{color};color:#fff;'
            f'text-decoration:none;padding:13px 28px;border-radius:8px;font-size:.9rem;'
            f'font-weight:700;letter-spacing:.1px;margin-top:8px">{label}</a>')


def _kv_row(label: str, value: str) -> str:
    return (f'<tr>'
            f'<td style="padding:7px 0;font-size:.8rem;color:#64748b;width:130px;vertical-align:top">{label}</td>'
            f'<td style="padding:7px 0;font-size:.85rem;color:#0f172a;font-weight:600;vertical-align:top">{value}</td>'
            f'</tr>')


def _pill(text: str, color: str) -> str:
    return (f'<span style="display:inline-block;background:{color}18;color:{color};'
            f'border-radius:999px;padding:2px 10px;font-size:.72rem;font-weight:700">{text}</span>')


# ── individual templates ───────────────────────────────────────────────────────

def tpl_welcome(display_name: str, username: str, set_pw_url: str) -> tuple[str, str]:
    """Returns (subject, html)."""
    subject = "Bienvenido/a a NuvoDesk — activa tu cuenta"
    body = f"""
    <h2 style="margin:0 0 6px;font-size:1.4rem;font-weight:800;color:#0f172a">
      Bienvenido/a, {display_name} 👋
    </h2>
    <p style="margin:0 0 24px;font-size:.9rem;color:#475569;line-height:1.65">
      Tu cuenta en NuvoDesk ha sido creada. Para acceder necesitas establecer tu contraseña.
    </p>
    <table cellpadding="0" cellspacing="0" border="0" style="background:#f8fafc;border:1px solid #e2e8f0;
      border-radius:8px;padding:16px 20px;margin-bottom:28px;width:100%">
      {_kv_row("Usuario", username)}
    </table>
    <p style="margin:0 0 6px;font-size:.85rem;color:#475569">
      Haz clic en el botón para crear tu contraseña. El enlace caduca en <strong>48 horas</strong>.
    </p>
    {_btn("Activar mi cuenta", set_pw_url, "#0f172a")}
    <p style="margin:20px 0 0;font-size:.78rem;color:#94a3b8">
      Si no esperabas este correo, puedes ignorarlo.
    </p>"""
    return subject, _base("Bienvenido a NuvoDesk", f"Activa tu cuenta como {username}", body)


def tpl_project_assigned(tech_name: str, project: dict, project_url: str) -> tuple[str, str]:
    subject = f"[NuvoDesk] Proyecto asignado: {project.get('name','')}"
    pri = project.get("priority", "normal")
    pri_label = _PRIORITY_LABEL.get(pri, pri)
    pri_color = _PRIORITY_COLOR.get(pri, "#64748b")
    due = project.get("due_date","") or "—"
    body = f"""
    <h2 style="margin:0 0 6px;font-size:1.25rem;font-weight:800;color:#0f172a">
      Se te ha asignado un proyecto
    </h2>
    <p style="margin:0 0 22px;font-size:.9rem;color:#475569">
      Hola {tech_name}, tienes un nuevo proyecto asignado en NuvoDesk.
    </p>
    <div style="border-left:4px solid {pri_color};background:#f8fafc;
      border-radius:0 8px 8px 0;padding:16px 20px;margin-bottom:24px">
      <p style="margin:0 0 4px;font-size:1.05rem;font-weight:800;color:#0f172a">
        {project.get('name','')}
      </p>
      <p style="margin:0;font-size:.85rem;color:#64748b">{project.get('client','')}</p>
    </div>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-bottom:28px">
      {_kv_row("Prioridad", _pill(pri_label, pri_color))}
      {_kv_row("Fecha límite", due)}
      {_kv_row("Tipo", project.get('work_type','').capitalize() or '—')}
    </table>
    {_btn("Ver proyecto", project_url)}"""
    return subject, _base("Proyecto asignado", f"Nuevo proyecto: {project.get('name','')}", body)


def tpl_project_due(tech_name: str, project: dict, days_left: int, project_url: str) -> tuple[str, str]:
    subject = f"[NuvoDesk] ⏰ Proyecto vence en {days_left} día{'s' if days_left != 1 else ''}: {project.get('name','')}"
    color = "#dc2626" if days_left <= 1 else "#ea580c" if days_left <= 3 else "#b45309"
    body = f"""
    <h2 style="margin:0 0 6px;font-size:1.25rem;font-weight:800;color:#0f172a">
      Proyecto próximo a vencer
    </h2>
    <p style="margin:0 0 22px;font-size:.9rem;color:#475569">
      Hola {tech_name}, un proyecto a tu cargo vence pronto.
    </p>
    <div style="border-left:4px solid {color};background:#fff7ed;
      border-radius:0 8px 8px 0;padding:16px 20px;margin-bottom:24px">
      <p style="margin:0 0 4px;font-size:1.05rem;font-weight:800;color:#0f172a">
        {project.get('name','')}
      </p>
      <p style="margin:0;font-size:.85rem;color:#64748b">{project.get('client','')}</p>
    </div>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-bottom:28px">
      {_kv_row("Vence", project.get('due_date',''))}
      {_kv_row("Tiempo restante", _pill(f"{days_left} día{'s' if days_left != 1 else ''}", color))}
    </table>
    {_btn("Ver proyecto", project_url, color)}"""
    return subject, _base("Proyecto próximo a vencer", f"Vence en {days_left} días", body)


def tpl_task_overdue(tech_name: str, task_name: str, project_name: str, due_date: str, project_url: str) -> tuple[str, str]:
    subject = f"[NuvoDesk] Tarea vencida: {task_name}"
    body = f"""
    <h2 style="margin:0 0 6px;font-size:1.25rem;font-weight:800;color:#0f172a">
      Tarea vencida sin completar
    </h2>
    <p style="margin:0 0 22px;font-size:.9rem;color:#475569">
      Hola {tech_name}, la siguiente tarea superó su fecha límite.
    </p>
    <div style="border-left:4px solid #dc2626;background:#fef2f2;
      border-radius:0 8px 8px 0;padding:16px 20px;margin-bottom:24px">
      <p style="margin:0 0 4px;font-size:1.05rem;font-weight:800;color:#0f172a">{task_name}</p>
      <p style="margin:0;font-size:.85rem;color:#64748b">Proyecto: {project_name}</p>
    </div>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-bottom:28px">
      {_kv_row("Fecha límite", due_date or "—")}
      {_kv_row("Estado", _pill("Vencida", "#dc2626"))}
    </table>
    {_btn("Ver proyecto", project_url, "#dc2626")}"""
    return subject, _base("Tarea vencida", f"Tarea vencida: {task_name}", body)


def tpl_low_stock(material_name: str, current_qty: int, min_qty: int, inventory_url: str) -> tuple[str, str]:
    subject = f"[NuvoDesk] Stock bajo: {material_name}"
    body = f"""
    <h2 style="margin:0 0 6px;font-size:1.25rem;font-weight:800;color:#0f172a">
      Alerta de stock bajo
    </h2>
    <p style="margin:0 0 22px;font-size:.9rem;color:#475569">
      Un material del almacén está por debajo del mínimo establecido.
    </p>
    <div style="border-left:4px solid #b45309;background:#fffbeb;
      border-radius:0 8px 8px 0;padding:16px 20px;margin-bottom:24px">
      <p style="margin:0 0 4px;font-size:1.05rem;font-weight:800;color:#0f172a">{material_name}</p>
    </div>
    <table cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-bottom:28px">
      {_kv_row("Stock actual", _pill(str(current_qty), "#dc2626"))}
      {_kv_row("Mínimo", str(min_qty))}
    </table>
    {_btn("Ver inventario", inventory_url, "#b45309")}"""
    return subject, _base("Stock bajo", f"Stock bajo: {material_name}", body)


def tpl_test(to_name: str) -> tuple[str, str]:
    subject = "NuvoDesk — correo de prueba"
    body = f"""
    <h2 style="margin:0 0 6px;font-size:1.25rem;font-weight:800;color:#0f172a">
      Correo de prueba ✓
    </h2>
    <p style="margin:0 0 16px;font-size:.9rem;color:#475569;line-height:1.65">
      Este es un correo de prueba enviado desde NuvoDesk.<br>
      Si lo recibes, la configuración SMTP es correcta.
    </p>
    <p style="margin:0;font-size:.8rem;color:#94a3b8">Destinatario: {to_name}</p>"""
    return subject, _base("Correo de prueba", "Configuración SMTP correcta", body)
