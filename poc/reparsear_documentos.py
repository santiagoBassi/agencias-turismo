"""
Re-parsea con el prompt actual todos los documentos ya confirmados de un viaje,
preservando el id y el estado `confirmado` de cada documento. Uso manual
(consume la API real de Gemini) -- pensado para después de iterar
parseo/PROMPT-PARSEO-v3.md: sin esto, los documentos ya cargados quedan
parseados con la versión vieja del prompt para siempre.

El contexto de "servicios ya cargados" (`{{CONTEXTO_VIAJE}}`) que se le pasa a
cada documento se congela ANTES de empezar la corrida (con los servicios
ORIGINALES del viaje, excluyendo los del propio documento que se está
re-parseando) -- no se recalcula a medida que van terminando otros documentos,
para que el resultado no dependa del orden de procesamiento.

Uso:
    uv run python reparsear_documentos.py <tripId>
"""
from __future__ import annotations

import sys
from pathlib import Path

import main
import parseo


def main_cli() -> None:
    if len(sys.argv) != 2:
        print("Uso: uv run python reparsear_documentos.py <tripId>")
        sys.exit(1)
    tid = sys.argv[1]

    db = main.cargar_db()
    trip = main._buscar_trip(db, tid)
    if trip is None:
        print(f"No existe el viaje {tid!r}.")
        sys.exit(1)

    documentos = [d for d in trip["documentos"] if d.get("confirmado")]
    if not documentos:
        print("Este viaje no tiene documentos confirmados para re-parsear.")
        return

    viajeros_asignados = [t for t in db["travelers"] if t["id"] in trip["travelerIds"]]
    # Contexto congelado al inicio: servicios de TODOS los documentos confirmados,
    # tal como están hoy en db.json (antes de re-parsear ninguno).
    servicios_por_doc = {
        d["id"]: [s for s in d["servicios"] if s.get("confirmado")] for d in documentos
    }
    todos_los_servicios = [s for lista in servicios_por_doc.values() for s in lista]

    costo_estimado = 0.003 * len(documentos)  # referencia: RESULTADOS-POC.md, ~USD 0.003/doc con gemini-3.1-flash-lite
    print(f"Viaje: {trip['nombre']} ({tid})")
    print(f"Documentos a re-parsear: {len(documentos)}")
    print(f"Costo estimado: ~USD {costo_estimado:.3f} (referencia RESULTADOS-POC.md, puede variar)")
    respuesta = input("¿Confirmás? Esto llama a Gemini de verdad y tiene costo real. [s/N] ").strip().lower()
    if respuesta != "s":
        print("Cancelado.")
        return

    costo_total = 0.0
    for i, documento in enumerate(documentos, 1):
        nombre = documento["nombreOriginal"]
        ruta = Path(documento["archivoPath"])
        if not ruta.exists():
            print(f"[{i}/{len(documentos)}] {nombre}: SALTEADO (el archivo ya no está en disco)")
            continue

        servicios_confirmados_ctx = [
            s for did, lista in servicios_por_doc.items() if did != documento["id"] for s in lista
        ]
        contenido = ruta.read_bytes()
        try:
            resultado = parseo.parsear_documento(
                contenido, documento["mimeType"],
                viaje=trip, viajeros=viajeros_asignados, servicios_confirmados=servicios_confirmados_ctx,
            )
        except parseo.ErrorParseo as exc:
            print(f"[{i}/{len(documentos)}] {nombre}: ERROR -- {exc}")
            continue

        medicion = resultado.pop("medicion")
        costo_total += medicion["costoUsd"]
        servicios_raw = resultado.get("servicios", [])
        main.reconciliar_viajeros_servicios(servicios_raw, viajeros_asignados)
        servicios_out = main.procesar_servicios_parseados(
            servicios_raw, documento["id"], confirmado=True
        )
        requiere_revision = any((s.get("extraccion") or {}).get("requiereRevision") for s in servicios_out)

        documento["parseo"] = {
            "estado": "revision" if requiere_revision else "parseado",
            "modelo": medicion["modelo"], "tokensEntrada": medicion["tokensEntrada"],
            "tokensSalida": medicion["tokensSalida"], "costoUsd": medicion["costoUsd"],
            "segundos": medicion["segundos"], "errorMsg": None,
        }
        documento["documento"] = resultado.get("documento")
        documento["servicios"] = servicios_out
        print(f"[{i}/{len(documentos)}] {nombre}: OK -- {len(servicios_out)} servicio(s), USD {medicion['costoUsd']:.4f}, {medicion['segundos']}s")

    main.guardar_db(db)
    print(f"\nListo. Costo real total: USD {costo_total:.4f}")


if __name__ == "__main__":
    main_cli()
