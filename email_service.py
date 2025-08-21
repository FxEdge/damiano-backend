# email_service.py
import os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from jinja2 import Template  # templating per soggetto/corpo

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")           # es. fxedge.tools@gmail.com
SMTP_PASS = os.getenv("SMTP_PASS")           # App Password di Gmail (non la password normale)
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "")
SMTP_REPLY_TO = os.getenv("SMTP_REPLY_TO")

def render_template(template_str: str, context: dict) -> str:
    """Rende una stringa con placeholder Jinja2."""
    return Template(template_str or "").render(**(context or {}))

def _build_message(to_email: str, subject: str, html: str, plain_fallback: str | None = None):
    msg = MIMEMultipart("alternative")

    # Mittente “Nome <email>” se fornito così in SMTP_FROM
    if SMTP_FROM and "<" in SMTP_FROM and ">" in SMTP_FROM:
        display = SMTP_FROM.split("<")[0].strip()
        email = SMTP_FROM.split("<")[1].split(">")[0].strip()
        msg["From"] = formataddr((display, email))
        from_addr = email
    else:
        msg["From"] = SMTP_FROM or SMTP_USER or ""
        from_addr = SMTP_USER or ""

    msg["To"] = to_email
    msg["Subject"] = subject
    if SMTP_REPLY_TO:
        msg["Reply-To"] = SMTP_REPLY_TO

    if plain_fallback:
        msg.attach(MIMEText(plain_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html or "", "html", "utf-8"))
    return msg, from_addr

def send_email(to_email: str, subject: str, html_body: str, plain_fallback: str | None = None):
    """Invio reale via SMTP (Gmail o altro)."""
    if not (SMTP_USER and SMTP_PASS):
        raise RuntimeError("SMTP non configurato: imposta SMTP_USER e SMTP_PASS nelle env vars")

    msg, from_addr = _build_message(to_email, subject, html_body, plain_fallback)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(from_addr, [to_email], msg.as_string())
