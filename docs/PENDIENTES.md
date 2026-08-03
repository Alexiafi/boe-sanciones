# Pendientes de puesta en marcha

Registro de lo que queda abierto tras la sesión 3 (histórico, documentos comerciales, rediseño). Todo lo
descrito aquí está **construido y probado con fixtures**, pero apagado por defecto — no se activa ni ejecuta
solo. Ver también `docs/GUIA_OPERATIVA.md` (cómo activarlo paso a paso) y `docs/LIMITES.md` (por qué existen
estos límites).

## 1. Datos y credenciales pendientes de Judit

| Qué falta | Para qué | Dónde se configura |
|---|---|---|
| Texto definitivo del contrato (qué es fijo, qué cambia por cliente además de CIF y precio) | La plantilla sembrada es explícitamente provisional (aviso visible en el propio PDF) | `PATCH /api/documentos-comerciales/plantillas/{id}` |
| Datos fiscales del emisor: nombre/razón social, CIF, dirección, email, tipo de IVA | Sin ellos, la API no permite generar ni contrato ni factura (`422` con la lista exacta de lo que falta) | `.env`: `EMISOR_NOMBRE`, `EMISOR_CIF`, `EMISOR_DIRECCION`, `EMISOR_EMAIL`, `EMISOR_IVA_PORCENTAJE` |
| Serie de numeración de factura, y si arranca en un número concreto por continuidad con facturación previa | Sin serie configurada no se puede emitir factura | `.env`: `FACTURA_SERIE` |
| Credenciales SMTP reales del buzón de envío (host, puerto, usuario, contraseña, remitente, TLS) | Necesarias para activar el envío real de contrato/factura/digest | `.env`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` |
| Regla de prescripción/vigencia que debe verse en `/historial` | Hoy está implementada como parámetro, no como criterio jurídico dado — pendiente de validación legal | N/A (lógica de negocio, no config) |
| Decisión sobre activar el buscador público del TEU en vivo | Por defecto solo se usa el índice propio | `.env`: `TEU_PUBLIC_SEARCH_ENABLED` |
| Proveedor de enriquecimiento de contacto a usar (DataForSEO / Serper) y su saldo | El enriquecimiento sigue apagado por defecto desde la sesión 2 | `.env`: `ENRICHMENT_ENABLED`, `ENRICHMENT_SEARCH_PROVIDER` |

## 2. Operaciones reales — solo en puesta en marcha, con confirmación explícita

Ninguna de estas tiene una ruta que se dispare sola. Cada una exige, en el momento, tanto una puerta permanente
en `.env` como una confirmación por petición.

| Operación | Puerta permanente (`.env`) | Confirmación por petición |
|---|---|---|
| Backfill histórico real (más allá del rango diminuto usado en pruebas) | `HISTORICO_BACKFILL_ENABLED=true` | Previsualizar rango + token de confirmación del rango exacto, desde la pantalla "Operación" |
| Extracción estructurada OpenAI (diaria u on-demand sobre histórico) | `OPENAI_EXTRACTION_ENABLED=true` + `OPENAI_API_KEY` | Checkbox/flag `permitir_extraccion_pago` en cada lanzamiento |
| Consulta pública del TEU en vivo | `TEU_PUBLIC_SEARCH_ENABLED=true` | Casilla "Incluir búsqueda pública TEU (en vivo)" en cada búsqueda |
| Envío real de email (contrato, factura, digest) | `EMAIL_SENDING_ENABLED=true` + SMTP real configurado | `confirmar=true` en cada envío — probar antes con Mailpit (`docker compose --profile dev-mail up -d mailpit`) |
| Enriquecimiento de contacto en lote | `ENRICHMENT_BATCH_ENABLED=true` | `confirmar=true` en cada lote |

**Recomendación de orden**: activar primero backfill histórico (rango reciente, ampliando hacia atrás en
sesiones sucesivas) y extracción OpenAI si aplica; dejar documentos comerciales y envío de email para cuando
Judit haya aportado los datos de la sección 1; enriquecimiento y TEU en vivo son opcionales y pueden activarse
en cualquier momento.
