# Codex Review Brief — Ronda 2

**Tipo de revisión:** FINAL_REVIEW (verificación de correcciones + revisión adversarial)
**Fecha:** 2026-10-05

Eres el revisor independiente de ORCA. En la ronda 1 devolviste REJECT. Tu informe está en `.orca/reviews/2026-10-05-FINAL_REVIEW-codex.md` y mi clasificación en `.orca/reviews/2026-10-05-FINAL_REVIEW-triage.md`. Léelos primero.
Tarea:
1. Verifica en el código, hallazgo por hallazgo, si cada uno marcado "Válido" está corregido de verdad. Cita archivo:línea.
2. Busca activamente problemas NUEVOS introducidos por las correcciones: regresiones de contrato entre `kc360/src` y el backend, condiciones de carrera, huecos de autorización, rate limit evitable, copy-on-write de hardware_specs, borrado lógico de personas, reatribución de autoría `_atribuir_movimiento`, CSP en `kc360/public/index.html`, componente `Modal`, permisos de UI y selector de tema (`utils/tema.js`).
3. Respeta los diferidos y riesgos aceptados de la clasificación (Clean Architecture, paginación en servidor, token en localStorage). Solo puedes reabrirlos con un argumento nuevo y concreto.
4. C1 (secretos en el historial de git) depende del dueño: rotar, hacer privado el repo y purgar. Verifica solo que `.env` ya no se rastree y que `.gitignore` lo cubra.

No leas ni cites archivos `.env`, `.env.bak` ni el zip. No modifiques nada. Responde en español.

Estado de las pruebas declarado (verifícalo leyendo, no ejecutando):
- Backend: 117 passed, 0 xfailed (`tests/test_api.py`, `tests/test_auth.py`, `tests/test_ronda2.py`).
- Frontend: 29 tests en 7 suites (`kc360/src/**/*.test.js`). El build compila sin warnings.

Cambio de última hora hecho por mí: `schemas.py` ahora acepta `tipo_propiedad` RENTADO además de PROPIO y ARRIENDO, porque existen 32 filas RENTADO en la BD y el formulario ofrece esa opción.

## Formato de respuesta requerido
Responde exactamente con esta forma, citando `archivo:línea`. Añade al inicio una tabla "Verificación ronda 1" con el ID del hallazgo y su estado (Corregido / Parcial / No corregido):

```text
CODEX REVIEW

Verificación ronda 1:
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
