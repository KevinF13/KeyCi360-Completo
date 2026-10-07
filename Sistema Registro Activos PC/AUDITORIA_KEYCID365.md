# Auditoría KEYCID365 — Sistema de Activos de TI

Fecha: 2026-10-05 · Alcance: frontend `kc360/` (React 19, CRA) y backend `Activos_LP_CID/` (FastAPI + PostgreSQL), más el paquete `KEYCID365_despliegue_2026-09-22_v2.zip`.
Marco de diseño: Apple Human Interface Guidelines (HIG), aplicadas a una app web de escritorio y móvil. Las convenciones exclusivas de iOS o macOS (barra de menús, tab bar nativa) no aplican. Sí aplican los principios y los fundamentos: accesibilidad, color, tipografía, layout y redacción.

---

## 1. Resumen

**Calificación de diseño (antes): Necesita trabajo. Después de los cambios: Bien.**
**Calificación de seguridad: Problemas críticos.** Hay que corregirlos antes de exponer el sistema fuera de la red interna.

La app cumple bien su función: un inventario de equipos, accesorios, personal, asignaciones y mantenimiento, con un responsive bien pensado (las tablas pasan a tarjetas con container queries). Visualmente era una plantilla "Flat UI" de 2014 (`#2c3e50`, `#3498db`, `#e74c3c`), con 107 colores hex sueltos, contraste insuficiente en texto secundario y botones, y ningún estilo de foco para teclado. Ya se aplicó una capa de diseño estilo Apple (ver §4).

El problema de fondo no es visual: **la API no tiene autenticación**. El login solo pone `isAuthenticated=true` en `localStorage`. Cualquiera en la red puede llamar `DELETE /equipos/computers/{serial}` directamente.

---

## 2. Seguridad y backend (fuera del HIG, pero lo más urgente)

### Crítico

| # | Hallazgo | Dónde | Corrección |
|---|---|---|---|
| S1 | **Ningún endpoint verifica identidad.** La sesión existe solo en el navegador (`localStorage.isAuthenticated`), así que basta con escribir ese valor en la consola para entrar. La API acepta cualquier petición. | `app.py`, `activos_equipos.py`, `mantenimiento.py` (0 usos de `Depends`) | Emitir un JWT (o una cookie de sesión `HttpOnly`) en `/auth/login` y proteger todos los routers con `dependencies=[Depends(usuario_actual)]`. |
| S2 | **Contraseñas en texto plano.** `INSERT ... (password)` y `WHERE username=%s AND password=%s`. | `login.py:31-35, 56-59` | Usar `bcrypt` (ya está en `requirements.txt`): `bcrypt.hashpw` al registrar y `bcrypt.checkpw` al iniciar sesión. Después, migrar las contraseñas existentes. |
| S3 | **`/auth/register` es público y acepta `role` desde el cliente.** Cualquiera puede crearse un usuario `ADMIN`. | `login.py:27` | Quitar el endpoint o exigir un admin autenticado, y fijar el rol en el servidor. |
| S4 | **El `.env` con credenciales de la BD va dentro del zip de despliegue** (`KEYCID365/backend/.env`), y además hay un `.env.bak`. | zip, carpeta backend | Sacarlo del paquete, rotar la contraseña de la BD y distribuir un `.env.example` sin valores. |

### Alto

- **S5. Fugas de errores internos:** las respuestas incluyen `detail=f"Error ...: {str(e)}"` en unos 70 puntos (`activos_equipos.py` 59, `mantenimiento.py` 12), lo que expone mensajes de PostgreSQL (tablas, constraints). Hay que registrar `e` en el log del servidor y devolver un mensaje genérico.
- **S6. `print()` como log:** 142 llamadas en `activos_equipos.py` que imprimen cédulas y payloads. Conviene usar `logging` y no registrar datos personales.
- **S7. `requirements.txt` está en UTF-16** y mezcla Flask, matplotlib, pywin32, playwright, oracledb y otros paquetes que el backend no usa. Hay que regenerarlo en UTF-8 solo con lo necesario (`fastapi`, `uvicorn`, `psycopg2-binary`, `python-dotenv`, `pydantic`, `bcrypt`).
- **S8. Conexión nueva a PostgreSQL por cada petición** (`get_conn()`). Basta con usar `psycopg2.pool.SimpleConnectionPool`.

### Medio

- **S9. `login.py` hace `except:` sin tipo** y lo convierte todo en "Usuario ya existe".
- **S10. CORS con una IP fija** (`192.168.20.4:4001`) en el código. Hay que pasarla a `CORS_EXTRA_ORIGINS`.
- **S11. Hay un `build/` versionado dentro de `kc360/`** junto al código fuente. Conviene generarlo solo para el despliegue.

---

## 3. Revisión de diseño (HIG)

**Tesis de la pantalla:** "encontrar un equipo por su serie y saber quién lo tiene y en qué estado está". Antes no había nada característico. Ahora el elemento distintivo es la **serie en tipografía monoespaciada**, porque es el identificador real de cada activo.

### Crítico (accesibilidad)

**A1. Contraste insuficiente en texto y botones** (corregido)
- **Qué:** el botón primario, blanco sobre `#3498db`, daba **3.15:1**. El texto secundario `#7f8c8d` sobre blanco daba **3.48:1**, y sobre las cabeceras de tabla `#f8f9fa`, **3.30:1**. Las etiquetas de tarjeta `#95a5a6` daban **2.56:1**, el botón Salir **3.82:1** y el texto naranja `#e67e22` **2.85:1**.
- **Por qué:** `accessibility.md › Vision`: *"Strive to meet color contrast minimum standards"*, con 4.5:1 para texto de hasta 17 pt.
- **Corrección aplicada:** acento `#0071e3` (blanco encima: **4.70:1**), secundario `#6e6e73` (**5.07:1**), rojo `#d70015` (**5.38:1**) y naranja `#b25000` sobre su tinte (**4.72:1**). Todas las etiquetas de estado superan 4.5:1 sobre su fondo.

**A2. Sin indicador de foco para teclado** (corregido)
- **Qué:** los campos tenían `outline: none` y no había ningún estilo `:focus-visible`, así que quien usa solo teclado no ve dónde está.
- **Por qué:** `accessibility.md › Speech`: *"Let people use the keyboard alone to navigate and interact with your app."*
- **Corrección aplicada:** anillo de foco global de 3 px `rgba(0,113,227,.45)` con `:focus-visible`, y halo azul en los campos.

**A3. Campos del login sin etiqueta asociada** (corregido)
- **Qué:** `<label>Usuario</label>` no tenía `htmlFor`, así que un lector de pantalla anunciaba "campo de texto, vacío".
- **Corrección aplicada:** se añadieron `id` y `htmlFor`, `autoComplete="username"` y `"current-password"`, y `role="alert"` en el mensaje de error.

**A4. Botones de solo ícono sin nombre accesible** (corregido en paginación; **pendiente** en tablas)
- **Qué:** los botones « ‹ › » solo tenían `title`. Los botones de ícono de las tablas (`btn-icon`, `btn-icon-action`) en Activos y Accesorios tampoco llevan `aria-label`.
- **Por qué:** `accessibility.md › Mobility`: *"make sure your interface elements are appropriately labeled"*.
- **Corrección:** se añadió `aria-label` en la paginación. **Pendiente:** añadirlo en cada botón de ícono de las tablas, por ejemplo `aria-label={`Generar acta de ${e.numero_serie}`}`.

### Mejoras

**D1. [Alto] 42 `alert()` / `window.confirm()` como sistema de feedback** (pendiente)
- **Qué:** Activos (15), Personas (8), Accesorios, Asignaciones y Dashboard (6 cada uno), `pdfGenerator.js` (1). Los éxitos rutinarios ("Guardado") interrumpen con un diálogo del navegador.
- **Por qué:** `alerts.md › Best practices`: *"Avoid using an alert merely to provide information."* Y `feedback.md`: *"Consider integrating status feedback into your interface."*
- **Corrección:** reutilizar el sistema de toasts que ya existe en Mantenimiento (`mt-toasts`) como un componente `<Toasts/>` común. Dejar `confirm` solo para acciones destructivas que no se pueden deshacer (eliminar un equipo o desasignarlo todo), con un modal propio cuyos botones digan "Eliminar" / "Cancelar" en lugar de Aceptar / Cancelar.

**D2. [Alto] Paleta sin semántica, con 107 colores literales** (corregido en la capa de tema)
- **Por qué:** `color.md › Best practices`: *"Avoid using the same color to mean different things."* Y `dark-mode.md › Dark Mode colors`: *"Avoid using hard-coded color values."*
- **Corrección aplicada:** `theme.css` define tokens con un rol cada uno (`--kc-label`, `--kc-label-2`, `--kc-accent`, `--kc-red`, etc.). El azul se usa solo para acciones y selección, y los estados tienen su propio color.

**D3. [Medio] No hay modo oscuro** (pendiente, preparado)
- **Por qué:** `dark-mode.md › Best practices`: *"Ensure that your app looks good in both appearance modes."*
- **Por qué no se activó todavía:** quedan unos 40 estilos inline con colores fijos (`color:'#666'`, `'#999'` en `Dashboard.js` y `Activos.js`) y los colores de Recharts, que se verían ilegibles sobre fondo oscuro. Primero hay que reemplazarlos por clases. Después basta con añadir `@media (prefers-color-scheme: dark)` con valores oscuros en `:root` (fondo `#000`/`#1c1c1e`, acento `#0a84ff`, secundario `#98989d` a 5.93:1). Sin un interruptor propio de la app (`dark-mode.md`: *"Avoid offering an app-specific appearance setting"*).

**D4. [Medio] Controles pequeños** (corregido)
- **Qué:** los botones de paginación medían 30–34 px y los de ícono unos 28 px con padding de 6 px.
- **Por qué:** `accessibility.md › Mobility`: mínimo 28×28 en escritorio y 44×44 en móvil.
- **Corrección aplicada:** todos los botones de ícono miden 32×32 como mínimo, el menú móvil y el login 44 px, y los campos 36 px.

**D5. [Medio] KPIs con franja lateral de color y efecto de elevación al pasar el mouse** (corregido)
- **Qué:** las 6 tarjetas usaban 6 colores de borde distintos, aunque no son interactivas, y aun así "saltaban" al pasar el mouse. Eso sugiere que se pueden pulsar cuando no es así.
- **Corrección aplicada:** ícono en un recuadro tintado, como en Ajustes de iOS/macOS, sin franja lateral ni elevación, y números con `tabular-nums`. En Mantenimiento, donde los KPIs sí filtran, se conserva el estado activo con un borde de 2 px.

**D6. [Medio] Redacción**
- "Salir" ahora dice "Cerrar sesión", y en el login "Entrar / Cargando..." ahora dice "Iniciar sesión / Iniciando sesión…". La acción conserva el mismo nombre en todo el flujo (`writing.md`).
- **Pendiente:** unificar las mayúsculas. Hoy conviven "Nuevo Activo" (estilo título) y "Registrar mantenimiento" (estilo oración). Para una app en español se recomienda el estilo oración en toda la interfaz.
- **Pendiente:** el error "Error de conexión con el servidor" debería decir qué hacer: "No se pudo conectar con el servidor. Verifica que el backend esté en ejecución e inténtalo de nuevo."

**D7. [Bajo] `Navbar.js` / `Navbar.css` no se usan** (código muerto). Se pueden eliminar.

### Notas de oficio

- **Punto de vista:** es una herramienta interna y discreta, y está bien que lo sea. La identidad se concentra en un solo lugar: la serie del equipo en monoespaciada, el único dato que el área de Sistemas usa de verdad para hablar de un equipo. Todo lo demás es tranquilo y de sistema.
- **Tipografía:** la del sistema (SF en Mac, Segoe UI Variable en Windows), sin cargar fuentes externas. Es lo correcto para una herramienta de trabajo (`typography.md › Using system fonts`). La jerarquía se marca con peso y tamaño: títulos de 32 px/700 con tracking negativo y cuerpo de 15 px.
- **Qué se quitó:** las franjas de color de los KPIs, los bordes de las tarjetas (la sombra suave basta) y el rojo sólido del botón de salir.

### Lo que funciona (conservar)

- **Tablas que pasan a tarjetas** con container queries (`App.css`, `tablasResponsivas.js`). Es una solución muy buena y poco común: cada fila se lee como "etiqueta: valor" sin desplazamiento horizontal.
- **Menú lateral que se convierte en cajón** en pantallas de menos de 992 px, con cierre por Esc y al navegar.
- **Hojas modales que suben desde abajo en móvil**, con el patrón correcto de *sheet*. Ahora llevan asa (*grabber*).
- **Mantenimiento** tiene toasts, orden por columnas, segmentado y avisos en contexto. Es el módulo más maduro y sirve de referencia para los demás.
- **Pruebas de API** (`tests/test_api.py`, unas 25 KB) que solo corren contra una copia local.

---

## 4. Cambios aplicados

| Archivo | Cambio |
|---|---|
| `kc360/src/theme.css` (**nuevo**) | Capa de diseño estilo Apple: tokens semánticos, menú lateral translúcido tipo *source list* de macOS, tarjetas con radio de 18 px, botones tipo píldora, pestañas como control segmentado, campos con halo de foco, etiquetas de estado tintadas, modales como hojas con animación, paginación, login. Respeta `prefers-reduced-motion`, `prefers-reduced-transparency` y `prefers-contrast`. |
| `kc360/src/App.js` | Importa `theme.css` al final, después de `App.css`. |
| `kc360/src/components/Sidebar.js` | `<aside aria-label>`, `aria-current="page"` en el enlace activo y "Cerrar sesión". |
| `kc360/src/components/Paginacion.js` | `aria-label` y `aria-current` en los botones. |
| `kc360/src/pages/Login.js` | Etiquetas asociadas, `autoComplete`, `autoFocus`, `role="alert"` y nuevos textos. |
| `kc360/src/pages/Dashboard.js` | Se quitaron los estilos inline del KPI "teal" que contradecían el tema. |

**Verificación:** `react-scripts build` compila sin errores. El único warning (`exhaustive-deps` en `Dashboard.js:40`) ya existía. Se capturaron Login, Dashboard, Activos y Mantenimiento a 1400 px y Activos a 390 px. No se probó con datos reales porque requiere el backend y la BD.

**Para revertir:** quitar la línea `import './theme.css'` de `App.js`. El resto de los cambios en JS son solo de accesibilidad y textos.

**Para desplegar:** volver a ejecutar `npm run build` en `kc360/`. El `build/` actual y el zip son anteriores a estos cambios.

---

## 5. Orden de trabajo recomendado

1. **Seguridad (S1–S4):** autenticación en la API, bcrypt, cerrar `/register`, sacar el `.env` del zip y rotar la clave de la BD.
2. **Accesibilidad pendiente (A4):** `aria-label` en los botones de ícono de las tablas.
3. **Feedback (D1):** reemplazar `alert()` por toasts y `confirm()` por un modal destructivo propio.
4. **Limpieza de estilos inline** y después el **modo oscuro (D3)**.
5. **Backend (S5–S8):** errores genéricos, logging, `requirements.txt` limpio y pool de conexiones.
