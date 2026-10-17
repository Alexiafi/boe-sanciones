"""OpenAI request shape: cost levers and the instructions that keep an
administration's contact data out of the extraction. No network, no client."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import extractor
from app.services.extractor import SYSTEM_PROMPT, build_extraction_request
from app.services.parser import limpiar_texto_pdf


@pytest.fixture(autouse=True)
def _restablecer(monkeypatch):
    monkeypatch.setattr(extractor, "_REASONING_EFFORT_RECHAZADO", False)


def test_default_model_is_the_cheapest_tier():
    assert settings.openai_model.endswith("nano")


def test_reasoning_models_get_low_reasoning_effort_and_no_temperature(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "low")
    body = build_extraction_request("texto", "titulo", model="gpt-5.4-nano")
    assert body["reasoning_effort"] == "low"
    assert "temperature" not in body


def test_reasoning_effort_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "")
    assert "reasoning_effort" not in build_extraction_request("t", "x", model="gpt-5.4-nano")


def test_non_reasoning_models_keep_temperature_and_skip_reasoning_effort(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "low")
    body = build_extraction_request("t", "x", model="gpt-4.1-mini")
    assert body["temperature"] == 0.0 and "reasoning_effort" not in body


def test_a_rejected_reasoning_effort_is_retried_without_it_and_remembered(monkeypatch):
    """A wrong value in .env must not fail every document of the day."""
    import httpx
    from openai import BadRequestError

    monkeypatch.setattr(settings, "openai_api_key", "k")
    monkeypatch.setattr(settings, "openai_reasoning_effort", "turbo")
    enviados = []

    class Completion:
        def model_dump(self, mode="json"):
            return {"choices": [{"message": {"content": '{"afectados": [], "es_documento_relevante": false}'}}]}

    class Completions:
        def create(self, **body):
            enviados.append(dict(body))
            if "reasoning_effort" in body:
                request = httpx.Request("POST", "https://api.openai.test/v1/chat/completions")
                raise BadRequestError(
                    "Unsupported value: 'reasoning_effort'", response=httpx.Response(400, request=request), body=None,
                )
            return Completion()

    class Cliente:
        def __init__(self, **_kwargs):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(extractor, "OpenAI", Cliente)
    resultado = extractor.extract_sanctions("texto", "titulo")
    assert resultado.es_documento_relevante is False
    assert "reasoning_effort" in enviados[0] and "reasoning_effort" not in enviados[1]
    extractor.extract_sanctions("texto", "otro")
    assert "reasoning_effort" not in enviados[2]  # remembered: no more wasted round trips


def test_prompt_forbids_using_the_administrations_contact():
    assert "NUNCA" in SYSTEM_PROMPT and "Administración que publica" in SYSTEM_PROMPT
    assert "nombre` es null" in SYSTEM_PROMPT


def test_pdf_watermark_noise_is_removed_from_extracted_text():
    crudo = "Texto útil\n\ne\n4\n2\n8\nV\n\nsegunda línea\n   \n-\nfin"
    assert limpiar_texto_pdf(crudo) == "Texto útil segunda línea fin"
