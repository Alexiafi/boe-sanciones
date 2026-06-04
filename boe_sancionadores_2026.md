# Extracción diaria de publicaciones sancionadoras del BOE en 2026

## 1. Objetivo

Montar un proceso **diario, robusto y auditable** que detecte y extraiga del BOE las publicaciones de carácter **sancionador** usando primero las **fuentes oficiales del propio BOE** y evitando scraping innecesario.  
La idea base en 2026 es:

1. Obtener el **sumario oficial diario** del BOE.
2. Recorrer todos los documentos publicados ese día.
3. Aplicar una **clasificación por reglas** para decidir si cada documento es “sancionador”.
4. Descargar y parsear el **XML del documento** cuando exista, y usar el HTML solo como respaldo.
5. Persistir el resultado con trazabilidad completa: fecha BOE, identificador BOE, título, sección, organismo, URLs oficiales y texto extraído.

---

## 2. Qué fuente usar en 2026: recomendación principal

La fuente recomendada no es scraping HTML “a pelo”, sino la **API oficial de datos abiertos del BOE**. La propia AEBOE publica una API REST para reutilizar el sumario del diario oficial, y la documentación técnica del sumario BOE indica que la llamada oficial es:

`/datosabiertos/api/boe/sumario/{fecha}`

La API funciona sobre HTTPS con `GET`, admite salida **JSON o XML** y devuelve para cada documento del sumario sus metadatos y las URLs oficiales de **PDF, HTML y XML**.  
Referencia oficial:

- API de datos abiertos del BOE: https://www.boe.es/datosabiertos/api/api.php
- FAQ BOE datos abiertos: https://www.boe.es/datosabiertos/faq/boe.php
- Documentación técnica del sumario BOE (PDF): https://www.boe.es/datosabiertos/documentos/APIsumarioBOE.pdf

### Por qué esta debe ser la vía principal

Porque el propio BOE expone exactamente lo que necesitamos para un pipeline diario:

- sumario por fecha;
- metadatos estructurados;
- identificador único del documento;
- enlaces oficiales al contenido;
- formato legible por máquina.

Eso hace que, para este caso, **Scrapling no sea la primera opción**. Puede tener sentido como **fallback** para inspección, depuración o recuperación de HTML si hubiera alguna incidencia puntual, pero **no como motor principal**, porque aquí ya existe una API oficial estable y documentada.

---

## 3. Endpoint oficial mínimo que hay que usar

## 3.1. Sumario diario

Ejemplo:

```bash
curl -L -X GET \
  -H "Accept: application/json" \
  "https://www.boe.es/datosabiertos/api/boe/sumario/20260306"
```

También sirve en XML cambiando el header `Accept`.

### Qué devuelve

El sumario devuelve un nodo raíz con:

- `status`
- `data.sumario.metadatos`
- `data.sumario.diario`

Y dentro del diario aparecen las secciones, departamentos, epígrafes e `item` con campos como:

- `identificador`
- `titulo`
- `url_pdf`
- `url_html`
- `url_xml`

Esto está documentado oficialmente por la AEBOE en la especificación del sumario.

---

## 4. Qué documentos considerar “sancionadores”

Aquí conviene ser muy preciso: en BOE aparecen **dos grandes familias** que suelen interesar en este proyecto, y además hay **falsos positivos** importantes.

## 4.1. Familia A: anuncios/notificaciones de expedientes sancionadores

Suelen aparecer en:

- **Sección V. Anuncios**
- muy a menudo en **V. Anuncios - B. Otros anuncios oficiales**
- normalmente con identificadores tipo **BOE-B-...**

Ejemplo real del BOE:

- **BOE-B-2024-18415**: “Anuncio ... por el que se notifica la propuesta de resolución del procedimiento sancionador incoado ...”  
  https://www.boe.es/diario_boe/txt.php?id=BOE-B-2024-18415

Este tipo de publicaciones suele contener expresiones como:

- `procedimiento sancionador`
- `expediente sancionador`
- `notificación de resolución`
- `propuesta de resolución`
- `sanción`
- `multa`
- `infracción`
- `incoado`
- `responsable`
- `pago voluntario`

## 4.2. Familia B: publicaciones oficiales de sanciones ya impuestas o firmes

No siempre están en anuncios. A veces aparecen en:

- **Sección III. Otras disposiciones**
- con identificadores tipo **BOE-A-...**

Ejemplo real:

- **BOE-A-2025-2496**: “Resolución ... por la que se publican las sanciones por infracciones ...”  
  https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-2496

Este tipo también debe entrar si el objetivo es capturar **todo lo sancionador publicado**, no solo notificaciones de expedientes.

## 4.3. Falsos positivos importantes

No todo lo que contiene la palabra `sancionador` es un expediente o una sanción concreta. El BOE publica también **normas** y **resoluciones organizativas** sobre régimen sancionador, procedimiento sancionador o unidades de apoyo.

Ejemplos reales de falsos positivos:

- normas que regulan “el procedimiento sancionador”;
- leyes o decretos cuyo texto menciona “régimen sancionador”;
- resoluciones organizativas o de coordinación.

Por eso no basta con buscar la palabra `sancionador` en bruto.

---

## 5. Estrategia recomendada de detección

Mi recomendación es una estrategia en **dos fases**:

## Fase 1: candidatos desde el sumario oficial

De cada `item` del sumario diario, construir un registro con:

- `fecha_publicacion`
- `identificador`
- `titulo`
- `seccion_codigo`
- `seccion_nombre`
- `departamento_codigo`
- `departamento_nombre`
- `epigrafe_nombre`
- `url_html`
- `url_xml`
- `url_pdf`

Después marcar como **candidato sancionador** si cumple al menos una de estas reglas.

### Regla A: título claramente sancionador

Incluir si el título contiene alguno de estos términos o patrones:

- `expediente sancionador`
- `procedimiento sancionador`
- `sanciones`
- `sanción`
- `multa`
- `infracción`
- `propuesta de resolución`
- `notificación de resolución`
- `incoado`
- `revocación de procedimientos sancionadores`

### Regla B: combinación de sección + léxico

Dar prioridad alta si:

- `seccion_nombre` contiene `V. Anuncios`
- o `seccion_nombre` contiene `Otros anuncios oficiales`
- y el título contiene términos como `sanción`, `multa`, `infracción`, `expediente`, `notificación`

### Regla C: publicaciones firmes en Sección III

Incluir también si:

- `seccion_nombre == "III. Otras disposiciones"`
- y el título contiene `publican las sanciones`, `sanciones por infracciones`, `multa`, `infracción`

## Fase 2: verificación con el XML o HTML del documento

Una vez detectado el candidato, descargar `url_xml` y validar con señales internas:

- presencia de `multa`;
- presencia de `infracción grave`, `infracción muy grave`, `infracción leve`;
- `expediente`;
- `procedimiento sancionador`;
- `responsable`;
- `pago voluntario`;
- `reducción de la sanción`;
- referencias legales de potestad sancionadora.

Si el XML falla o no está disponible, usar `url_html`.

---

## 6. Regla práctica para minimizar ruido

Usa una política de clasificación por niveles:

### Nivel 1: alta confianza
Entrar directamente si aparece alguno de estos patrones:

- `expediente sancionador`
- `procedimiento sancionador`
- `publican las sanciones`
- `sanciones por infracciones`
- `propuesta de resolución del procedimiento sancionador`

### Nivel 2: confianza media
Entrar si coinciden al menos **2 señales** entre:

- `sanción`
- `multa`
- `infracción`
- `notificación`
- `resolución`
- `expediente`

y además el documento está en **Sección III** o **Sección V**.

### Nivel 3: revisión manual / cola de QA
Mandar a revisión si aparece `régimen sancionador` o `procedimiento sancionador` pero el documento parece una norma general (`Ley`, `Real Decreto`, `Orden`, etc.).

---

## 7. Arquitectura técnica recomendada en 2026

## Opción recomendada

- **Python 3.12**
- **httpx** para cliente HTTP
- **lxml** o `xml.etree.ElementTree` para XML
- **pydantic v2** para validar el esquema interno
- **tenacity** para reintentos
- **dateutil** para fechas
- **sqlite / postgres** para persistencia
- **parquet** opcional para analítica
- **structlog** o `logging` JSON para observabilidad

### Por qué no arrancaría con scraping agente-first

Porque el BOE ya da:

- API oficial,
- estructura,
- URLs XML,
- HTML,
- PDF.

En este proyecto, lo más moderno no es usar agentes porque sí, sino **usar primero la fuente oficial machine-readable** y dejar las librerías de scraping inteligente como respaldo.

---

## 8. Dónde encaja Scrapling

Scrapling existe y sigue activo en 2026; en PyPI figura la versión `0.4.1` publicada el 27 de febrero de 2026, y su repositorio oficial lo presenta como framework de scraping adaptativo.

Referencias:

- PyPI Scrapling: https://pypi.org/project/scrapling/
- GitHub Scrapling: https://github.com/D4Vinci/Scrapling
- Docs: https://scrapling.readthedocs.io/en/latest/index.html

### Mi recomendación realista

Usarlo solo para alguna de estas situaciones:

1. **Fallback HTML** si un documento concreto falla con `httpx` por alguna rareza de markup.
2. **Inspección exploratoria** para entender cambios de estructura.
3. **Recuperación de texto** si una página HTML específica no se deja parsear cómodamente con XPath/CSS clásico.
4. **QA semántica** en una etapa aparte, nunca como única fuente de verdad.

### Lo que no haría

No montaría un pipeline diario del BOE cuyo núcleo dependiera de navegación “agéntica” o de scraping stealth cuando existe una API oficial del organismo.

---

## 9. Modelo de datos recomendado

```json
{
  "boe_id": "BOE-B-2024-18415",
  "fecha_publicacion": "2024-05-21",
  "diario_numero": 123,
  "seccion_codigo": "5",
  "seccion_nombre": "V. Anuncios",
  "departamento_codigo": "....",
  "departamento_nombre": "Comisión Nacional de los Mercados y la Competencia",
  "epigrafe_nombre": "B. Otros anuncios oficiales",
  "titulo": "Anuncio ... procedimiento sancionador ...",
  "familia_sancionadora": "anuncio_expediente|sancion_firme|otro",
  "confidence": 0.97,
  "match_rules": ["title:procedimiento sancionador", "section:V", "body:multa"],
  "url_html": "...",
  "url_xml": "...",
  "url_pdf": "...",
  "texto_plano": "...",
  "organismo_emisor": "...",
  "expediente": "...",
  "persona_o_entidad": "...",
  "importe_multa_eur": 355000.0,
  "tipo_infraccion": "grave|muy grave|leve|null",
  "estado_publicacion": "propuesta|notificacion|resolucion|sancion_firme|revocacion|desconocido",
  "hash_texto": "...",
  "first_seen_at": "2026-03-06T06:05:00Z",
  "source": "boe_api_sumario"
}
```

---

## 10. Campos que merece la pena extraer del contenido

Además de metadatos del sumario, yo intentaría extraer del XML/HTML:

- **expediente / referencia interna** (`Expediente: XXX/2024`, `referencia SNC/...`)
- **organismo emisor**
- **nombre de la persona o entidad afectada**
- **NIF/CIF parcialmente anonimizado, si aparece**
- **tipo de actuación**:
  - incoación,
  - propuesta de resolución,
  - notificación,
  - resolución,
  - sanción firme,
  - revocación
- **tipo de infracción**:
  - leve,
  - grave,
  - muy grave
- **importe de multa**
- **plazos**:
  - alegaciones,
  - recursos,
  - pago voluntario
- **base legal**:
  - ley / artículo citado
- **dominio material**:
  - postal,
  - mercado de valores,
  - aguas,
  - transportes,
  - auditoría,
  - etc.

---

## 11. Dedupe y trazabilidad

Usa como clave natural principal:

- `boe_id`

Y como defensas adicionales:

- `hash_texto`
- `(fecha_publicacion, titulo, organismo_emisor)`

### Regla
Si vuelve a aparecer el mismo `boe_id`, se actualiza el registro, no se duplica.

---

## 12. Flujo ETL diario recomendado

## Paso 1
Determinar la fecha BOE a procesar.

## Paso 2
Llamar a:

`https://www.boe.es/datosabiertos/api/boe/sumario/{AAAAMMDD}`

## Paso 3
Normalizar el JSON/XML a una lista plana de documentos.

## Paso 4
Aplicar reglas de candidatura sancionadora sobre:

- título,
- sección,
- epígrafe,
- departamento.

## Paso 5
Para cada candidato:
- descargar `url_xml`;
- parsear texto;
- extraer entidades y señales;
- clasificar la publicación.

## Paso 6
Persistir resultado estructurado.

## Paso 7
Guardar también un artefacto de auditoría:
- JSON crudo del sumario,
- XML crudo del documento,
- timestamp de ingesta,
- versión del clasificador/reglas.

## Paso 8
Emitir métricas:
- total docs del día,
- total candidatos,
- total sancionadores confirmados,
- falsos positivos revisados,
- errores de descarga,
- tiempo medio por documento.

---

## 13. Clasificador inicial por reglas

Un baseline muy razonable para empezar:

```python
SANCTION_PATTERNS_STRONG = [
    r"\bexpediente sancionador\b",
    r"\bprocedimiento sancionador\b",
    r"\bpropuesta de resolución\b",
    r"\bnotificación de resolución\b",
    r"\bpublican las sanciones\b",
    r"\bsanciones por infracciones\b",
]

SANCTION_PATTERNS_MEDIUM = [
    r"\bsanción(?:es)?\b",
    r"\bmulta(?:s)?\b",
    r"\binfracci[oó]n(?:es)?\b",
    r"\bexpediente\b",
    r"\bnotificaci[oó]n\b",
    r"\bresoluci[oó]n\b",
    r"\bincoad[oa]\b",
]
```

### Heurística sencilla

- Si hay match con `STRONG` => candidato directo.
- Si hay al menos 2 matches de `MEDIUM` y el documento está en Sección III o V => candidato.
- Si el título empieza por `Ley`, `Real Decreto`, `Orden` y el match es solo `régimen sancionador` => mandar a revisión, no incluir automáticamente.

---

## 14. Pseudocódigo del pipeline

```python
from __future__ import annotations

import re
import httpx
from datetime import date
from typing import Any

BOE_SUMMARY_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{yyyymmdd}"

STRONG = [
    re.compile(r"\bexpediente sancionador\b", re.I),
    re.compile(r"\bprocedimiento sancionador\b", re.I),
    re.compile(r"\bpropuesta de resolución\b", re.I),
    re.compile(r"\bnotificación de resolución\b", re.I),
    re.compile(r"\bpublican las sanciones\b", re.I),
    re.compile(r"\bsanciones por infracciones\b", re.I),
]

MEDIUM = [
    re.compile(r"\bsanción(?:es)?\b", re.I),
    re.compile(r"\bmulta(?:s)?\b", re.I),
    re.compile(r"\binfracci[oó]n(?:es)?\b", re.I),
    re.compile(r"\bexpediente\b", re.I),
    re.compile(r"\bnotificaci[oó]n\b", re.I),
    re.compile(r"\bresoluci[oó]n\b", re.I),
    re.compile(r"\bincoad[oa]\b", re.I),
]

NORMATIVE_PREFIXES = (
    "ley ",
    "real decreto ",
    "real decreto-ley ",
    "orden ",
)

def fetch_summary(yyyymmdd: str) -> dict[str, Any]:
    url = BOE_SUMMARY_URL.format(yyyymmdd=yyyymmdd)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()

def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

def flatten_summary(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # Nota: aquí hay que normalizar diario/seccion/departamento/epigrafe/item
    # porque en BOE a veces pueden venir como objeto único o como lista.
    docs = []
    sumario = payload["data"]["sumario"]

    for diario in ensure_list(sumario.get("diario")):
        diario_numero = diario.get("numero")
        for seccion in ensure_list(diario.get("seccion")):
            sec_codigo = seccion.get("codigo")
            sec_nombre = seccion.get("nombre")
            for depto in ensure_list(seccion.get("departamento")):
                dep_codigo = depto.get("codigo")
                dep_nombre = depto.get("nombre")
                for epigrafe in ensure_list(depto.get("epigrafe")):
                    epi_nombre = epigrafe.get("nombre")
                    for item in ensure_list(epigrafe.get("item")):
                        docs.append(
                            {
                                "diario_numero": diario_numero,
                                "seccion_codigo": sec_codigo,
                                "seccion_nombre": sec_nombre,
                                "departamento_codigo": dep_codigo,
                                "departamento_nombre": dep_nombre,
                                "epigrafe_nombre": epi_nombre,
                                "identificador": item.get("identificador"),
                                "titulo": item.get("titulo", ""),
                                "url_html": item.get("url_html"),
                                "url_xml": item.get("url_xml"),
                                "url_pdf": item.get("url_pdf"),
                            }
                        )
    return docs

def is_candidate(doc: dict[str, Any]) -> tuple[bool, list[str]]:
    title = (doc.get("titulo") or "").lower()
    section = (doc.get("seccion_nombre") or "").lower()

    reasons = []

    for pat in STRONG:
        if pat.search(title):
            reasons.append(f"strong:{pat.pattern}")

    if reasons:
        return True, reasons

    medium_hits = [pat.pattern for pat in MEDIUM if pat.search(title)]
    if len(medium_hits) >= 2 and ("iii." in section or "v." in section):
        return True, [f"medium:{p}" for p in medium_hits]

    if title.startswith(NORMATIVE_PREFIXES) and "régimen sancionador" in title:
        return False, ["likely_normative_false_positive"]

    return False, []

def run_daily(yyyymmdd: str):
    payload = fetch_summary(yyyymmdd)
    docs = flatten_summary(payload)
    candidates = []

    for doc in docs:
        ok, reasons = is_candidate(doc)
        if ok:
            doc["match_rules"] = reasons
            candidates.append(doc)

    return candidates
```

---

## 15. Extracción del XML del documento

Siempre que exista `url_xml`, úsala como fuente de texto preferente.  
Razones:

- estructura mejor que PDF;
- menos ruido;
- más fácil para XPath y regex;
- mejor trazabilidad;
- evita OCR.

### Regla práctica
Orden de preferencia por documento:

1. `url_xml`
2. `url_html`
3. `url_pdf` solo si no queda otra

---

## 16. Qué pruebas haría antes de pasar a producción

## Prueba 1: backfill corto
Procesar los últimos **30 días** y revisar una muestra manual.

## Prueba 2: backfill medio
Procesar **12 meses** y medir:
- recall aproximado,
- precisión,
- organismos más frecuentes,
- tipos de falsos positivos.

## Prueba 3: conjunto oro
Crear un dataset manual de unas **300-500 publicaciones** etiquetadas:
- sancionador sí/no,
- tipo de publicación,
- importe multa sí/no,
- expediente sí/no.

## Prueba 4: estabilidad estructural
Validar que el parser aguanta:
- uno o varios diarios;
- uno o varios epígrafes;
- items únicos vs listas;
- documentos sin ciertos campos.

---

## 17. Salida mínima útil para negocio

Como mínimo, yo devolvería por cada documento:

- `boe_id`
- `fecha_publicacion`
- `titulo`
- `seccion_nombre`
- `departamento_nombre`
- `familia_sancionadora`
- `expediente`
- `persona_o_entidad`
- `importe_multa_eur`
- `tipo_infraccion`
- `estado_publicacion`
- `url_html`
- `url_xml`
- `url_pdf`

---

## 18. Programación del job diario

Opciones razonables:

- **GitHub Actions** si el volumen es pequeño y basta con ejecución diaria.
- **AWS Lambda + EventBridge** si queréis serverless.
- **ECS/Fargate** o contenedor programado si luego crecerá bastante.
- **Airflow / Dagster** solo si esto va a convivir con más pipelines de datos.

### Mi recomendación
Si queréis arrancar rápido:
- repositorio Python,
- job diario en GitHub Actions,
- artefactos crudos versionados en S3 o bucket equivalente,
- base de datos Postgres.

---

## 19. Consideraciones legales y de reutilización

La propia AEBOE publica esta información para descarga y reutilización mediante su API de datos abiertos. Aun así, conviene mantener en el sistema la atribución de fuente y no presentar el dato reutilizado como si fuese una publicación oficial propia.

Referencias:
- https://www.boe.es/datosabiertos/api/api.php
- https://www.boe.es/datosabiertos/faq/boe.php
- https://www.boe.es/informacion/aviso_legal/index.php

---

## 20. Recomendación final de implementación

### Lo que yo haría
**Versión 1**
- API oficial del sumario BOE
- parsing JSON
- filtro por reglas sobre título + sección
- descarga de XML por documento candidato
- extracción regex/XPath
- persistencia en Postgres

**Versión 2**
- añadir clasificación híbrida reglas + modelo ligero
- cola de revisión manual para falsos positivos
- métricas de precisión y recall
- dashboards

**Versión 3**
- normalización por dominio sancionador
- enriquecimiento de entidades
- alertas por organismo / importe / sector

### Decisión técnica importante
Para este proyecto, en 2026, lo correcto es **API-first** y **XML-first**.  
Scrapling puede entrar como herramienta auxiliar, pero no debería sustituir al acceso oficial del BOE.

---

## 21. Referencias verificables

1. API de datos abiertos del BOE  
   https://www.boe.es/datosabiertos/api/api.php

2. FAQ oficial de reutilización BOE  
   https://www.boe.es/datosabiertos/faq/boe.php

3. Documentación oficial de la API de sumario BOE  
   https://www.boe.es/datosabiertos/documentos/APIsumarioBOE.pdf

4. Ejemplo real de anuncio sancionador en Sección V  
   https://www.boe.es/diario_boe/txt.php?id=BOE-B-2024-18415

5. Ejemplo real de publicación de sanciones firmes en Sección III  
   https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-2496

6. Aviso legal y condiciones generales de reutilización  
   https://www.boe.es/informacion/aviso_legal/index.php

7. Scrapling en PyPI  
   https://pypi.org/project/scrapling/

8. Repositorio oficial de Scrapling  
   https://github.com/D4Vinci/Scrapling

9. Documentación de Scrapling  
   https://scrapling.readthedocs.io/en/latest/index.html
