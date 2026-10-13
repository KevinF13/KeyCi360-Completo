# Contrato: módulo de impresoras y KPIs (Run run_3fb193af123c)

Coordinador: sesión principal de Claude. Este contrato es fijo: si un worker necesita cambiarlo, debe preguntarlo con `ask` antes de hacerlo.

## Contexto
- Las impresoras existen hoy como activos en `computers` cuyo `hardware_specs.tipo_equipo` es ILIKE 'impres%'. Hay 27, la mayoría Canon iR-ADV, con `tipo_propiedad` RENTADO. Siguen en `computers` para conservar el inventario, el mantenimiento, la auditoría y los triggers.
- Hoy las lecturas se llevan en Excel con formato ancho: EMPRESA | MODELO | IP | HOSTNAME | ÁREA, y luego un par de columnas (B/N, Color) por cada fecha de lectura. Los contadores son **acumulados**: el consumo del periodo es la lectura actual menos la anterior, y la última columna del Excel es esa diferencia. Ejemplo de 2 filas (las columnas van separadas por tabuladores o espacios múltiples):
```
                                        01/2026 y 02/2026   01/03/2026   01/04/2026 ...
                    B/N  Color  B/N  Color  B/N  Color ...
FARMACID  Canon iR-ADV C4245     172.16.1.32  FCCCAPRT02     CONTROL DE CALIDAD  584210 0  590871 0 ... 700902 0  10137 0
FARMACID  Canon iR-ADV C356 III  172.16.1.20  GERENCIA       GERENCIA-FCID       48868 43062  49372 44045 ... 61349 53638  982 609
```
  Nota: en la segunda fila el 4.º campo es el ÁREA ("GERENCIA") y el 5.º es el hostname ("GERENCIA-FCID"): el orden de hostname y área no es fiable. El último par de columnas (una diferencia) NO es una lectura y debe ignorarse al importar.

## Esquema (migración `sql/005_impresoras.py`: idempotente, simulacro por defecto, `--aplicar`)
```sql
CREATE TABLE IF NOT EXISTS printers (
  id            SERIAL PRIMARY KEY,
  computer_id   INTEGER NOT NULL UNIQUE REFERENCES computers(id),
  company_id    INTEGER NULL REFERENCES companies(id),
  ip_address    VARCHAR(45) NULL,       -- IPv4/IPv6 validada en la API; único si no es NULL (índice parcial)
  hostname      VARCHAR(100) NULL,
  area          VARCHAR(100) NULL,
  ubicacion     VARCHAR(150) NULL,
  es_color      BOOLEAN NOT NULL DEFAULT FALSE,
  proveedor     VARCHAR(100) NULL,
  observaciones TEXT NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT now(),
  updated_at    TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_printers_ip ON printers(ip_address) WHERE ip_address IS NOT NULL;

CREATE TABLE IF NOT EXISTS printer_readings (
  id             SERIAL PRIMARY KEY,
  printer_id     INTEGER NOT NULL REFERENCES printers(id) ON DELETE CASCADE,
  periodo        DATE NOT NULL,          -- siempre el día 1 del mes al que corresponde la lectura
  fecha_lectura  DATE NOT NULL,          -- fecha real en que se tomó
  contador_bn    BIGINT NOT NULL CHECK (contador_bn >= 0),
  contador_color BIGINT NOT NULL DEFAULT 0 CHECK (contador_color >= 0),
  es_reinicio    BOOLEAN NOT NULL DEFAULT FALSE,  -- cambio de equipo o reinicio del contador: el consumo es el contador mismo
  observaciones  TEXT NULL,
  registrado_por VARCHAR(50) NOT NULL,   -- username autenticado, nunca enviado por el cliente
  created_at     TIMESTAMP NOT NULL DEFAULT now(),
  UNIQUE (printer_id, periodo),
  CHECK (periodo = date_trunc('month', periodo)::date)
);
CREATE INDEX IF NOT EXISTS ix_printer_readings_periodo ON printer_readings(periodo);
```
Relleno inicial: una fila de `printers` por cada computadora de tipo impresora que aún no la tenga. `es_color` se infiere por heurística (el modelo contiene " C" seguido de un dígito, p. ej. "iR-ADV C5550", o la palabra "COLOR") y el script informa cuáles infirió. `company_id` queda NULL.

## Reglas de negocio
- consumo_bn y consumo_color de una lectura = contador menos el contador de la lectura anterior de la misma impresora (por `periodo`). Si `es_reinicio` es verdadero o no hay lectura anterior, el consumo es NULL ("sin base") cuando no hay anterior, o el contador mismo cuando es reinicio.
- Un contador menor que el de la lectura anterior → 400 "El contador B/N (X) es menor que la lectura anterior (Y) del <mes>. Si cambió el equipo o se reinició el contador, marca 'Reinicio de contador'." Lo mismo para color. Al insertar en medio del histórico, también debe ser ≤ que la lectura siguiente.
- Una impresora monocromática (`es_color` falso) con `contador_color` > 0 → 400.
- Solo una lectura por impresora y mes: un duplicado da 409.
- `periodo` no puede ser futuro, y `fecha_lectura` no puede ser futura.

## API (`printers.py`, prefijo `/impresoras`)
Usa las mismas dependencias que `/equipos`: GET lo puede hacer cualquier usuario autenticado; POST/PUT/DELETE exigen ADMIN (`lectura_usuario_escritura_admin`). Modelos Pydantic en `schemas.py`, errores genéricos con `logger.exception`, conexiones con `db.get_conn`.

| Método | Ruta | Cuerpo / query | Respuesta |
|---|---|---|---|
| GET | `/impresoras` | `?incluir_baja=false` | `[Impresora]` |
| GET | `/impresoras/{id}` | | `Impresora` |
| POST | `/impresoras` | `{numero_serie, marca, modelo, tipo_propiedad, tarifa_mensual?, fecha_recepcion_proveedor?, anio_fabricacion?, company_id?, ip_address?, hostname?, area?, ubicacion?, es_color, proveedor?, observaciones?}` | 201 `Impresora`. Crea `hardware_specs` (tipo_equipo 'Impresora', reutilizando una spec idéntica si existe), `computers` (estado DISPONIBLE) y `printers` en una sola transacción. |
| PUT | `/impresoras/{id}` | campos de `printers` + `marca`, `modelo`, `tipo_propiedad`, `tarifa_mensual` (spec con copy-on-write, igual que en hardware) | `Impresora` |
| GET | `/impresoras/{id}/lecturas` | | `[Lectura]` ordenadas por periodo DESC |
| POST | `/impresoras/{id}/lecturas` | `{periodo:"YYYY-MM", fecha_lectura:"YYYY-MM-DD", contador_bn, contador_color, es_reinicio?, observaciones?}` | 201 `Lectura` |
| PUT | `/impresoras/lecturas/{lectura_id}` | los mismos campos | `Lectura` (vuelve a validar contra la anterior y la siguiente) |
| DELETE | `/impresoras/lecturas/{lectura_id}` | | 204 |
| POST | `/impresoras/lecturas/lote` | `{lecturas:[{printer_id, periodo, fecha_lectura, contador_bn, contador_color, es_reinicio?, observaciones?}], modo:"validar"\|"aplicar"}` | 200 `{ok, creadas, validas, errores:[{indice, printer_id, periodo, mensaje}]}`: `creadas` = escritas (0 en validar o si se rechaza), `validas` = las que pasaron la validación. Es atómico: con un solo error no se inserta nada. `validar` nunca escribe. |
| GET | `/impresoras/resumen` | `?meses=12` | `ResumenImpresoras` |
| GET | `/impresoras/lecturas` | `?desde=YYYY-MM&hasta=YYYY-MM` (ambos opcionales; formato inválido o `desde` > `hasta` → 422) | `[LecturaReporte]` ordenada por impresora y periodo. Solo lectura (cualquier usuario autenticado). Excluye impresoras ELIMINADO. El consumo usa el LAG sobre TODO el histórico de cada impresora y el rango se aplica después (la primera lectura del rango conserva su consumo si hay una anterior). Declarada antes de `/{id}`. |
| GET | `/equipos/accessories/reporte` | | `[AccesorioReporte]` ordenada por tipo, marca, modelo, serie. Solo lectura. Todos los accesorios no ELIMINADO (disponibles y asignados). `asignado` sale de `person_accessories.activo = TRUE` (si hubiera más de una activa, la más reciente). Declarada antes de `/accessories/disponibles`. |

```ts
// Reportes para exportar a Excel (frontend: utils/exportarExcel.js y utils/reportesExcel.js)
LecturaReporte = { printer_id, numero_serie, modelo, empresa /* o null */, ip_address, hostname, area, es_color,
  estado /* nombre en statuses */, periodo:"YYYY-MM", fecha_lectura:"YYYY-MM-DD", contador_bn, contador_color,
  es_reinicio, consumo_bn: number|null, consumo_color: number|null, registrado_por }
AccesorioReporte = { id, tipo, marca, modelo, numero_serie, tipo_propiedad, asignado: boolean,
  asignado_a: string|null, cedula: string|null, empresa: string|null, fecha_asignacion: "YYYY-MM-DD"|null }
```

```ts
Impresora = { id, computer_id, numero_serie, marca, modelo, tipo_propiedad, tarifa_mensual, estado /* nombre en statuses */,
  company_id, empresa /* companies.nombre o null */, ip_address, hostname, area, ubicacion, es_color, proveedor, observaciones,
  ultima_lectura: null | { id, periodo:"YYYY-MM", fecha_lectura, contador_bn, contador_color },
  consumo_ultimo: null | { periodo:"YYYY-MM", bn, color },   // consumo de la última lectura
  lectura_mes_actual: boolean }
Lectura = { id, printer_id, periodo:"YYYY-MM", fecha_lectura, contador_bn, contador_color, es_reinicio,
  consumo_bn: number|null, consumo_color: number|null, observaciones, registrado_por, created_at }
ResumenImpresoras = { total, activas, color, monocromo, sin_lectura_mes_actual,
  periodo_actual:"YYYY-MM", consumo_mes: { bn, color }, consumo_mes_anterior: { bn, color },
  serie: [{ periodo:"YYYY-MM", bn, color }],                 // últimos N meses, consumo total por mes
  top: [{ printer_id, modelo, hostname, area, empresa, bn, color, total }] }  // top 5 del último periodo con datos
// Reglas de estado (ronda 3): serie y consumo_mes* incluyen impresoras en BAJA y excluyen ELIMINADO; top solo impresoras activas.
```
Para el inventario y las KPI de "equipos de cómputo", el frontend excluye `tipo_equipo` ILIKE 'impres%'. El backend de `/equipos` no cambia.

## Propiedad de archivos (sin solapes)
- **Worker A (backend):**
  - Nuevos: `Activos_LP_CID (1)/Activos_LP_CID/printers.py` y `sql/005_impresoras.py`.
  - Edita `schemas.py` (añadir), `app.py` (incluir el router) y `tests/test_impresoras.py` (nuevo).
  - No edita `activos_equipos.py`, `mantenimiento.py` ni `auth.py`.
- **Worker B (frontend, impresoras):**
  - Nuevos: `kc360/src/pages/Impresoras.js`, `Impresoras.css`, `kc360/src/utils/importarLecturas.js` y `importarLecturas.test.js`.
  - Edita `components/Sidebar.js` (enlace), `App.js` (ruta `/impresoras`) y `pages/Activos.js` (excluir impresoras del inventario y del selector de tipo).
- **Worker C (frontend, Dashboard):**
  - Edita solo `kc360/src/pages/Dashboard.js` y `Dashboard.css`. Si necesita un componente nuevo, lo crea como `components/KpiCard.js` + `.css`.
- **Nadie** edita `theme.css`, `axiosConfig.js`, `Toasts.js`, `ConfirmDialog.js`, `Modal.js` ni archivos del otro worker. Si hace falta un token nuevo, se pide al coordinador.

## Entorno y reglas globales
- BD SOLO la copia local: `localhost:5433/keycid365_test`, usuario postgres, sin contraseña. **Nunca producción** (el `.env` apunta a producción, 192.168.20.3).
- Backend corriendo en `127.0.0.1:7001`, iniciado por el coordinador sin `--reload`. Frontend con `npm start` en `:3000` (recarga en caliente). No los detengas: avisa en tu `worker_done` y el coordinador reinicia.
- Pruebas del backend (PowerShell): `$env:TEST_DB_HOST='localhost'; $env:TEST_DB_PORT='5433'; $env:TEST_DB_NAME='keycid365_test'; $env:TEST_DB_USER='postgres'; $env:TEST_DB_PASSWORD=''; python -m pytest tests -q` (hoy dan 117 passed).
- Pruebas del frontend: `$env:CI='true'; npx react-scripts test --watchAll=false` (hoy 29 passed). Build: `$env:BUILD_PATH="$env:TEMP\kc360_build_<worker>"; $env:CI='false'; npx react-scripts build`.
- Diseño: estilo Apple HIG ya aplicado; todo color sale de tokens `--kc-*` de `theme.css`, con modo claro y oscuro. Textos en español con mayúscula solo al inicio. Usa `useToast`, `useConfirm`, `Modal`, `mensajeError`, `useChartColors` y `usePaginacion`/`Paginacion`. Botones de solo ícono con `aria-label`. `utils/permisos.js`: oculta las escrituras si el rol es USER.
- **No** hagas commits, no toques git y no imprimas secretos.
