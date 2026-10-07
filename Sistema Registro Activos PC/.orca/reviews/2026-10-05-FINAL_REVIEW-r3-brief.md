# Codex Review Brief: ronda 3

**Tipo:** FINAL_REVIEW (verificación de la ronda 2 + revisión del módulo nuevo de impresoras y del Dashboard)
**Fecha:** 2026-10-05

Eres el revisor independiente de ORCA. Tu trabajo es buscar fallos activamente, no confirmar que todo está bien. No modifiques nada. No leas ni cites `.env`, `.env.bak` ni el zip. Responde en español y cita `archivo:línea`.

Lee primero:
- `.orca/reviews/2026-10-05-FINAL_REVIEW-r2-codex.md` (tu informe anterior) y `.orca/reviews/2026-10-05-FINAL_REVIEW-r2-triage.md` (cómo se clasificó).
- `.orca/impresoras-contrato.md` (el contrato del módulo nuevo).

Tareas:
1. **Ronda 2:** verifica cada fila R2-* de la clasificación. Marca las de backend (H5, H6, H4, M1, H2, N1) y las de frontend (L1, L2, L3) como Corregido, Parcial o No corregido.
2. **Módulo de impresoras**, revisión adversarial:
   - `Activos_LP_CID (1)/Activos_LP_CID/printers.py`, `sql/005_impresoras.py`, los modelos de impresoras en `schemas.py` y `tests/test_impresoras.py`.
   - `kc360/src/pages/Impresoras.js` y `utils/importarLecturas.js` con sus pruebas.
   - Qué buscar:
     - corrección del cálculo de consumo, incluidos reinicios, inserciones en medio del histórico y borrados;
     - atomicidad y concurrencia del lote;
     - autorización;
     - validaciones (periodo o fecha futura, monocromo, IP);
     - migración segura e idempotente para producción;
     - parser del Excel: robustez y asociación por IP, hostname y área intercambiados;
     - cumplimiento del contrato entre frontend y backend.
3. **Dashboard** (`kc360/src/pages/Dashboard.js`, `components/KpiCard.js`):
   - cifras correctas y no duplicadas;
   - exclusión de impresoras;
   - accesibilidad de las tarjetas-enlace;
   - manejo de errores por sección.
4. **No reabras** los diferidos ni los riesgos aceptados (A1 Clean Architecture, P1 paginación en servidor, token en localStorage, rate limit compartido entre procesos mientras haya un solo proceso), salvo con un argumento nuevo y concreto.

Estado de pruebas declarado (verifica leyendo, no ejecutando):
- Backend: 160 passed.
- Frontend: 79 tests en 13 suites, build sin warnings.

Formato exacto:
```text
CODEX REVIEW

Verificación ronda 2:
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
