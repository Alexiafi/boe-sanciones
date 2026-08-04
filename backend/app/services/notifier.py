"""Notification service: in-app + email."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models.cliente import VinculoCliente
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.services.mailer import email_sending_available, enviar_email

logger = logging.getLogger(__name__)


def create_inapp_notification(
    db: Session,
    sancionado: Sancionado,
    tipo: str = "nueva_sancion",
    cliente_id: int | None = None,
    vinculo_id: int | None = None,
) -> Notificacion:
    """Create the in-app alert for a new sanction.

    ``cliente_id``/``vinculo_id`` are set only when the sanction was
    automatically assigned to an existing client (see
    ``services/vinculos.asignar_sancion_a_cliente`` and
    ``services/alertas.ejecutar_radar_clientes``) — that's what the
    "Solo mis clientes" filter in /notificaciones matches on.
    """
    rol = None
    titular = sancionado.nombre
    if vinculo_id is not None:
        vinculo = db.get(VinculoCliente, vinculo_id)
        if vinculo is not None:
            titular = vinculo.nombre or titular
            rol = vinculo.rol

    if cliente_id is not None:
        titulo = f"Nueva sanción de cliente: {titular or 'Desconocido'}"
        if rol:
            titulo += f" ({rol})"
    else:
        titulo = f"Nueva sanción: {titular or 'Desconocido'}"

    partes = []
    if sancionado.organismo_emisor:
        partes.append(f"Organismo: {sancionado.organismo_emisor}")
    if sancionado.tipo_infraccion:
        partes.append(f"Tipo: {sancionado.tipo_infraccion}")
    if sancionado.importe_multa_eur:
        partes.append(f"Multa: {sancionado.importe_multa_eur:,.2f} EUR")
    if sancionado.expediente:
        partes.append(f"Expediente: {sancionado.expediente}")

    mensaje = " | ".join(partes) if partes else "Se ha detectado una nueva sanción en el BOE."

    notif = Notificacion(
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        leida=False,
        sancionado_id=sancionado.id,
        cliente_id=cliente_id,
    )
    db.add(notif)
    db.flush()
    return notif


def send_email_digest(sancionados: list[Sancionado], fecha: str) -> bool:
    """Send an email digest with new sanctions found for a given date.

    Gated behind EMAIL_SENDING_ENABLED (see services/mailer.py) in addition to
    having a recipient configured — the daily pipeline must never send a real
    email unless sending has been explicitly turned on, even if SMTP
    credentials happen to be present in .env for other testing.
    """
    available, reason = email_sending_available()
    if not available:
        logger.info("Email sending disabled, skipping digest: %s", reason)
        return False
    if not settings.notification_email_to:
        logger.info("No digest recipient configured, skipping digest")
        return False

    if not sancionados:
        logger.info("No sanctions to report, skipping email")
        return False

    subject = f"BOE Sanciones - {len(sancionados)} nuevas sanciones ({fecha})"

    rows = []
    for s in sancionados:
        rows.append(
            f"<tr>"
            f"<td>{s.nombre or '-'}</td>"
            f"<td>{s.identificador or '-'}</td>"
            f"<td>{s.organismo_emisor or '-'}</td>"
            f"<td>{s.tipo_infraccion or '-'}</td>"
            f"<td>{s.importe_multa_eur or '-'}</td>"
            f"<td>{s.expediente or '-'}</td>"
            f"</tr>"
        )

    html_body = f"""\
    <html>
    <body>
    <h2>Nuevas sanciones detectadas en el BOE - {fecha}</h2>
    <p>Se han encontrado <strong>{len(sancionados)}</strong> sancionados nuevos.</p>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
    <tr>
        <th>Nombre</th><th>Identificador</th><th>Organismo</th>
        <th>Tipo</th><th>Multa (EUR)</th><th>Expediente</th>
    </tr>
    {"".join(rows)}
    </table>
    <p style="color:#888;margin-top:20px;">
        Este es un email automático del sistema BOE Sanciones.
    </p>
    </body>
    </html>
    """

    try:
        enviar_email(
            destino=settings.notification_email_to, asunto=subject, html=html_body, confirmar=True,
        )
        logger.info("Email digest sent to %s", settings.notification_email_to)
        return True

    except Exception:
        logger.exception("Failed to send email digest")
        return False
