# Clasificación de la revisión de Codex (FINAL_REVIEW, 2026-10-05)

Veredicto de Codex: **REJECT**. El Gate 9 queda **bloqueado** hasta resolver los Critical y High.

| # | Severidad | Hallazgo | Clasificación | Acción |
|---|---|---|---|---|
| C1 | Critical | `.env` con credenciales de producción versionado desde el commit inicial | **Válido, confirmado.** El repo `KevinF13/KeyCi360-Completo` es **público** y el commit inicial ya está en `origin`. | Hecho en local: `.gitignore` nuevo; `.env` y `__pycache__` dejan de rastrearse (`git rm --cached`, sin commit). **Requiere al dueño:** rotar `DB_PASSWORD`, poner el repo en privado y purgar el historial (git filter-repo + force push). No se hace sin autorización. |
| H1 | High | Un token USER puede crear, editar y eliminar | Válido | Backend: USER solo lectura, escrituras solo ADMIN, rol leído de la BD en cada petición (revocación). |
| H2 | High | `usuario_registro` falsificable desde el cliente | Válido | Backend: la autoría sale de `usuario_actual`; el frontend deja de enviarla. |
| H3 | High | Carrera en "una computadora activa por persona" | Válido | Backend: `SELECT ... FOR UPDATE` sobre `people`. |
| H4 | High | El endpoint de estado acepta cualquier texto (xfail previo) | Válido | Backend: validar contra `statuses` y bloquear estados con flujo propio. |
| H5 | High | Editar un equipo modifica la `hardware_specs` compartida (xfail previo) | Válido | Backend: copy-on-write. |
| M1 | Medium | Sin rate limiting; enumeración por tiempo en la ruta legada | Válido | Backend: limitador en memoria con 429 y bcrypt de relleno en la ruta legada. |
| M2 | Medium | `JWT_SECRET` débil aceptado | Válido | Backend: mínimo 32 caracteres. |
| M3 | Medium | Token en `localStorage` y sin CSP | **Parcial.** Se acepta el riesgo de `localStorage` (app de LAN con expiración de 30 min; pasar a cookie HttpOnly exige CSRF y cambios de despliegue). | Frontend: se evalúa una CSP con `INLINE_RUNTIME_CHUNK=false`. |
| M4 | Medium | Modales sin semántica de diálogo ni gestión del foco | Válido | Frontend: componente `Modal` común con trampa de foco. |
| M5 | Medium | Cuerpos `dict` producen 500 | Válido | Backend: modelos Pydantic en las rutas de creación y edición. |
| L1 | Low | `/docs` público | Válido | Backend: solo con `ENABLE_DOCS=true`. |
| L2 | Low | Contraseñas truncadas en silencio a 72 bytes | Válido | Backend: rechazar más de 72 bytes. |
| L3 | Low | El script 004 no acumula `rowcount` | Válido | Backend. |
| L4 | Low | Colores literales fuera de `theme.css` | Válido | Frontend. |
| A1 | Arquitectura | Clean Architecture 2/10: SQL y reglas de negocio dentro de los controladores | **Válido pero diferido.** Es una refactorización grande, fuera del alcance de la auditoría. | Se recomienda como siguiente iniciativa: DTO, casos de uso, repositorios. |
| A2 | Arquitectura | El pool no se cierra en el lifespan | Válido | Backend. |
| P1 | Rendimiento | Paginación solo en el cliente | **Válido pero diferido.** El volumen actual (unos 250 equipos) no lo justifica todavía. | Retomar si el histórico crece. |
| T1 | Pruebas | 7 xfail aceptados como esperados | Válido | Backend: corregirlos y convertirlos en pruebas normales. |
| T2 | Pruebas | `App.test.js` de CRA, sin pruebas de UI | Válido | Frontend: pruebas del interceptor, App, ConfirmDialog, Toasts y tema. |
| T3 | Pruebas | Tokens sintéticos que no detectan revocación | Válido | Backend: pruebas de usuario borrado y de cambio de rol. |

Corrección mía: en la auditoría inicial afirmé que "no es un repo git". Era falso: el repositorio está un nivel más arriba. Codex lo detectó.
