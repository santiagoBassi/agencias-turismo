# Resultados de la POC (medidos, no estimados)

Corrida real de `probar_fixtures.py` contra los 6 documentos de `../DocumentosEjemplo/`,
comparados contra `../parseo/fixtures/`. Fecha: 2026-09-10.

## 1 · El parseo funciona

Con **ambos** modelos probados, el pipeline completo (PDF/imagen → Gemini → JSON validado
contra el schema → servicios → itinerario) corre de punta a punta sin intervención manual.
La regla de granularidad más exigente del prompt (separar `paquete-tortuguero.pdf` en 5
servicios, con el seguro y la devolución del auto como complementos) se cumplió en cantidad
de servicios con los dos modelos.

Fallas reales encontradas en ambos modelos (no solo en el barato):
- **Horas inventadas**: cuando el documento no trae hora de check-in/check-out, el modelo a
  veces pone `14:00`/`12:00` en vez de `modo:"dia_completo"` — viola la regla anti-alucinación
  del prompt (`PROMPT-PARSEO-v2.md` regla 2).
- **Campos de `datos` cruzados entre tipos**: el modelo llena claves que no corresponden al
  `tipo` del servicio (ej. un vuelo con campos de excursión). El schema define `datos` como un
  único objeto con **todos** los campos de **todos** los tipos (`additionalProperties:true` a
  propósito, ver `esquema-servicio.schema.json`), sin restricción condicional por `tipo` — esto
  parece ser una limitación de diseño del contrato, no solo del modelo: pagar 18x más no lo
  resolvió (ver abajo). Quedaría para una iteración futura del schema/prompt, fuera del
  alcance de esta POC.

Matching de viajeros contra `{{CONTEXTO_VIAJE}}` funcionó correctamente en la prueba end-to-end
del panel (confirmó al titular contra el viajero cargado, `confianzaMatch:1`).

## 2 · El costo es razonable — con el modelo correcto

| Modelo | Entrada | Salida (incl. thinking) | **Costo total, 6 docs** | Tiempo/doc |
|---|---:|---:|---:|---:|
| `gemini-3.1-flash-lite` (default) | 20.531 tok | 13.659 tok | **USD 0.0256** | 8–13s |
| `gemini-3.5-flash` (con thinking) | 20.531 tok | 48.977 tok | **USD 0.4716** | 27–60s |

Referencia del análisis de costos (`../analisis-costos-pricing-validacion-peregrí.md`):
USD 0.03–0.05 por viaje documentado, estimado sobre GPT-5.4 mini.

**El modelo barato (`gemini-3.1-flash-lite`) queda por debajo del presupuesto** (0.026 vs.
0.03–0.05) y sin costo de "thinking" oculto (0 tokens de pensamiento en todas las pruebas).
El modelo caro (`gemini-3.5-flash`) cuesta **18x más** por activar razonamiento por defecto,
tarda 3–7x más por documento, y **no corrige** las dos fallas de calidad de arriba de forma
consistente — es evidencia de que el problema no se resuelve solo cambiando de modelo.

## Conclusión para decidir

1. El parseo con IA es viable y el costo (con el modelo default de esta POC) es mejor al
   presupuestado.
2. La calidad de extracción todavía tiene errores puntuales (horas inventadas, campos
   cruzados) que conviene resolver iterando el prompt/schema — no gastando más en el modelo.
3. `GEMINI_MODEL` en `.env` queda como el único punto de cambio para volver a comparar
   cuando se ajuste el prompt/schema, sin tocar código.

Detalle documento por documento: correr `uv run python probar_fixtures.py` (con
`GEMINI_API_KEY` configurada en `.env`).
