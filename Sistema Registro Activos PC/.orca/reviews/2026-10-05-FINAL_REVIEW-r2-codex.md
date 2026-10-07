CODEX REVIEW

Verificación ronda 1:

| ID | Estado |
|---|---|
| C1 | Corregido |
| H1 | Corregido |
| H2 | Parcial |
| H3 | Corregido |
| H4 | Parcial |
| H5 | Parcial |
| M1 | Parcial |
| M2 | Corregido |
| M3 | Parcial |
| M4 | Corregido |
| M5 | Corregido |
| L1 | Corregido |
| L2 | Corregido |
| L3 | Corregido |
| L4 | Corregido |
| A1 | No corregido — diferido aceptado |
| A2 | Corregido |
| P1 | No corregido — diferido aceptado |
| T1 | Corregido |
| T2 | Corregido |
| T3 | Corregido |

Critical:

- C1 queda corregido en el árbol local: `.env` ya no aparece en `git ls-files`, figura como eliminación staged y las reglas cubren `.env` y variantes, preservando `.env.example`. Falta que esos cambios se confirmen en Git; rotación, privacidad y purga siguen correctamente asignadas al dueño. `.gitignore:3`, `.gitignore:4`, `.gitignore:5`

High:

- H5 no está completamente corregido. El copy-on-write solo compara los siete campos de `_CAMPOS_CLAVE_HW`. Si cambian únicamente `pantalla`, `otros` o `status_id`, se actualiza en sitio la fila compartida y se alteran todos los equipos que la usan. Además, al reutilizar una especificación de destino ya existente, los valores nuevos de `pantalla` y `otros` se descartan silenciosamente. Las pruebas solo cambian `ram_gb`, por lo que no detectan ambos casos. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1423`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1479`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1481`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1508`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1541`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_api.py:504`

- Nueva carrera entre asignación y eliminación de una computadora. La asignación bloquea primero `computers`, pero `delete_computer` lee la computadora sin `FOR UPDATE`. Una eliminación concurrente puede no ver todavía la asignación insertada, cerrar cero relaciones, esperar al actualizar la computadora y terminar dejándola `ELIMINADO` con una asignación activa. La eliminación debe bloquear la computadora antes de consultar/cerrar asignaciones y necesita una prueba concurrente. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:442`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:503`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:648`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:660`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:672`

Medium:

- H4 es parcial. Se rechazan estados inexistentes, `ELIMINADO` y `ASIGNADO`, pero se acepta cualquier otro valor presente en la tabla global `statuses`. Esa tabla contiene estados de otras entidades, como `ACTIVO`; por tanto, una computadora puede quedar en un estado ajeno a su dominio. Debe emplearse una lista positiva de estados/transiciones válidas para computadoras. Las pruebas solo cubren dos estados reservados, `BAJA` y uno inventado. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:59`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1041`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1054`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:159`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_api.py:529`

- M1 es parcial y evitable. El límite usa exclusivamente la pareja `(username, IP)`, y la propia prueba confirma que cambiar de usuario desde la misma IP evita el bloqueo. Tampoco se comparte entre procesos. Además, `_MAX_CLAVES` no es un límite efectivo: si las 10 000 claves siguen vigentes, la poda no elimina ninguna y luego se siguen agregando entradas sin cota. Hace falta al menos un límite adicional por IP y/o cuenta, almacenamiento compartido para múltiples workers y una expulsión real al alcanzar el máximo. `Activos_LP_CID (1)/Activos_LP_CID/login.py:23`, `Activos_LP_CID (1)/Activos_LP_CID/login.py:31`, `Activos_LP_CID (1)/Activos_LP_CID/login.py:55`, `Activos_LP_CID (1)/Activos_LP_CID/login.py:58`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:194`

- H2 mejoró, pero queda un hueco de auditoría: eliminar un accesorio asignado desactiva la relación sin recibir al usuario autenticado ni insertar una `DEVOLUCION` en `accessory_history`. Los flujos normales sí escriben el usuario expresamente. La prueba de autoría no cubre la eliminación de un accesorio asignado. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:690`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:706`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1138`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1157`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:116`

- Hay una regresión de contrato al crear hardware: React envía `pantalla`, `otros` y `status_id`, y Pydantic los acepta, pero el `INSERT` ignora los dos primeros y fuerza `status_id=5`. El usuario puede completar esos campos y recibir éxito aunque sus datos no se guarden. `kc360/src/pages/Activos.js:136`, `kc360/src/pages/Activos.js:144`, `Activos_LP_CID (1)/Activos_LP_CID/schemas.py:41`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:179`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:183`

- H1 sí está corregido: la autorización se aplica por método en ambos routers y el rol se relee de la BD en cada petición, cubriendo eliminación y degradación del usuario. `Activos_LP_CID (1)/Activos_LP_CID/auth.py:73`, `Activos_LP_CID (1)/Activos_LP_CID/auth.py:81`, `Activos_LP_CID (1)/Activos_LP_CID/auth.py:93`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:16`, `Activos_LP_CID (1)/Activos_LP_CID/mantenimiento.py:12`

- H3 está corregido para la regla originalmente denunciada: la fila de la persona se bloquea antes de comprobar sus asignaciones activas. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:474`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:481`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:487`

- El borrado lógico de personas está correctamente serializado contra asignaciones, rechaza relaciones activas y permite reactivar conservando la identidad histórica. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:83`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:91`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1387`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1399`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1406`

Low:

- La CSP supone una mejora real: bloquea scripts inline, plugins y cambios de base URL. Sin embargo, al entregarse mediante `<meta>` y no incluir una política de framing efectiva, no protege contra clickjacking; `frame-ancestors` debe enviarse como cabecera HTTP porque no es válido en una CSP definida por `<meta>`. `kc360/public/index.html:13`, `kc360/public/index.html:15`

- Los permisos visuales fallan abiertos: si `usuario` falta o contiene JSON inválido, `esSoloLectura()` devuelve `false` y muestra controles de administración. El backend conserva la seguridad, por lo que no es una escalada, pero la UI debería ocultar escrituras salvo rol `ADMIN` explícito. `kc360/src/utils/permisos.js:3`, `kc360/src/utils/permisos.js:5`, `kc360/src/utils/permisos.js:7`

- El selector de tema usa `radiogroup`/`radio`, pero todos los botones permanecen en el orden normal de tabulación y no implementan navegación con flechas ni roving `tabIndex`. El tema sí se persiste y aplica correctamente; el defecto es del patrón de accesibilidad del selector. `kc360/src/components/Sidebar.js:63`, `kc360/src/components/Sidebar.js:69`, `kc360/src/components/Sidebar.js:72`, `kc360/src/utils/tema.js:18`, `kc360/src/utils/tema.js:25`

- M4 está corregido: `Modal` aporta nombre accesible, `aria-modal`, Escape, confinamiento por Tab y restauración de foco; `ConfirmDialog` reutiliza la misma lógica. `kc360/src/components/Modal.js:11`, `kc360/src/components/Modal.js:44`, `kc360/src/components/Modal.js:74`, `kc360/src/components/ConfirmDialog.js:17`

- M2, L1, L2, L3 y L4 están corregidos. El secreto exige 32 caracteres; la documentación lo refleja; la documentación API queda desactivada por defecto; bcrypt rechaza más de 72 bytes; la migración suma `rowcount`; y los CSS de aplicación ya usan tokens fuera de `theme.css`. `Activos_LP_CID (1)/Activos_LP_CID/auth.py:22`, `Activos_LP_CID (1)/Activos_LP_CID/.env.example:6`, `Activos_LP_CID (1)/Activos_LP_CID/app.py:30`, `Activos_LP_CID (1)/Activos_LP_CID/login.py:72`, `Activos_LP_CID (1)/Activos_LP_CID/sql/004_hashear_passwords.py:78`

Architecture:

- A1 continúa diferido conforme a la clasificación; no lo reabro. Los controladores siguen concentrando SQL y reglas, pero no apareció un riesgo nuevo que cambie el acuerdo.
- A2 está corregido mediante el `lifespan`, que llama a `cerrar_pool()` al apagar la aplicación. `Activos_LP_CID (1)/Activos_LP_CID/app.py:20`, `Activos_LP_CID (1)/Activos_LP_CID/app.py:23`, `Activos_LP_CID (1)/Activos_LP_CID/db.py:65`

Security:

- Autorización y revocación quedan correctamente aplicadas en backend. El frontend oculta las operaciones para `USER`, pero esa lógica es solo UX y no sustituye al control del servidor. `Activos_LP_CID (1)/Activos_LP_CID/auth.py:86`, `kc360/src/pages/Activos.js:252`, `kc360/src/pages/Mantenimiento.js:1008`
- La autoría de mantenimiento ya procede exclusivamente de `usuario_actual`, y el frontend dejó de enviar `usuario_registro`. `Activos_LP_CID (1)/Activos_LP_CID/mantenimiento.py:175`, `Activos_LP_CID (1)/Activos_LP_CID/mantenimiento.py:179`, `kc360/src/pages/Mantenimiento.js:432`
- Se respeta el riesgo aceptado del token en `localStorage`; no se reabre.
- Persisten el rate limit evitable, el hueco de auditoría de accesorios y la protección incompleta contra framing descritos arriba.

Performance:

- P1 permanece diferido conforme a la clasificación. No apareció evidencia nueva que justifique reabrir la paginación en servidor.

Testing:

- La lectura estática da exactamente 117 casos backend después de expandir parametrizaciones: 75 funciones de prueba más 42 casos adicionales. No quedan marcadores `xfail`. `Activos_LP_CID (1)/Activos_LP_CID/tests/test_api.py:58`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_api.py:417`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_auth.py:38`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:45`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:242`
- El frontend contiene 29 pruebas en siete archivos, coherente con lo declarado. Incluye interceptor, sesión, errores, tema, `Modal`, `ConfirmDialog` y toasts. `kc360/src/App.test.js:18`, `kc360/src/api/axiosConfig.test.js:28`, `kc360/src/components/Modal.test.js:5`, `kc360/src/utils/tema.test.js:9`
- T3 está corregido con pruebas de usuario eliminado, cambio de rol y nombre ajeno. `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:65`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:76`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda2.py:94`
- No se ejecutaron pruebas ni build, conforme a la instrucción. “117 passed” y “build sin warnings” son resultados de ejecución y no pueden demostrarse únicamente leyendo; sí se verificaron estructura, conteos y ausencia de `xfail`.
- Falta cobertura para `RENTADO`, cambios de `pantalla`/`otros` sobre especificaciones compartidas, eliminación concurrente de computadoras y eliminación de accesorios asignados. La admisión de `RENTADO` está implementada correctamente en el esquema y coincide con el formulario. `Activos_LP_CID (1)/Activos_LP_CID/schemas.py:9`, `Activos_LP_CID (1)/Activos_LP_CID/schemas.py:60`, `kc360/src/pages/Activos.js:512`

Recommendation:

- Bloquear el cierre de la ronda hasta: aplicar copy-on-write a todos los campos mutables y conservarlos al reutilizar una especificación; bloquear la computadora al inicio de `delete_computer`; registrar con autor autenticado la devolución al eliminar accesorios; sustituir la lista negativa de estados por transiciones permitidas; y reforzar el rate limit por IP/cuenta con almacenamiento compartido y límite de memoria real.
- Añadir pruebas específicas para esas rutas y para `tipo_propiedad=RENTADO`.
- Antes del commit, incluir tanto la eliminación staged de `.env` como el `.gitignore` actualmente no rastreado. Las acciones históricas de C1 siguen dependiendo del dueño.

REJECT