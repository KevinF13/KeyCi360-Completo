# Clasificación de la ronda 2 de Codex (FINAL_REVIEW, 2026-10-05)

Veredicto de Codex: **REJECT**. Ronda 1: 12 corregidos, 5 parciales, 2 diferidos aceptados (A1, P1); C1 ya corregido en local.
El Gate 9 sigue **bloqueado** por 2 High.

**Secuencia:** estos cambios tocan `activos_equipos.py`, `login.py`, `schemas.py`, `Sidebar.js` y `permisos.js`. Hay workers de impresoras editando en paralelo `schemas.py` y `Sidebar.js`, así que se aplican **después** de que esa oleada termine, para no pisarse.

| # | Sev. | Hallazgo | Clasificación | Acción |
|---|---|---|---|---|
| R2-H5 | High | El copy-on-write ignora `pantalla`, `otros` y `status_id`: cambiarlos en una spec compartida afecta a todos los equipos que la usan, y al reutilizar una spec se descartan en silencio. | Válido | Si la spec es compartida y cambian campos que no son clave, responder 409 con el número de equipos afectados, salvo `aplicar_a_todos: true`. Al reutilizar una spec existente con `pantalla`/`otros` distintos, aplicar la misma regla. El frontend muestra la confirmación "Se aplicará a N equipos". Añadir pruebas. |
| R2-H6 | High | Carrera entre asignar y eliminar: `delete_computer` no bloquea la computadora. | Válido | Hacer `SELECT ... FOR UPDATE` sobre la computadora al inicio de `delete_computer`, en el mismo orden de bloqueo que la asignación. Añadir una prueba concurrente. |
| R2-H4 | Medium | El cambio de estado acepta estados de otras entidades (`ACTIVO`). | Válido | Lista positiva de estados de computadora (DISPONIBLE, MANTENIMIENTO, BAJA, más los que el frontend use realmente) y transiciones permitidas. Añadir pruebas. |
| R2-M1 | Medium | El rate limit se evita cambiando de usuario; la memoria no está acotada; no se comparte entre procesos. | **Parcial.** Se corrige el límite por IP y la expulsión real. Almacenamiento compartido: **riesgo aceptado**, porque el despliegue es un solo proceso uvicorn (`INICIAR.txt`). Si se escala a varios workers, hay que pasarlo a la BD o a Redis. | Backend + pruebas. |
| R2-H2 | Medium | Eliminar un accesorio asignado no registra DEVOLUCION con el autor. | Válido | Insertar DEVOLUCION en `accessory_history` con `usuario_actual`. Añadir prueba. |
| R2-N1 | Medium | Crear hardware ignora `pantalla` y `otros` y fuerza `status_id=5` aunque responde éxito. | Válido | Persistir `pantalla` y `otros`. Para `status_id`, respetar el contrato real (decidir con el código). Añadir prueba. |
| R2-L1 | Low | `frame-ancestors` no funciona en una CSP por `<meta>` (clickjacking). | Válido | `kc360/public/serve.json` con las cabeceras `X-Frame-Options: DENY` y `Content-Security-Policy: frame-ancestors 'none'`, para `npx serve -s build`. |
| R2-L2 | Low | `esSoloLectura()` falla abierto. | Válido | Fallar cerrado: solo `role === 'ADMIN'` ve las escrituras. Añadir prueba. |
| R2-L3 | Low | El radiogroup del tema no tiene roving tabindex ni navegación con flechas. | Válido | Implementar tabIndex -1/0 y las flechas izquierda/derecha. Añadir prueba. |
| R2-T | Testing | Falta cobertura de RENTADO, de los casos anteriores y de eliminar un accesorio asignado. | Válido | Incluido en las acciones de arriba. |
| C1 | — | Falta hacer commit de la eliminación de `.env` y del `.gitignore`. | Válido | Lo decide el dueño; no se hace commit sin que lo pida. |
