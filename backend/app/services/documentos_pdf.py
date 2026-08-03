"""HTML -> PDF rendering for contrato/factura documents (WeasyPrint + Jinja2).

Templates live in the database (``PlantillaDocumento.contenido_html``, seeded
provisionally by migration 0006) so Judit's real contract text can be edited
without a code deploy. This module only renders — it never invents content:
every placeholder must be supplied by the caller, and
``services/documentos_comerciales.validar`` refuses to generate anything
until the required data is present.
"""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined
from weasyprint import HTML

# autoescape=True unconditionally (not select_autoescape, which only
# activates by filename extension and never fires for from_string() templates
# with no name) — every placeholder value is a person's real name/CIF/address
# and must be HTML-escaped even though the surrounding template markup is not.
_ENV = Environment(autoescape=True, undefined=StrictUndefined)

# Wraps the DB-stored template body with a shared, minimal print stylesheet.
# The body itself carries an .aviso-provisional banner (see migration 0006's
# seeded templates) whenever it is still the placeholder text, so a
# provisional PDF can never be mistaken for a final one even if downloaded
# and forwarded before Judit supplies the real wording.
_SHELL = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  @page { size: A4; margin: 2.5cm; }
  body { font-family: "DejaVu Sans", sans-serif; font-size: 11pt; color: #181c1e; }
  h1 { font-size: 16pt; margin-bottom: 0.5em; }
  table { width: 100%; border-collapse: collapse; margin: 1em 0; }
  th, td { text-align: left; padding: 0.4em 0.6em; border-bottom: 1px solid #c4c6cf; }
  .aviso-provisional {
    background: #ffdad6; color: #410002; padding: 0.6em 1em; margin-bottom: 1.5em;
    font-weight: bold; border-radius: 4px;
  }
</style>
</head>
<body>
{{ cuerpo | safe }}
</body>
</html>
"""


def render_html(template_html: str, context: dict) -> str:
    """Render a DB-stored Jinja2 template string against ``context``.

    ``StrictUndefined`` makes a missing placeholder raise instead of silently
    rendering an empty string — a blank CIF/precio in a legal document is
    worse than a loud failure at generation time.
    """
    cuerpo = _ENV.from_string(template_html).render(**context)
    return _ENV.from_string(_SHELL).render(cuerpo=cuerpo)


def render_pdf(template_html: str, context: dict) -> bytes:
    html = render_html(template_html, context)
    return HTML(string=html).write_pdf()
