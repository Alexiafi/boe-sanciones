"""Email sending: gated by EMAIL_SENDING_ENABLED + explicit confirmar=true,
injectable transport, and a real (in-memory) attachment round-trip. No test
here opens a real socket — SmtpTransport is only ever instantiated inside
send(), and no test lets that happen."""

from __future__ import annotations

from email import message_from_bytes

import pytest

from app.config import settings
from app.services.mailer import (
    Adjunto,
    EmailSendingDisabled,
    build_message,
    email_sending_available,
    enviar_email,
)


class _FakeTransport:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


def test_desactivado_por_defecto(monkeypatch):
    monkeypatch.setattr(settings, "email_sending_enabled", False)
    disponible, motivo = email_sending_available()
    assert disponible is False
    assert "EMAIL_SENDING_ENABLED" in motivo


def test_enviar_sin_confirmar_lanza(monkeypatch):
    monkeypatch.setattr(settings, "email_sending_enabled", True)
    transport = _FakeTransport()
    with pytest.raises(EmailSendingDisabled):
        enviar_email(destino="a@example.com", asunto="x", html="<p>x</p>", confirmar=False, transport=transport)
    assert transport.sent == []


def test_enviar_con_flag_apagado_lanza_incluso_confirmando(monkeypatch):
    monkeypatch.setattr(settings, "email_sending_enabled", False)
    transport = _FakeTransport()
    with pytest.raises(EmailSendingDisabled):
        enviar_email(destino="a@example.com", asunto="x", html="<p>x</p>", confirmar=True, transport=transport)
    assert transport.sent == []


def test_enviar_con_todo_confirmado_usa_el_transporte_inyectado(monkeypatch):
    monkeypatch.setattr(settings, "email_sending_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "mailpit")
    transport = _FakeTransport()
    adjunto = Adjunto(nombre="factura.pdf", contenido=b"%PDF-1.4 contenido falso", mimetype="application/pdf")

    ok = enviar_email(
        destino="cliente@example.com", asunto="Factura FAC-2026-0001", html="<p>Adjunto</p>",
        adjuntos=[adjunto], confirmar=True, transport=transport,
    )
    assert ok is True
    assert len(transport.sent) == 1
    msg = transport.sent[0]
    assert msg["To"] == "cliente@example.com"
    assert msg["Subject"] == "Factura FAC-2026-0001"

    # Round-trip through the real email serialisation to prove the attachment
    # survives intact — not just that add_attachment() was called.
    raw = msg.as_bytes()
    parsed = message_from_bytes(raw)
    attachments = [part for part in parsed.walk() if part.get_filename() == "factura.pdf"]
    assert len(attachments) == 1
    assert attachments[0].get_payload(decode=True) == b"%PDF-1.4 contenido falso"


def test_build_message_sin_adjuntos():
    msg = build_message(destino="a@example.com", asunto="s", html="<p>h</p>")
    assert msg["To"] == "a@example.com"
    assert msg.is_multipart()
