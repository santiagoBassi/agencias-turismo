"""
Test de regresión del agrupador de eventos (eventos.py) -- NO llama a Gemini,
corre gratis e instantáneo. Usa como fixture los 40 servicios reales del viaje
"Roma" (3 pasajeros, 32 documentos) fijados en fixture_agrupador_roma.json antes
de re-parsear con el prompt reforzado, así queda un caso de regresión estable
aunque el re-parseo futuro cambie los datos en db.json.

Correr con: uv run python probar_agrupador.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import eventos

FIXTURE = Path(__file__).resolve().parent / "fixture_agrupador_roma.json"

# Cardinalidades esperadas de los 11 eventos con más de un pasaje, verificadas a
# mano contra los datos reales (ver el plan de esta iteración): 5 grupos de 3
# (dos trenes multipasajero + seguros + ...) y 6 pares de 2.
CARDINALIDADES_MULTI_ESPERADAS = sorted([3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2], reverse=True)


def _fail(msg: str) -> None:
    print(f"FALLÓ: {msg}")
    sys.exit(1)


def main() -> None:
    servicios = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if len(servicios) != 40:
        _fail(f"el fixture tiene {len(servicios)} servicios, se esperaban 40 -- ¿se regeneró el fixture?")

    evs = eventos.agrupar_en_eventos(servicios)

    if len(evs) != 24:
        _fail(f"se esperaban 24 eventos, se obtuvieron {len(evs)}")
    print(f"✓ 40 servicios -> {len(evs)} eventos")

    total_en_eventos = sum(len(e["servicios"]) for e in evs)
    if total_en_eventos != 40:
        _fail(f"se perdieron o duplicaron servicios al agrupar: {total_en_eventos} != 40")
    print("✓ ningún servicio se pierde ni se duplica al agrupar")

    cardinalidades_multi = sorted((len(e["servicios"]) for e in evs if len(e["servicios"]) > 1), reverse=True)
    if cardinalidades_multi != CARDINALIDADES_MULTI_ESPERADAS:
        _fail(f"cardinalidades de eventos multi-servicio distintas a lo esperado: {cardinalidades_multi} != {CARDINALIDADES_MULTI_ESPERADAS}")
    print(f"✓ {len(cardinalidades_multi)} eventos multi-servicio con las cardinalidades esperadas: {cardinalidades_multi}")

    frecciarossa = next(
        (e for e in evs if "9520" in (e["representante"].get("titulo") or "") and len(e["servicios"]) == 3),
        None,
    )
    if frecciarossa is None:
        _fail("no se encontró el evento del Frecciarossa 9520 con sus 3 pasajes")
    ids_viajeros = {v.get("viajeroId") for v in frecciarossa["viajerosUnion"]}
    if len(ids_viajeros) != 3 or None in ids_viajeros:
        _fail(f"viajerosUnion del Frecciarossa 9520 no tiene los 3 viajeroId esperados: {ids_viajeros}")
    print("✓ viajerosUnion del Frecciarossa 9520 contiene a los 3 pasajeros")

    print("\nOK -- todas las verificaciones pasaron.")


if __name__ == "__main__":
    main()
