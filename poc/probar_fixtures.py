"""
Corre el parseo real (Gemini) contra los 6 documentos de ../DocumentosEjemplo/ y
compara la salida con los fixtures de regresión de ../parseo/fixtures/, según los
criterios de ../parseo/fixtures/README.md (comparar tipo/estado/temporal/
esComplemento exactos, y las claves presentes en `datos`; ignorar
_comentario_fixture, confianza, fragmentoFuente y claveLocal). Al final imprime
la tabla de costo real por documento -- el resultado que busca esta POC (ver
../analisis-costos-pricing-validacion-peregrí.md).

Uso: uv run python probar_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import parseo  # noqa: E402  (después de load_dotenv, así GEMINI_API_KEY ya está en el entorno)

RAIZ = Path(__file__).resolve().parent.parent
DOCS_DIR = RAIZ / "DocumentosEjemplo"
FIXTURES_DIR = RAIZ / "parseo" / "fixtures"

# (archivo en DocumentosEjemplo/, fixture correspondiente, mime type)
CASOS = [
    ("04 HTL Lomas del Volcan 07 Enero.pdf", "htl-lomas-del-volcan.json", "application/pdf"),
    ("05 Universal x4 Expres Pass.pdf", "universal-express-pass.json", "application/pdf"),
    ("E-TKT Giemenez Nelida Raquel.pdf", "e-tkt-gimenez.json", "application/pdf"),
    ("Traslados y Excursion.pdf", "traslados-y-excursion.json", "application/pdf"),
    ("02 Paquete Tortuguero y Alquiler Auto 02 al 04 Enero.pdf", "paquete-tortuguero.json", "application/pdf"),
    ("WhatsApp Image 2026-06-09 at 7.05.22 PM.jpeg", "europamundo-puglia-campania.json", "image/jpeg"),
]


def comparar(real: list[dict], esperado: list[dict]) -> list[str]:
    problemas = []
    if len(real) != len(esperado):
        problemas.append(f"cantidad de servicios: esperado {len(esperado)}, obtenido {len(real)}")
    for i, (r, e) in enumerate(zip(real, esperado)):
        for campo in ("tipo", "estado"):
            if r.get(campo) != e.get(campo):
                problemas.append(f"servicio {i}: {campo} esperado={e.get(campo)!r} obtenido={r.get(campo)!r}")
        rt, et = (r.get("temporal") or {}), (e.get("temporal") or {})
        if rt.get("modo") != et.get("modo"):
            problemas.append(f"servicio {i}: temporal.modo esperado={et.get('modo')!r} obtenido={rt.get('modo')!r}")
        for punto in ("inicio", "fin"):
            rp, ep = (rt.get(punto) or {}), (et.get(punto) or {})
            if rp.get("fechaHoraLocal") != ep.get("fechaHoraLocal"):
                problemas.append(f"servicio {i}: temporal.{punto}.fechaHoraLocal esperado={ep.get('fechaHoraLocal')!r} obtenido={rp.get('fechaHoraLocal')!r}")
            if rp.get("precision") != ep.get("precision"):
                problemas.append(f"servicio {i}: temporal.{punto}.precision esperado={ep.get('precision')!r} obtenido={rp.get('precision')!r}")
        if bool(r.get("esComplemento")) != bool(e.get("esComplemento")):
            problemas.append(f"servicio {i}: esComplemento esperado={e.get('esComplemento')!r} obtenido={r.get('esComplemento')!r}")
        claves_r, claves_e = set((r.get("datos") or {}).keys()), set((e.get("datos") or {}).keys())
        if claves_r != claves_e:
            faltan, de_mas = claves_e - claves_r, claves_r - claves_e
            problemas.append(f"servicio {i}: claves de datos distintas -- faltan {faltan or '{}'}, de más {de_mas or '{}'}")
    return problemas


def main():
    filas_costo = []
    for archivo, fixture, mime in CASOS:
        contenido = (DOCS_DIR / archivo).read_bytes()
        esperado = json.loads((FIXTURES_DIR / fixture).read_text(encoding="utf-8"))
        esperado.pop("_comentario_fixture", None)

        print(f"\n=== {archivo} ===")
        try:
            resultado = parseo.parsear_documento(contenido, mime)
        except parseo.ErrorParseo as e:
            print(f"  ERROR DE PARSEO: {e}")
            continue

        m = resultado["medicion"]
        filas_costo.append((archivo, m))
        servicios = resultado.get("servicios", [])
        print(f"  modelo={m['modelo']}  entrada={m['tokensEntrada']}  salida={m['tokensSalida']}  costo=USD {m['costoUsd']:.5f}  {m['segundos']}s")

        problemas = comparar(servicios, esperado.get("servicios", []))
        if not problemas:
            print(f"  OK -- {len(servicios)} servicio(s), coincide con el fixture en los campos clave")
        else:
            print(f"  DIFERENCIAS ({len(problemas)}):")
            for p in problemas:
                print(f"    - {p}")

    if filas_costo:
        total_in = sum(m["tokensEntrada"] for _, m in filas_costo)
        total_out = sum(m["tokensSalida"] for _, m in filas_costo)
        total_usd = sum(m["costoUsd"] for _, m in filas_costo)
        print("\n=== Costo total (\"un viaje documentado\", ver analisis-costos-pricing-validacion-peregrí.md §2) ===")
        for archivo, m in filas_costo:
            print(f"  {archivo:60s} {m['tokensEntrada']:>6} in  {m['tokensSalida']:>6} out  USD {m['costoUsd']:.5f}  {m['segundos']}s")
        print(f"  {'TOTAL':60s} {total_in:>6} in  {total_out:>6} out  USD {total_usd:.5f}")
        print("  Referencia del análisis de costos: USD 0.03-0.05 por viaje documentado (estimado sobre GPT-5.4 mini).")


if __name__ == "__main__":
    main()
