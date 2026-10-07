CODEX REVIEW

Verificación ronda 2:

- R2-H5: Corregido. Los campos compartidos requieren confirmación y el frontend reenvía `aplicar_a_todos`; también se cubre la reutilización de especificaciones. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1575`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1614`, `kc360/src/pages/Activos.test.js:33`
- R2-H6: Corregido. La computadora se bloquea antes de cerrar asignaciones y existe prueba concurrente. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:697`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:712`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda3.py:115`
- R2-H4: Corregido. Hay lista positiva y matriz de transiciones. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1107`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1113`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:1154`
- R2-M1: Corregido dentro del riesgo aceptado de un solo proceso. Hay contador por IP y expulsión efectiva. `Activos_LP_CID (1)/Activos_LP_CID/login.py:24`, `Activos_LP_CID (1)/Activos_LP_CID/login.py:60`, `Activos_LP_CID (1)/Activos_LP_CID/login.py:63`
- R2-H2: Corregido. Eliminar un accesorio asignado registra `DEVOLUCION` con el usuario autenticado. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:743`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:758`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:769`
- R2-N1: Corregido. `pantalla` y `otros` se persisten; el estado inicial activo está documentado y probado. `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:229`, `Activos_LP_CID (1)/Activos_LP_CID/activos_equipos.py:240`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_ronda3.py:33`
- R2-L1: Corregido. Se definen `X-Frame-Options: DENY` y `frame-ancestors 'none'`. `kc360/public/serve.json:6`
- R2-L2: Corregido. La interfaz falla cerrada salvo `role === 'ADMIN'`. `kc360/src/utils/permisos.js:4`
- R2-L3: Corregido. El selector tiene roving `tabIndex`, flechas y Home/End. `kc360/src/components/Sidebar.js:20`, `kc360/src/components/Sidebar.js:86`, `kc360/src/components/Sidebar.js:94`

Critical:

- Ninguno.

High:

- Hay una carrera entre actualizar y borrar una lectura. Ambos endpoints leen primero la lectura sin bloquearla y después bloquean la impresora. Si una actualización cambia el periodo mientras el borrado espera ese bloqueo, el borrado conserva el periodo antiguo y valida los vecinos equivocados después de eliminar, pudiendo dejar un histórico inconsistente. Debe releerse/bloquearse la lectura después de adquirir el bloqueo de la impresora, manteniendo un orden uniforme. No existe prueba concurrente de lecturas. `Activos_LP_CID (1)/Activos_LP_CID/printers.py:342`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:346`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:376`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:380`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:383`

Medium:

- El parser tabulado sin IP pierde uno de los dos campos intercambiables. Para `EMPRESA<TAB>MODELO<TAB><TAB>HOSTNAME<TAB>ÁREA`, toma como candidatos la celda vacía y hostname, descartando área. Esto reduce la asociación automática precisamente cuando falta la IP. `kc360/src/utils/importarLecturas.js:96`, `kc360/src/utils/importarLecturas.js:109`, `kc360/src/utils/importarLecturas.js:114`
- La asociación procesa primero todas las coincidencias por hostname y puede devolver una coincidencia o ambigüedad sin evaluar una evidencia única por área. Dado que hostname y área pueden venir intercambiados, debe resolver ambos candidatos conjuntamente y asociar solo cuando el resultado global sea inequívoco. `kc360/src/utils/importarLecturas.js:195`, `kc360/src/utils/importarLecturas.js:207`
- Los contadores de Excel se convierten a `Number`, aunque el backend permite valores por encima de `Number.MAX_SAFE_INTEGER`. Un contador grande puede redondearse silenciosamente antes de enviarse y quedar persistido con otro valor. Debe rechazarse fuera del rango seguro o utilizarse texto/`BigInt` hasta serializarlo. `kc360/src/utils/importarLecturas.js:78`, `kc360/src/utils/importarLecturas.js:80`, `Activos_LP_CID (1)/Activos_LP_CID/schemas.py:175`
- El resumen suma lecturas de todas las impresoras, incluidas las cuyo equipo está `BAJA` o `ELIMINADO`; el filtro de estado solo se aplica a los conteos. La serie, los consumos del mes y el top pueden seguir mostrando equipos retirados. `Activos_LP_CID (1)/Activos_LP_CID/printers.py:224`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:233`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:246`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:265`

Low:

- El Dashboard oculta por completo la sección de impresoras cuando falla `/impresoras/resumen`; no muestra error ni permite reintentar esa sección, aunque las demás sí lo hacen. `kc360/src/pages/Dashboard.js:110`, `kc360/src/pages/Dashboard.js:140`, `kc360/src/pages/Dashboard.js:361`
- El parser no contiene pruebas para pegado tabulado con IP vacía ni para conflictos cruzados entre hostname y área. Las pruebas construyen los candidatos directamente y no ejercitan la pérdida producida por `separarTextos`. `kc360/src/utils/importarLecturas.test.js:86`, `kc360/src/utils/importarLecturas.test.js:132`

Architecture:

- No reabro A1. La migración 005 es transaccional, usa creación condicional, relleno con `ON CONFLICT` y simulacro por defecto. `Activos_LP_CID (1)/Activos_LP_CID/sql/005_impresoras.py:30`, `Activos_LP_CID (1)/Activos_LP_CID/sql/005_impresoras.py:106`, `Activos_LP_CID (1)/Activos_LP_CID/sql/005_impresoras.py:128`
- La idempotencia se prueba con tres aplicaciones sobre la copia de pruebas. `Activos_LP_CID (1)/Activos_LP_CID/tests/test_impresoras.py:53`

Security:

- La autorización cumple el contrato: la dependencia del router permite GET autenticado y exige ADMIN para escrituras; el rol se relee de la BD. `Activos_LP_CID (1)/Activos_LP_CID/printers.py:17`, `Activos_LP_CID (1)/Activos_LP_CID/auth.py:73`, `Activos_LP_CID (1)/Activos_LP_CID/auth.py:93`
- `registrado_por` procede del usuario autenticado, no del cuerpo. `Activos_LP_CID (1)/Activos_LP_CID/printers.py:206`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:212`
- No se reabren token en `localStorage` ni rate limit multiproceso.

Performance:

- No reabro P1. El lote bloquea las impresoras en orden estable y procesa hasta 5.000 lecturas dentro de una sola transacción. `Activos_LP_CID (1)/Activos_LP_CID/printers.py:304`, `Activos_LP_CID (1)/Activos_LP_CID/printers.py:305`, `Activos_LP_CID (1)/Activos_LP_CID/schemas.py:195`

Testing:

- La lectura estática confirma 160 casos backend al expandir las parametrizaciones: 115 funciones y 45 casos adicionales. No se ejecutaron.
- El frontend contiene 13 suites, pero el conteo estático actual es 80 casos, no 79: 66 pruebas normales más 14 casos de dos `test.each`. `kc360/src/utils/importarLecturas.test.js:155`, `kc360/src/utils/permisos.test.js:10`
- Las pruebas cubren consumo, reinicios, inserción intermedia, borrado, validaciones, atomicidad funcional del lote y autorización. `Activos_LP_CID (1)/Activos_LP_CID/tests/test_impresoras.py:163`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_impresoras.py:213`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_impresoras.py:254`, `Activos_LP_CID (1)/Activos_LP_CID/tests/test_impresoras.py:316`
- Falta una prueba realmente concurrente entre PUT y DELETE de lecturas. La prueba actual de atomicidad verifica rollback por error, no serialización concurrente.
- “Build sin warnings” no puede comprobarse solamente leyendo; no se ejecutó el build por instrucción.

Recommendation:

- Bloquear el cierre hasta serializar correctamente PUT/DELETE de lecturas y añadir la prueba concurrente.
- Corregir el parser sin IP, resolver hostname/área como un conjunto de evidencias y proteger la precisión de enteros.
- Definir explícitamente si consumos y top deben excluir `BAJA`/`ELIMINADO`; la implementación actual no los excluye.
- Mostrar un error recuperable para la sección de impresoras del Dashboard.

REJECT