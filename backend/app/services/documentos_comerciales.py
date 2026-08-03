"""Contract/invoice generation: explicit validation of missing data, atomic
invoice numbering, and PDF creation.

Nothing here invents a value. Every required field surfaces as a specific
missing-field message from ``validar`` instead of a generic error, and
``generar_contrato``/``generar_factura`` refuse to run — raising
``DatosFaltantesError`` — until ``validar`` returns an empty list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

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


def _pdf_path(cliente: Cliente, tipo: str, identificador: str) -> str:
    carpeta = os.path.join(settings.documentos_dir, cliente.codigo)
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, f"{tipo}_{identificador}.pdf")


def generar_contrato(db: Session, cliente: Cliente, *, precio: float) -> DocumentoComercial:
    faltantes = validar(db, "contrato", cliente, {"precio": precio})
    if faltantes:
        raise DatosFaltantesError(faltantes)

    plantilla = plantilla_activa(db, "contrato")
    hoy = date.today()
    contexto = {"cliente": cliente, "emisor": _emisor_dict(), "precio": _money(precio), "fecha": hoy.isoformat()}
    identificador = f"{cliente.codigo}-{hoy.isoformat()}"
    pdf_bytes = render_pdf(plantilla.contenido_html, contexto)
    ruta = _pdf_path(cliente, "contrato", identificador)
    with open(ruta, "wb") as fh:
        fh.write(pdf_bytes)

    documento = DocumentoComercial(
        cliente_id=cliente.id, tipo="contrato", pdf_path=ruta,
        datos={
            "precio": float(precio), "emisor": _emisor_dict(), "plantilla_id": plantilla.id,
            "plantilla_provisional": PROVISIONAL_MARKER in plantilla.contenido_html,
        },
        estado="generado",
    )
    db.add(documento)
    db.add(ActividadCliente(
        cliente_id=cliente.id, tipo="sistema", titulo="Contrato generado",
        datos={"precio": float(precio)},
    ))
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
        "factura": {"numero": numero, "fecha": hoy.isoformat()},
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
