# Límites legales y técnicos

Este documento reúne, en un solo sitio, las limitaciones que el equipo de desarrollo ha identificado y que
**requieren valoración jurídica de Judit** antes de operar el sistema con clientes reales. El sistema ayuda a
trabajar más rápido; no sustituye la revisión legal de cada caso (PLAN.md §10.4, propuesta técnica §10.4).

## 1. RGPD y enriquecimiento de contacto

- El enriquecimiento automático de teléfono/email (sesión 2) trata datos personales de personas físicas
  cuando el sancionado es un particular. El sistema está diseñado para minimizar ese tratamiento:
  - **Solo persiste contacto ya publicado profesionalmente** por la propia entidad (páginas "aviso legal" /
    "contacto" de su propia web), nunca datos de fuentes de terceros no verificadas.
  - **Nunca se persiste sin evidencia**: el CIF/NIF o el nombre exacto del sancionado deben aparecer en la
    página encontrada antes de guardar nada (`services/enrichment/verify.py`).
  - Cada dato guardado lleva **fuente, URL de origen y fecha** (`contacto_fuente`, `contacto_url`,
    `contacto_actualizado_at`), siempre editable y borrable desde la ficha.
  - El enriquecimiento en lote está desactivado por defecto y requiere doble confirmación.
- **La base de licitud** (previsiblemente interés legítimo / actividad profesional de la abogacía) y la
  valoración final de cumplimiento **corresponden a Judit**, no al sistema. Antes de operar con clientes
  reales, se recomienda documentar esa base de licitud y, si aplica, informar en el primer contacto según
  corresponda.
- Los datos de particulares en el histórico (nombres, DNI parcial o completo según la fuente) se tratan con
  el mismo criterio de minimización: el índice guarda solo identificadores y nombres normalizados, no perfiles
  enriquecidos, y la extracción estructurada completa solo ocurre bajo demanda sobre documentos concretos.

## 2. Limitación del TEU: 90 días de consulta pública

El Tablón Edictal Único (TEU), donde se publican las notificaciones de la DGT y otras administraciones al
amparo del art. 44 de la Ley 39/2015, **solo permite consulta pública libre durante 90 días** desde la
publicación. Pasado ese plazo, el anuncio deja de ser accesible sin el código de verificación (CSV) del
documento original.

**Consecuencia práctica**: el histórico del TEU de un cliente **anterior a 90 días desde la fecha actual**
solo contiene lo que este sistema haya acumulado **por sí mismo** desde su puesta en marcha (vía el pipeline
diario o un backfill lanzado mientras esos documentos aún estaban en su ventana pública). No hay forma de
recuperar retroactivamente notificaciones del TEU que ya salieron de esa ventana antes de que el sistema
empezara a operar.

- El **BOE ordinario** (sanciones publicadas fuera del TEU) **no tiene esta limitación**: su contenido
  permanece accesible indefinidamente, y el backfill manual sí puede recuperarlo para los 4 años completos.
- Esta limitación se muestra de forma visible en la UI: `/historial`, `/consulta` y el bloque "Histórico
  sancionador" de la ficha de cliente llevan siempre el aviso correspondiente, y cada documento del TEU fuera
  de la ventana de 90 días se marca como "Solo acumulado".

## 3. DNI enmascarado en el BOE ordinario

Por la Disposición Adicional 7ª de la LOPDGDD, las notificaciones del TEU identifican al afectado por su
**número completo** de DNI/NIE/CIF (sin nombre). Las sanciones publicadas por el cauce ordinario del BOE
(fuera del TEU), en cambio, identifican habitualmente por **nombre y apellidos + 4 cifras del DNI visibles**
(`***4567**`), nunca el documento completo.

**Consecuencia práctica**: el casado de un cliente contra el histórico del BOE ordinario es menos preciso
que contra el TEU — se hace por nombre normalizado (búsqueda de texto completo) y, cuando hay 4 dígitos
visibles, se cruzan posicionalmente contra el DNI completo del cliente para reforzar la confianza del
resultado (`via_match="nombre_dni_parcial"`). Esto reduce falsos positivos pero no los elimina del todo — un
resultado por nombre debe revisarse antes de darlo por bueno, especialmente con apellidos comunes.

## 4. Coste variable de OpenAI

- El coste variable del sistema no está en la aplicación en sí, sino en las llamadas a la API de OpenAI para
  extracción estructurada. Corre a cargo de Judit mediante su propia API key.
- Estrategia de contención (ver README y `docs/GUIA_OPERATIVA.md`): extracción completa solo sobre el bloque
  reciente (30 días) y, bajo demanda, sobre documentos históricos concretos ya localizados por regex — nunca
  sobre el histórico completo.
- El backfill histórico **no usa OpenAI en ningún punto** — es una garantía estructural (el módulo no
  siquiera importa el cliente de extracción), no solo una bandera de configuración.

## 5. Variabilidad del formato documental del BOE

No todas las publicaciones presentan la información con el mismo nivel de detalle o estructura. El sistema
está diseñado para tolerar datos incompletos (campos vacíos en vez de fallos, o inferencias no justificadas)
en vez de intentar "adivinar" un dato que el documento no contiene explícitamente. Esto puede resultar en
fichas con campos vacíos que un vistazo al documento original sí aclara — por eso el acceso al documento
oficial del BOE está siempre disponible desde cada sanción, resultado histórico y documento.

## 6. Escalabilidad de la búsqueda histórica

El enfoque actual (índice con `tsvector`/GIN sobre PostgreSQL) es adecuado para el volumen esperado de un
backfill de 4 años del dominio sancionador. Si el volumen creciera muy por encima de lo previsto, podría
convenir un motor de búsqueda dedicado — no es una limitación del MVP, sino una posible evolución futura
(propuesta técnica §10.2).

## 7. Revisión jurídica final

Ninguno de los cálculos o etiquetas de este sistema (estado de "prescripción" orientativo en `/historial`,
confianza de un match de enriquecimiento o de histórico, clasificación de una sanción) constituye una
valoración jurídica. Son ayudas operativas para priorizar el trabajo, no sustitutos del criterio profesional
de la abogada sobre cada expediente concreto.
