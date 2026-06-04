```markdown
# Sistema de Diseño: Autoridad Editorial y Claridad Institucional

Este documento detalla las directrices visuales y funcionales para la aplicación de gestión de multas del BOE. El enfoque trasciende la interfaz administrativa convencional, adoptando una estética de **"Minimalismo Autoritario"**. No se trata solo de gestionar datos, sino de proyectar confianza, legalidad y una experiencia de usuario sin fricciones mediante el uso magistral del espacio y la jerarquía tonal.

---

## 1. Norte Creativo: El Administrador Silencioso
El sistema se rige bajo el concepto de **"Claridad Soberana"**. Evitamos el desorden visual de las aplicaciones gubernamentales tradicionales. En su lugar, utilizamos una disposición editorial donde el contenido respira. La confianza no se construye con líneas divisorias, sino con una estructura impecable, una tipografía legible y una profundidad sutil que guía al usuario de manera natural.

---

## 2. Paleta de Colores y Capas Tonales

La paleta se aleja de los contrastes agresivos para abrazar una jerarquía basada en la luminosidad y la profundidad.

### Jerarquía de Superficies (El Sistema de Capas)
Queda estrictamente prohibido el uso de bordes de 1px para separar secciones. La estructura se define mediante el cambio de fondo:
- **Base del Canvas:** `surface` (#f7fafc). El lienzo principal sobre el cual descansa todo.
- **Contenedores de Nivel 1:** `surface_container_low` (#f1f4f6) para áreas de contenido secundario.
- **Tarjetas y Áreas de Enfoque:** `surface_container_lowest` (#ffffff) para elevar el contenido prioritario sobre el fondo.
- **Nesting (Anidamiento):** Para crear profundidad, coloca un elemento `surface_container_highest` (#e0e3e5) dentro de un área `surface` para denotar una acción o información técnica.

### La Regla del "Vidrio y Degradado"
Para evitar un aspecto plano y genérico:
- **CTAs Principales:** Utiliza un degradado sutil desde `primary` (#002045) hacia `primary_container` (#1a365d) en un ángulo de 135°. Esto aporta una "vibración" profesional que el color plano no posee.
- **Elementos Flotantes:** Para modales o notificaciones, emplea efectos de *Glassmorphism* usando `surface_container_lowest` con una opacidad del 80% y un `backdrop-blur` de 12px.

---

## 3. Tipografía Editorial

Utilizamos **Inter** como eje central por su equilibrio entre modernidad y formalidad.

- **Display (display-lg/md):** Reservado para cifras de multas totales o estados de cuenta de alto impacto. Transmite la autoridad del BOE.
- **Headline (headline-sm):** Títulos de secciones. Debe usarse con un `letter-spacing` ligeramente negativo (-0.02em) para una apariencia más compacta y premium.
- **Body (body-lg):** El estándar para lectura de artículos de leyes o detalles de infracciones.
- **Label (label-md):** Siempre en mayúsculas con un `letter-spacing` de 0.05em cuando se use en encabezados de tablas o etiquetas de estado.

---

## 4. Elevación y Profundidad: Adiós a la Estructura Rígida

### Tonal Layering (Capas Tonales)
En lugar de sombras paralelas tradicionales, la profundidad se logra "apilando" los tokens de superficie. Una tarjeta blanca (`surface_container_lowest`) sobre un fondo gris pálido (`surface`) ya comunica elevación sin necesidad de efectos visuales pesados.

### Sombras Ambientales
Si un elemento requiere flotar (como un menú desplegable):
- **Sombra:** `0px 10px 30px rgba(24, 28, 30, 0.06)`. El color de la sombra debe ser una versión diluida de `on_surface`, nunca gris puro o negro.

### El "Ghost Border" (Borde Fantasma)
Si la accesibilidad exige un límite visual, usa el token `outline_variant` con una opacidad reducida al 15%. Nunca uses bordes opacos al 100%.

---

## 5. Componentes de Firma

### Botones de Gran Formato
Los botones deben ser generosos, transmitiendo seguridad en la acción.
- **Primario:** Fondo degradado `primary` a `primary_container`, texto en `on_primary`. Radio de curvatura: `lg` (0.5rem).
- **Sizing:** Padding vertical de `3.5` (1.2rem) y horizontal de `6` (2rem).
- **Interacción:** En `hover`, el botón debe aumentar ligeramente su sombra ambiental, no cambiar drásticamente de color.

### Campos de Entrada (Inputs)
- **Estilo:** Sin borde inferior ni bordes marcados. Fondo en `surface_container_high` con un radio `md`.
- **Foco:** Un cambio sutil a `surface_container_lowest` y un "Ghost Border" en `primary`.

### Listas y Tablas de Infracciones
- **Prohibición:** No usar líneas divisorias horizontales entre filas.
- **Alternativa:** Usar un espaciado de `2.5` (0.85rem) entre filas y un cambio de color de fondo al pasar el cursor (`hover`) a `surface_container_low`.

### Chips de Estado
- **Pendiente:** Fondo `tertiary_fixed`, texto `on_tertiary_fixed_variant`.
- **Pagado:** Fondo `secondary_container`, texto `on_secondary_container`.
- **Anulado:** Fondo `error_container`, texto `on_error_container`.

---

## 6. Do's and Don'ts (Prácticas Recomendadas)

### Sí (Do)
- **Espacio en blanco como herramienta:** Deja que los datos "respiren". Usa la escala de espaciado `8` (2.75rem) entre secciones mayores.
- **Iconografía lineal:** Usa iconos de trazo fino (1.5px) y minimalistas que complementen la tipografía Inter.
- **Asimetría intencionada:** En el dashboard, permite que las tarjetas de resumen tengan anchos variados para romper la monotonía de la rejilla.

### No (Don't)
- **No uses sombras pesadas:** Evita cualquier sombra que distraiga del contenido. La interfaz debe sentirse ligera, no cargada.
- **No uses divisores:** Si sientes que necesitas una línea, probablemente necesites más espacio en blanco (`spacing-5` o superior).
- **No mezcles alineaciones:** Mantén una alineación a la izquierda rigurosa para todo el texto editorial para preservar el orden legal.

---

## 7. Tokens de Referencia

| Atributo | Token Primario | Valor |
| :--- | :--- | :--- |
| Radio Principal | `rounded-lg` | 0.5rem |
| Espaciado Estándar | `spacing-4` | 1.4rem |
| Color de Texto Principal | `on_surface` | #181c1e |
| Color de Acento | `primary` | #002045 |
| Fondo de Aplicación | `surface` | #f7fafc |

Este sistema no es solo una guía visual; es el marco de trabajo para construir una herramienta que proyecte la seriedad del BOE con la modernidad de la web actual.```