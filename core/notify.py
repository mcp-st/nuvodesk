"""Notification helpers: internal DB notifications + SMTP email."""
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from core.db import q1, run, r2d


def get_setting(key: str, default: str = "") -> str:
    row = q1("SELECT value FROM app_settings WHERE key=?", (key,))
    return row[0] if row else default


def set_setting(key: str, value: str):
    run("INSERT OR REPLACE INTO app_settings (key,value) VALUES(?,?)", (key, value))


def send_email(to_addr: str, subject: str, html_body: str, text_body: str = "") -> str | None:
    """Returns None on success, error string on failure."""
    host      = get_setting("smtp_host")
    port      = int(get_setting("smtp_port", "587") or "587")
    user      = get_setting("smtp_user")
    pwd       = get_setting("smtp_pass")
    from_addr = get_setting("smtp_from") or user
    tls       = get_setting("smtp_tls", "1") == "1"

    if not host:
        return "SMTP no configurado (host vacío)"
    if not to_addr:
        return "Destinatario vacío"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to_addr
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context() if tls else None
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            if tls:
                smtp.starttls(context=ctx)
                smtp.ehlo()
            if user:
                smtp.login(user, pwd)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())
        return None
    except Exception as e:
        return str(e)


def _notify(user_id: int, title: str, body: str, url: str,
            event_key: str = "", extra: dict | None = None):
    """Create internal notification and optionally send HTML email per event rules."""
    rule = r2d(q1(
        "SELECT notify_internal, notify_email FROM notif_rules WHERE event_key=?",
        (event_key,)
    )) if event_key else None

    do_internal = rule["notify_internal"] if rule else 1
    do_email    = rule["notify_email"]    if rule else 0

    if do_internal:
        run("INSERT INTO notifications (user_id,title,body,url) VALUES(?,?,?,?)",
            (user_id, title, body, url))

    if do_email:
        user_row = r2d(q1("SELECT email, display_name FROM users WHERE id=?", (user_id,)))
        to = (user_row["email"] or "").strip() if user_row else ""
        if to:
            html, text = _render_email(event_key, title, body, url, extra or {},
                                       user_row.get("display_name", "") if user_row else "")
            send_email(to, subject=f"[NuvoDesk] {title}", html_body=html, text_body=text)


def _render_email(event_key: str, title: str, body: str, url: str,
                  extra: dict, recipient_name: str) -> tuple[str, str]:
    """Returns (html, text) for an email notification."""
    from core.email_templates import (
        tpl_project_assigned, tpl_project_due,
        tpl_task_overdue, tpl_low_stock, _base,
    )
    text = f"{title}\n\n{body}\n\n{url}"

    if event_key == "project_assigned":
        _, html = tpl_project_assigned(recipient_name, extra.get("project", {}), url)
    elif event_key == "project_due_soon":
        _, html = tpl_project_due(recipient_name, extra.get("project", {}),
                                   extra.get("days_left", 0), url)
    elif event_key == "task_overdue":
        _, html = tpl_task_overdue(
            recipient_name, extra.get("task_name", title),
            extra.get("project_name", ""), extra.get("due_date", ""), url)
    elif event_key == "stock_low":
        _, html = tpl_low_stock(
            extra.get("material_name", title),
            extra.get("current_qty", 0), extra.get("min_qty", 0), url)
    else:
        # generic fallback
        body_html = f"""
        <h2 style="margin:0 0 12px;font-size:1.2rem;font-weight:800;color:#0f172a">{title}</h2>
        <p style="margin:0 0 24px;font-size:.9rem;color:#475569;line-height:1.65">{body}</p>
        <a href="{url}" style="display:inline-block;background:#0f172a;color:#fff;text-decoration:none;
          padding:13px 28px;border-radius:8px;font-size:.9rem;font-weight:700">Ver en NuvoDesk</a>"""
        html = _base(title, body, body_html)

    return html, text
