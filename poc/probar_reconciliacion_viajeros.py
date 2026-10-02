"""Regresiones locales del match de viajeros y sus alertas de itinerario.

No llama a Gemini ni escribe db.json. Correr con:
    uv run python probar_reconciliacion_viajeros.py
"""
from __future__ import annotations

import copy
import sys

import eventos
import main


VIAJEROS = [
    {"id": "trv_vanesa", "name": "Vanesa Caminos"},
    {"id": "trv_santiago", "name": "Santiago Oscar Meiller"},
    {"id": "trv_julieta", "name": "Julieta Meiller"},
]


def _fail(mensaje: str) -> None:
    print(f"FALLÓ: {mensaje}")
    sys.exit(1)


def _servicio(viajeros: list[dict], *, modo: str = "instante", complemento: bool = False) -> dict:
    return {
        "id": "svc_prueba",
        "tipo": "traslado",
        "temporal": {
            "modo": modo,
            "inicio": {"fechaHoraLocal": "2026-08-02T14:40"},
        },
        "ubicacion": {
            "inicio": {"ciudad": "Paris"},
            "fin": {"ciudad": "Centro"},
        },
        "esComplemento": complemento,
        "viajeros": viajeros,
    }


def main_test() -> None:
    servicios = [
        _servicio([{
            "nombreEnDocumento": "Camino Vanesa",
            "nombreNormalizado": "Vanesa Camino",
            "viajeroId": None,
            "confianzaMatch": 0.5,
            "rol": "titular",
        }]),
        _servicio([{
            "nombreEnDocumento": "VANESA CAMINOS",
            "nombreNormalizado": "Vanesa Caminos",
            "viajeroId": "trv_vanesa",
            "confianzaMatch": 1,
            "rol": "titular",
        }]),
    ]
    # El segundo documento representa el mismo traslado, por eso comparte la
    # misma clave de agrupación aunque sea otro servicio persistido.
    servicios[1]["id"] = "svc_prueba_2"
    main.reconciliar_viajeros_servicios(servicios, VIAJEROS)
    viajero_errata = servicios[0]["viajeros"][0]
    if viajero_errata["nombreEnDocumento"] != "Camino Vanesa":
        _fail("el nombre fuente no se conservó")
    if viajero_errata["viajeroId"] != "trv_vanesa" or viajero_errata["nombreNormalizado"] != "Vanesa Caminos":
        _fail("la errata Camino/ Caminos no se reconcilió contra la viajera canónica")
    evento = eventos.agrupar_en_eventos(servicios)[0]
    if len(evento["viajerosUnion"]) != 1:
        _fail("la misma viajera quedó duplicada al agrupar los pasajes")
    print("✓ la errata menor se vincula sin duplicar a la viajera")

    ambiguo = _servicio([{
        "nombreEnDocumento": "Ana Lope",
        "nombreNormalizado": "Ana Lope",
        "viajeroId": None,
        "confianzaMatch": None,
        "rol": "titular",
    }])
    main.reconciliar_viajeros_servicios([ambiguo], [
        {"id": "trv_lopez", "name": "Ana Lopez"},
        {"id": "trv_lopes", "name": "Ana Lopes"},
    ])
    if ambiguo["viajeros"][0]["viajeroId"] is not None:
        _fail("un match ambiguo no debe asignar un viajero")
    print("✓ un match ambiguo queda sin vincular")

    paso_incompleto = eventos.agrupar_en_eventos([_servicio([
        {"nombreEnDocumento": "Vanesa Caminos", "nombreNormalizado": "Vanesa Caminos", "viajeroId": "trv_vanesa", "rol": "titular"},
        {"nombreEnDocumento": "Julieta Meiller", "nombreNormalizado": "Julieta Meiller", "viajeroId": "trv_julieta", "rol": "acompanante"},
    ])])[0]
    alerta = main._alerta_viajeros_evento(paso_incompleto, [v["id"] for v in VIAJEROS], {})
    if alerta is None or (alerta["esperados"], alerta["detectados"], alerta["pendiente"]) != (3, 2, True):
        _fail(f"alerta de cantidad inesperada: {alerta}")
    resuelta = main._alerta_viajeros_evento(
        paso_incompleto,
        [v["id"] for v in VIAJEROS],
        {paso_incompleto["id"]: {"huella": alerta["huella"]}},
    )
    if resuelta is None or resuelta["pendiente"]:
        _fail("la resolución de una alerta no quedó persistida por huella")
    reabierta = main._alerta_viajeros_evento(
        paso_incompleto,
        [v["id"] for v in VIAJEROS] + ["trv_nuevo"],
        {paso_incompleto["id"]: {"huella": alerta["huella"]}},
    )
    if reabierta is None or not reabierta["pendiente"]:
        _fail("un cambio en los viajeros del viaje debe reabrir la alerta")
    print("✓ una diferencia de viajeros alerta y puede marcarse como revisada")

    # El endpoint usa la misma huella, pero persiste la resolución por evento.
    servicio_endpoint = _servicio(copy.deepcopy(paso_incompleto["viajerosUnion"]))
    servicio_endpoint["confirmado"] = True
    evento_endpoint = eventos.agrupar_en_eventos([servicio_endpoint])[0]
    db_prueba = {
        "travelers": copy.deepcopy(VIAJEROS),
        "trips": [{
            "id": "trp_prueba",
            "travelerIds": [v["id"] for v in VIAJEROS],
            "documentos": [{"servicios": [servicio_endpoint]}],
        }],
    }
    cargar_db_original, guardar_db_original = main.cargar_db, main.guardar_db
    try:
        main.cargar_db = lambda: db_prueba
        main.guardar_db = lambda _: None
        main.confirmar_revision_viajeros("trp_prueba", evento_endpoint["id"])
    finally:
        main.cargar_db, main.guardar_db = cargar_db_original, guardar_db_original
    resolucion_endpoint = db_prueba["trips"][0]["revisionesViajerosPorEvento"].get(evento_endpoint["id"])
    if not resolucion_endpoint or "huella" not in resolucion_endpoint:
        _fail("el endpoint no persistió la revisión de viajeros por evento")
    print("✓ el endpoint confirma la revisión por paso")

    for variante in (
        _servicio(copy.deepcopy(paso_incompleto["viajerosUnion"]), modo="transversal"),
        _servicio(copy.deepcopy(paso_incompleto["viajerosUnion"]), complemento=True),
    ):
        evento_excluido = eventos.agrupar_en_eventos([variante])[0]
        if main._alerta_viajeros_evento(evento_excluido, [v["id"] for v in VIAJEROS], {}) is not None:
            _fail("un servicio transversal o complemento no debe alertar por viajeros")
    print("✓ seguros y complementos quedan fuera de las alertas")

    print("\nOK -- todas las verificaciones pasaron.")


if __name__ == "__main__":
    main_test()
