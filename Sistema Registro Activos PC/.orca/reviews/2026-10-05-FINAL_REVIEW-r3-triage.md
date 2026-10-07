# Clasificación de la ronda 3 de Codex (FINAL_REVIEW, 2026-10-05)

Veredicto de Codex: **REJECT**. Las 9 filas R2 quedan **corregidas**. Critical: ninguno. Gate 9 bloqueado por 1 High del módulo nuevo.

| # | Sev. | Hallazgo | Clasificación | Acción |
|---|---|---|---|---|
| R3-H1 | High | Carrera PUT/DELETE de lecturas: se lee la lectura antes de bloquear la impresora. | Válido | Backend: orden de bloqueo uniforme (impresora → relectura de la lectura con `FOR UPDATE`) y prueba concurrente. |
| R3-M1 | Medium | El parser tabulado sin IP pierde un candidato. | Válido | Frontend: ignorar las celdas vacías como candidatos. Prueba con el texto pegado. |
| R3-M2 | Medium | La asociación por hostname/área no resuelve ambos candidatos como conjunto. | Válido | Frontend: conjunto de evidencias, asociar solo si es único; prioridad a hostname exacto único. |
| R3-M3 | Medium | Pérdida de precisión de los contadores por encima de `MAX_SAFE_INTEGER`. | Válido | Frontend: rechazar la fila con "Contador fuera de rango". |
| R3-M4 | Medium | El resumen suma impresoras en BAJA/ELIMINADO. | Válido. **Decisión del coordinador:** la serie y el consumo del mes incluyen las de BAJA (el consumo ocurrió) y excluyen las ELIMINADO (error de registro); el top solo cuenta las activas. | Backend + pruebas. Documentado en el contrato. |
| R3-L1 | Low | El Dashboard oculta la sección de impresoras ante cualquier error. | Válido | Frontend: error recuperable con "Reintentar"; con 404 se oculta. |
| R3-L2 | Low | Faltan pruebas del parser con pegado real. | Válido | Incluido en M1-M3. |
| R3-T | Testing | Hay 80 casos de frontend, no 79. | Corrección aceptada: los `test.each` cuentan por caso. | — |

## Ronda 4 (verificación): **PASS WITH CHANGES**
- Las 7 filas R3 quedaron verificadas como corregidas por Codex. No hay Critical, High ni Medium.
- Un Low: la fila "ambigua" mostraba el ícono de éxito. **Corregido**: ahora muestra el ícono de advertencia, y hay una prueba de la vista previa con un pegado real, sin IP y con candidatas en conflicto.
- Estado final: backend 164 passed; frontend 88 passed en 13 suites; build "Compiled successfully".
- **Gate 9: APROBADO** (no queda ningún Critical/High sin resolver).
- Pendiente del dueño (C1): rotar la contraseña de la BD, hacer privado el repo y purgar el historial; además, hacer commit del `.gitignore` y de la eliminación de `.env`.
