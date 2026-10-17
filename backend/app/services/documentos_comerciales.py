"""Contract/invoice generation: explicit validation of missing data, atomic
invoice numbering, and PDF creation.

Nothing here invents a value. Every required field surfaces as a specific
missing-field message from ``validar`` instead of a generic error, and
``generar_contrato``/``generar_factura`` refuse to run — raising
``DatosFaltantesError`` — until ``validar`` returns an empty list.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.cliente import ActividadCliente, Cliente
from app.models.documentos_comerciales import ContadorFactura, DocumentoComercial, PlantillaDocumento
from app.services.documentos_pdf import render_pdf

# Marks a template as not-yet-real (see migration 0006's seeded templates).
# generar_* still produces a PDF from it — refusing to generate at all would
# block previewing the layout — but the resulting DocumentoComercial.datos
# records that it came from a provisional template, and the PDF itself
# carries a visible on-page banner (see documentos_pdf._SHELL).
PROVISIONAL_MARKER = "PLANTILLA PROVISIONAL"
_LOGO_DATA_URI = "data:image/jpeg;base64," + (
    Path(__file__).resolve().parent.parent / "assets" / "en_plazo_logo.jpg.b64"
).read_text(encoding="ascii").strip()

_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_larga(d: date) -> str:
    return f"{d.day} de {_MESES_ES[d.month - 1]} de {d.year}"


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


@dataclass(frozen=True)
class CampoFaltante:
    campo: str
    mensaje: str

    def to_dict(self) -> dict:
        return {"campo": self.campo, "mensaje": self.mensaje}


class DatosFaltantesError(ValueError):
    def __init__(self, faltantes: list[CampoFaltante]):
        self.faltantes = faltantes
        super().__init__("Faltan datos para generar el documento: " + ", ".join(f.campo for f in faltantes))


def _emisor_dict() -> dict:
    return {
        "nombre": settings.emisor_nombre,
        "cif": settings.emisor_cif,
        "direccion": settings.emisor_direccion,
        "email": settings.emisor_email,
        "iban": settings.emisor_iban,
        "iva_porcentaje": settings.emisor_iva_porcentaje,
    }


def _money(value) -> str:
    dec = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{dec:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def plantilla_activa(db: Session, tipo: str) -> PlantillaDocumento | None:
    return db.execute(
        select(PlantillaDocumento)
        .where(PlantillaDocumento.tipo == tipo, PlantillaDocumento.activo.is_(True))
        .order_by(PlantillaDocumento.version.desc())
    ).scalars().first()


def validar_estructural(db: Session, tipo: str, cliente: Cliente) -> list[CampoFaltante]:
    """Checks that don't depend on the specific transaction (precio/cuantía):
    plantilla, datos del emisor, datos fiscales del cliente. This is what the
    "checklist de datos pendientes" preview (``GET .../documentos/validar``)
    shows BEFORE an amount has even been entered — it must not report
    precio/cuantía as missing just because the preview call has none yet."""
    faltantes: list[CampoFaltante] = []

    if plantilla_activa(db, tipo) is None:
        faltantes.append(CampoFaltante("plantilla", f"No hay una plantilla activa de tipo '{tipo}'."))

    if not settings.emisor_nombre:
        faltantes.append(CampoFaltante("EMISOR_NOMBRE", "Falta el nombre/razón social del emisor en la configuración."))
    if not settings.emisor_cif:
        faltantes.append(CampoFaltante("EMISOR_CIF", "Falta el CIF del emisor en la configuración."))
    if not settings.emisor_direccion:
        faltantes.append(CampoFaltante("EMISOR_DIRECCION", "Falta la dirección fiscal del emisor en la configuración."))

    if tipo == "factura" and not settings.factura_serie:
        faltantes.append(
            CampoFaltante("FACTURA_SERIE", "Falta configurar la serie de numeración de factura (FACTURA_SERIE).")
        )
    if tipo == "factura" and not settings.emisor_iban:
        faltantes.append(CampoFaltante("EMISOR_IBAN", "Falta configurar el IBAN del emisor (EMISOR_IBAN)."))

    if not cliente.cif_nif:
        faltantes.append(CampoFaltante("cliente.cif_nif", "El cliente no tiene CIF/NIF registrado."))
    if not cliente.direccion_fiscal:
        faltantes.append(CampoFaltante("cliente.direccion_fiscal", "El cliente no tiene dirección fiscal registrada."))

    return faltantes


def validar(db: Session, tipo: str, cliente: Cliente, payload: dict) -> list[CampoFaltante]:
    """Full check before actually generating: structural readiness plus the
    transaction-specific amount/concept for this particular document."""
    faltantes = validar_estructural(db, tipo, cliente)

    if tipo == "contrato":
        precio = payload.get("precio")
        if precio is None or float(precio) <= 0:
            faltantes.append(CampoFaltante("precio", "Debe indicar el precio del contrato (mayor que 0)."))
        if not payload.get("servicio"):
            faltantes.append(CampoFaltante("servicio", "Debe indicar el servicio contratado."))
        if not payload.get("forma_pago"):
            faltantes.append(CampoFaltante("forma_pago", "Debe indicar la forma de pago."))
    elif tipo == "factura":
        cuantia = payload.get("cuantia")
        if cuantia is None or float(cuantia) <= 0:
            faltantes.append(CampoFaltante("cuantia", "Debe indicar la cuantía de la factura (mayor que 0)."))
        if not payload.get("concepto"):
            faltantes.append(CampoFaltante("concepto", "Debe indicar el concepto de la factura."))

    return faltantes


def allocate_numero_factura(db: Session, serie: str, anio: int) -> str:
    """Atomic PostgreSQL UPSERT counter — same pattern as the OP-/CLI- codes
    in ``services/oportunidades.allocate_codigo``; safe under concurrent
    requests, never reused."""
    stmt = (
        insert(ContadorFactura)
        .values(serie=serie, anio=anio, ultimo_valor=1)
        .on_conflict_do_update(
            index_elements=[ContadorFactura.serie, ContadorFactura.anio],
            set_={"ultimo_valor": ContadorFactura.ultimo_valor + 1},
        )
        .returning(ContadorFactura.ultimo_valor)
    )
    secuencia = db.execute(stmt).scalar_one()
    return f"{serie}-{anio}-{secuencia:04d}"


def nombre_fichero_seguro(valor: str) -> str:
    """A document number is free text chosen by the issuer (a series such as
    ``2026/0072#`` is a perfectly good invoice series) but it must never reach
    the filesystem or a ``Content-Disposition`` header as-is: the ``/`` made the
    path point into a directory that does not exist, so the invoice could be
    neither written nor downloaded."""
    limpio = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9._-]+", "-", str(valor))).strip("-.")
    return limpio or "documento"


def _pdf_path(cliente: Cliente, tipo: str, identificador: str) -> str:
    carpeta = os.path.join(settings.documentos_dir, nombre_fichero_seguro(cliente.codigo))
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, f"{tipo}_{nombre_fichero_seguro(identificador)}.pdf")


def generar_contrato(
    db: Session, cliente: Cliente, *, precio: float, servicio: str, forma_pago: str,
    fecha_inicio: date | None = None,
) -> DocumentoComercial:
    faltantes = validar(db, "contrato", cliente, {"precio": precio, "servicio": servicio, "forma_pago": forma_pago})
    if faltantes:
        raise DatosFaltantesError(faltantes)

    plantilla = plantilla_activa(db, "contrato")
    hoy = date.today()
    inicio = fecha_inicio or hoy
    fin = _add_months(inicio, 12)
    contexto = {
        "cliente": cliente, "emisor": _emisor_dict(), "precio": _money(precio),
        "servicio": servicio, "forma_pago": forma_pago,
        "fecha": hoy.isoformat(),
        "contrato": {
            "lugar": "Barcelona",
            "fecha_larga": _fecha_larga(hoy),
            "fecha_inicio": inicio.strftime("%d/%m/%Y"),
            "fecha_fin": fin.strftime("%d/%m/%Y"),
        },
    }
    identificador = f"{cliente.codigo}-{hoy.isoformat()}"
    pdf_bytes = render_pdf(plantilla.contenido_html, contexto)
    ruta = _pdf_path(cliente, "contrato", identificador)
    with open(ruta, "wb") as fh:
        fh.write(pdf_bytes)

    documento = DocumentoComercial(
        cliente_id=cliente.id, tipo="contrato", pdf_path=ruta,
        datos={
            "precio": float(precio), "servicio": servicio, "forma_pago": forma_pago,
            "fecha_inicio": inicio.isoformat(), "fecha_fin": fin.isoformat(),
            "emisor": _emisor_dict(), "plantilla_id": plantilla.id,
            "plantilla_provisional": PROVISIONAL_MARKER in plantilla.contenido_html,
        },
        estado="generado",
    )
    db.add(documento)
    db.add(ActividadCliente(
        cliente_id=cliente.id, tipo="sistema", titulo="Contrato generado",
        datos={"precio": float(precio)},
    ))
    # A generated contract is what makes a prospect a real client.
    if cliente.estado_cliente == "informado":
        cliente.estado_cliente = "activo"
    if not cliente.fecha_contrato:
        cliente.fecha_contrato = inicio
    if not cliente.precio_contrato:
        cliente.precio_contrato = float(precio)
    db.commit()
    db.refresh(documento)
    return documento


def generar_factura(db: Session, cliente: Cliente, *, cuantia: float, concepto: str) -> DocumentoComercial:
    faltantes = validar(db, "factura", cliente, {"cuantia": cuantia, "concepto": concepto})
    if faltantes:
        raise DatosFaltantesError(faltantes)

    plantilla = plantilla_activa(db, "factura")
    hoy = date.today()
    numero = allocate_numero_factura(db, settings.factura_serie, hoy.year)
    iva_pct = Decimal(str(settings.emisor_iva_porcentaje))
    cuantia_dec = Decimal(str(cuantia)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    iva_importe = (cuantia_dec * iva_pct / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = cuantia_dec + iva_importe

    contexto = {
        "cliente": cliente, "emisor": _emisor_dict(), "concepto": concepto,
        "cuantia": _money(cuantia_dec), "iva_importe": _money(iva_importe), "total": _money(total),
        "factura": {
            "numero": numero,
            "fecha": hoy.strftime("%d/%m/%Y"),
            "fecha_vencimiento": (hoy + timedelta(days=settings.factura_vencimiento_dias)).strftime("%d/%m/%Y"),
            "logo_data_uri": _LOGO_DATA_URI,
        },
    }
    pdf_bytes = render_pdf(plantilla.contenido_html, contexto)
    ruta = _pdf_path(cliente, "factura", numero)
    with open(ruta, "wb") as fh:
        fh.write(pdf_bytes)

    documento = DocumentoComercial(
        cliente_id=cliente.id, tipo="factura", serie=settings.factura_serie, numero=numero, pdf_path=ruta,
        datos={
            "cuantia": float(cuantia_dec), "concepto": concepto, "iva_porcentaje": float(iva_pct),
            "iva_importe": float(iva_importe), "total": float(total), "emisor": _emisor_dict(),
            "plantilla_id": plantilla.id, "plantilla_provisional": PROVISIONAL_MARKER in plantilla.contenido_html,
        },
        estado="generado",
    )
    db.add(documento)
    db.add(ActividadCliente(
        cliente_id=cliente.id, tipo="sistema", titulo=f"Factura {numero} generada",
        datos={"cuantia": float(cuantia_dec), "concepto": concepto},
    ))
    db.commit()
    db.refresh(documento)
    return documento
