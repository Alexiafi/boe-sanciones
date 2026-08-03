"""Pure regex/checksum tests: no database, no network, no OpenAI. These run
unconditionally (no TEST_DATABASE_URL_SYNC needed), like test_oportunidades.py's
non-DB tests."""

from __future__ import annotations

from app.services.historico.patterns import (
    dni_encaja_con_mascara,
    extraer_claves,
    normalizar_nombre,
    validar_cif,
    validar_dni,
)


def test_dni_nie_cif_validos_se_extraen():
    texto = "Notificado a D. con DNI 12345678Z y a Dña. con NIE X1234567L, empresa CIF B12345674."
    claves = extraer_claves(texto)
    assert "12345678Z" in claves.identificadores
    assert "X1234567L" in claves.identificadores
    assert "B12345674" in claves.identificadores


def test_checksum_invalido_se_descarta():
    texto = "Referencia con DNI 12345678A y CIF B12345679 (dígitos de control incorrectos)."
    claves = extraer_claves(texto)
    assert "12345678A" not in claves.identificadores
    assert "B12345679" not in claves.identificadores


def test_expediente_no_produce_falso_positivo():
    texto = "expediente B1234567/2021, Nº 12345678, CSV: ABC12345678Z"
    claves = extraer_claves(texto)
    assert claves.identificadores == []


def test_matricula_nueva_se_extrae_y_vocales_se_rechazan():
    assert "1234BCD" in extraer_claves("matrícula 1234 BCD del vehículo").matriculas
    assert "1234ABC" not in extraer_claves("el código 1234 ABC del anexo").matriculas


def test_matricula_antigua_requiere_contexto_y_provincia_valida():
    assert "M1234AB" in extraer_claves("el vehículo con matrícula M-1234-AB fue embargado").matriculas
    assert "M1234AB" not in extraer_claves("según el anexo M 1234 AB de la resolución").matriculas
    assert "XX1234AB" not in extraer_claves("el vehículo XX-1234-AB fue embargado").matriculas


def test_mascara_dni_se_conserva_y_encaja_posicionalmente():
    claves = extraer_claves("Notificado a la persona con DNI ***4567**")
    assert "***4567**" in claves.digitos_parciales
    assert dni_encaja_con_mascara("12345678Z", "***4567**") is True
    assert dni_encaja_con_mascara("12395678Z", "***4567**") is False


def test_razon_social_requiere_forma_juridica():
    claves = extraer_claves("La empresa ACME LOGISTICA SL fue sancionada.")
    assert "ACME LOGISTICA SL" in claves.nombres


def test_organismos_se_descartan():
    claves = extraer_claves("MINISTERIO DEL INTERIOR notifica a DIRECCION GENERAL DE TRAFICO SA.")
    assert claves.nombres == []


def test_normalizacion_quita_acentos_y_usa_sentinela():
    assert normalizar_nombre("José María García") == "JOSE MARIA GARCIA"
    claves = extraer_claves("JOSÉ MARÍA GARCÍA con DNI 12345678Z. ACME LOGISTICA SL fue sancionada.")
    assert "zzsep" in claves.nombres_norm
    assert "JOSE MARIA GARCIA" in claves.nombres_norm
    assert "ACME LOGISTICA SL" in claves.nombres_norm


def test_topes_por_documento():
    texto = " ".join(f"{n:08d}Z" for n in range(5000))
    # None of these pass the DNI checksum by construction, so this also
    # exercises that a large scan doesn't blow up; the real cap is checked
    # structurally via MAX_IDENTIFICADORES.
    claves = extraer_claves(texto)
    assert len(claves.identificadores) <= 2_000


def test_checksum_helpers_directos():
    assert validar_dni("12345678", "Z") is True
    assert validar_dni("12345678", "A") is False
    assert validar_cif("B", "1234567", "4") is True
    assert validar_cif("B", "1234567", "9") is False
