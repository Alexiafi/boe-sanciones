"""SMTP email sending with attachments — gated, and safe to point at Mailpit.

Off by default (``EMAIL_SENDING_ENABLED=false``); every caller must also pass
an explicit ``confirmar=True``. ``transport`` is injectable so tests never
open a real socket: ``SmtpTransport`` constructs its ``smtplib.SMTP`` client
only inside ``send()``, never at import or ``__init__`` time, so a test can
prove no socket is touched simply by not calling it (see
``tests/test_mailer.py``, following the same discipline as
``services/enrichment/service.py``).

For local development, point ``SMTP_HOST``/``SMTP_PORT`` at the Mailpit
service in ``docker-compose.yml`` (profile ``dev-mail``) instead of a real
mailbox — the email (with attachments) lands in a local web UI, nothing
leaves the machine.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class EmailSendingDisabled(ValueError):
    """Raised when a send is attempted without every gate open."""


@dataclass(frozen=True)
class Adjunto:
    nombre: str
    contenido: bytes
    mimetype: str = "application/pdf"


class EmailTransport(Protocol):
    def send(self, msg: EmailMessage) -> None: ...


class SmtpTransport:
    def send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            if settings.smtp_use_tls:
                try:
                    server.starttls()
                except smtplib.SMTPNotSupportedError:
                    pass  # Mailpit and similar local relays don't offer STARTTLS
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)


def email_sending_available() -> tuple[bool, str | None]:
    if not settings.email_sending_enabled:
        return False, "El envío de email está desactivado (EMAIL_SENDING_ENABLED=false)."
    if not settings.smtp_host:
        return False, "No hay servidor SMTP configurado (SMTP_HOST)."
    return True, None


def build_message(*, destino: str, asunto: str, html: str, adjuntos: list[Adjunto] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = settings.smtp_from or settings.smtp_user or "no-reply@boe-sanciones.local"
    msg["To"] = destino
    msg.set_content("Este mensaje requiere un cliente de correo compatible con HTML.")
    msg.add_alternative(html, subtype="html")
    for adjunto in adjuntos or []:
        maintype, _, subtype = adjunto.mimetype.partition("/")
        msg.add_attachment(
            adjunto.contenido, maintype=maintype or "application", subtype=subtype or "octet-stream",
            filename=adjunto.nombre,
        )
    return msg


def enviar_email(
    *, destino: str, asunto: str, html: str, adjuntos: list[Adjunto] | None = None,
    confirmar: bool = False, transport: EmailTransport | None = None,
) -> bool:
    if not confirmar:
        raise EmailSendingDisabled("Debe confirmar explícitamente el envío (confirmar=true).")
    disponible, motivo = email_sending_available()
    if not disponible:
        raise EmailSendingDisabled(motivo)
    msg = build_message(destino=destino, asunto=asunto, html=html, adjuntos=adjuntos)
    (transport or SmtpTransport()).send(msg)
    logger.info("Email enviado a %s: %s (%d adjuntos)", destino, asunto, len(adjuntos or []))
    return True
