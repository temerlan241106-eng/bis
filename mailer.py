"""Отправка писем через SMTP (по умолчанию Gmail). Без настроек письмо печатается в консоль."""
import smtplib
import sys
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app, render_template

outbox = []  # в тестах сюда складываются «отправленные» письма


def _safe_stdout():
    """Консоль Windows может не уметь печатать кириллицу/эмодзи — не падаем из-за этого."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def configured():
    cfg = current_app.config
    return bool(cfg.get("MAIL_USERNAME") and cfg.get("MAIL_PASSWORD"))


def send(to, subject, template, **ctx):
    """Отправляет письмо из шаблона templates/email/<template>.html (+ .txt). Возвращает True/False."""
    cfg = current_app.config
    html = render_template(f"email/{template}.html", **ctx)
    text = render_template(f"email/{template}.txt", **ctx)

    if cfg.get("TESTING"):
        outbox.append({"to": to, "subject": subject, "text": text, "html": html})
        return True

    if not configured():
        print("\n" + "=" * 60)
        print(f"✉  Почта не настроена (MAIL_USERNAME/MAIL_PASSWORD в .env). Письмо для {to}:")
        print(f"   {subject}\n{text}")
        print("=" * 60 + "\n")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.get("MAIL_SENDER_NAME", "FitnessIT KBTU"), cfg["MAIL_USERNAME"]))
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    try:
        port = int(cfg.get("MAIL_PORT", 587))
        if port == 465:
            with smtplib.SMTP_SSL(cfg["MAIL_SERVER"], port, timeout=20,
                                  context=ssl.create_default_context()) as s:
                s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["MAIL_SERVER"], port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
                s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as e:
        current_app.logger.error("Не удалось отправить письмо на %s: %s", to, e)
        return False
