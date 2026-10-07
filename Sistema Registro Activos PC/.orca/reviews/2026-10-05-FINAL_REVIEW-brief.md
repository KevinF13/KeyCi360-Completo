# Codex Review Brief

**Tipo de revisión:** FINAL_REVIEW (SECURITY + CODE + ARCHITECTURE)
**Fecha:** 2026-10-05

Eres el revisor independiente del sistema ORCA. Tu trabajo es intentar demostrar que esta solución tiene problemas: bugs, vulnerabilidades, regresiones, race conditions, problemas arquitectónicos, inconsistencias, código muerto, mal manejo de errores, falta de tests y edge cases. No confirmes que está bien, búscale fallos activamente. No modifiques ningún archivo.
NO leas ni cites el contenido de ningún archivo `.env`, `.env.bak` ni del zip: contienen credenciales de producción. Usa `.env.example`.
Responde en español.

## Objetivo del cambio
KEYCID365 es el inventario interno de activos de TI de Grupo CID. El frontend está en `kc360/` (React 19, CRA, axios) y el backend en `Activos_LP_CID (1)/Activos_LP_CID/` (FastAPI, psycopg2, PostgreSQL). La auditoría `AUDITORIA_KEYCID365.md` encontró que la API no tenía autenticación (la sesión era solo un flag en localStorage), que las contraseñas estaban en texto plano, que `/auth/register` era público y aceptaba el rol desde el cliente, que se filtraban errores internos y que el frontend tenía problemas de accesibilidad y feedback. Este cambio corrige todo eso y aplica un diseño estilo Apple HIG con modo oscuro.

## Requisitos / acceptance criteria
- `POST /auth/login` devuelve `{id, username, role, access_token, token_type:"bearer", expires_in:1800}`. Es un JWT HS256 con `JWT_SECRET` y expira a los 30 min. Sin `JWT_SECRET` la app no arranca.
- Todo `/equipos/*` y `/mantenimiento/*` exige `Bearer`. Sin token o con token inválido responde 401 con `WWW-Authenticate`.
- `/auth/register` solo funciona para ADMIN, con el rol tomado del token; guarda la contraseña con bcrypt.
- Login: compara con bcrypt si el valor guardado empieza por `$2`; si no, hace una comparación legada en tiempo constante (ver decisiones). Nunca reescribe contraseñas al iniciar sesión.
- `sql/004_hashear_passwords.py` migra las contraseñas a bcrypt de forma manual e idempotente, con simulacro por defecto.
- Los errores 500 son genéricos (`logger.exception`), sin `str(e)` al cliente. Se usa logging en lugar de `print`. El pool de conexiones vive en `db.py` y se crea en el primer uso. CORS extra viene de la variable de entorno.
- Frontend: un interceptor de axios añade el Bearer y, ante un 401 fuera del login, dispara el evento `kc:sesion-expirada`, con lo que `App.js` cierra la sesión. La sesión solo se restaura si hay token.
- Frontend: los 42 `alert`/`confirm` se reemplazaron por `Toasts.js` y `ConfirmDialog.js` (accesible y basado en promesa). Los botones de solo ícono tienen `aria-label`. Los colores son tokens (`theme.css`) y hay modo oscuro con `prefers-color-scheme`.

## Archivos modificados
Backend (`Activos_LP_CID (1)/Activos_LP_CID/`):
- Nuevos: `auth.py`, `db.py`, `.env.example`, `sql/004_hashear_passwords.py`, `tests/test_auth.py`.
- Modificados: `login.py`, `app.py`, `activos_equipos.py`, `mantenimiento.py`, `requirements.txt`, `tests/conftest.py`, `tests/test_api.py`.

Frontend (`kc360/src/`):
- Nuevos: `theme.css`, `components/Toasts.js` y `.css`, `components/ConfirmDialog.js` y `.css`, `utils/errores.js`, `utils/chartColors.js`.
- Modificados: `api/axiosConfig.js`, `App.js`, `components/Sidebar.js`, `components/Paginacion.js`, todas las páginas en `pages/*.js` y `*.css`, `utils/pdfGenerator.js`.
- Eliminados: `Navbar.js` y `Navbar.css`.

## Tests
- `pytest` contra una copia local de la BD: 68 passed y 7 xfailed. Los 7 xfail son bugs conocidos y previos. La línea base era 49 passed y 7 xfailed.
- `tests/test_auth.py`: 19 pruebas (401 sin token o con token inválido o expirado, login con bcrypt y con legado, register sin ADMIN, 500 sin fuga de error, preflight de CORS).
- Frontend: `react-scripts build` compila sin warnings. No hay pruebas de UI; `App.test.js` es el de CRA por defecto.

## Decisiones ya tomadas (y por qué)
- **Contraseñas legadas en texto plano:** se aceptan temporalmente. La BD de producción la comparte el sistema desplegado actual, que compara texto plano; reescribir las contraseñas al iniciar sesión lo rompería. La migración es un script manual que se corre después de desplegar.
- **Token en localStorage** (no en cookie HttpOnly): es una app interna en LAN, el cambio es mínimo y no hay revocación; la expiración de 30 min mitiga el riesgo. Desafíalo si ves un riesgo concreto.
- **No hay un interruptor de tema:** se sigue la preferencia del sistema, como pide el HIG.
- **Hallazgos que ya conozco y quiero que evalúes:** no hay rate limiting en el login; hay enumeración de usuarios por tiempo en la ruta legada; `/docs` es público.

## Formato de respuesta requerido
Responde exactamente con esta forma, citando `archivo:línea` en cada hallazgo:

```text
CODEX REVIEW

Critical:
High:
Medium:
Low:
Architecture:
Security:
Performance:
Testing:
Recommendation:

PASS / PASS WITH CHANGES / REJECT
```
