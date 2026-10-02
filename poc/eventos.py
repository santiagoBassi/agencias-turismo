"""
Agrupa servicios ya parseados en "eventos" del itinerario cuando en realidad son
el mismo evento del mundo real repetido en varios documentos -- típicamente un
viaje multipasajero donde cada pasajero trae su propio e-ticket/pasaje del mismo
vuelo/tren/traslado (ver CONTEXTO-PROYECTO.md y parseo/MODELO-DATOS.md).

No fusiona nada: cada servicio persiste intacto, 1:1 con el documento que lo
generó. Un evento es una vista derivada en lectura (mismo patrón que describe
MODELO-DATOS.md para camposMostrar/icono: "DERIVADO POR CÓDIGO AL LEER -- NUNCA
ESCRITO POR LA IA") que agrupa N servicios bajo una misma fila del itinerario,
con el detalle disponible para ver cada pasaje por separado.

La deduplicación no puede vivir en el modelo: los documentos se parsean en
paralelo (ver main.py, asyncio.to_thread + semáforo) y cada uno se procesa sin
ver a los demás. La clave de agrupación de abajo está validada contra un viaje
real de 40 servicios (3 pasajeros, 32 documentos): agrupa en 24 eventos exactos,
sin falsos positivos. El PNR/localizador y el título NO sirven como clave: un
mismo vuelo puede tener dos PNR distintos (dos reservas separadas) y el mismo
tren puede salir con títulos distintos entre pasajes (ver el prompt, regla 9,
para la mitigación del lado del parseo).
"""
from __future__ import annotations

import hashlib
import unicodedata


def _normalizar(texto: str | None) -> str:
    """minúsculas, sin acentos, solo alfanumérico -- para comparar nombres de
    lugar que llegan con distinta capitalización/acentuación entre documentos."""
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return "".join(c for c in sin_acentos.lower() if c.isalnum())


def _lugar_clave(lugar: dict | None) -> str:
    """Código IATA/estación si existe, si no ciudad, si no nombre. Vacío si el
    servicio no tiene ubicación (hoteles, seguros, excursiones "transversales")."""
    if not isinstance(lugar, dict):
        return ""
    return _normalizar(lugar.get("codigo")) or _normalizar(lugar.get("ciudad")) or _normalizar(lugar.get("nombre"))


def clave_evento(servicio: dict) -> tuple[str, str, str, str]:
    """Identidad determinística de "a qué evento del mundo real pertenece este
    servicio". Dos servicios con la misma clave son el mismo evento."""
    ini = ((servicio.get("temporal") or {}).get("inicio") or {}).get("fechaHoraLocal") or ""
    ubicacion = servicio.get("ubicacion") or {}
    return (
        servicio.get("tipo") or "",
        ini,
        _lugar_clave(ubicacion.get("inicio")),
        _lugar_clave(ubicacion.get("fin")),
    )


def _id_evento(clave: tuple[str, str, str, str]) -> str:
    """Hash corto y determinístico de la clave -- estable entre requests mientras
    los servicios no cambien, sin necesidad de persistirlo (es derivado, como el
    resto de este módulo)."""
    cruda = "|".join(clave).encode("utf-8")
    return "evt_" + hashlib.sha1(cruda).hexdigest()[:10]


def _mejor_representante(servicios: list[dict]) -> dict:
    """El servicio del grupo con menos camposInciertos es el que se muestra en
    la fila del itinerario -- es, en promedio, el pasaje mejor extraído."""
    def cantidad_inciertos(s: dict) -> int:
        return len((s.get("extraccion") or {}).get("camposInciertos") or [])
    return min(servicios, key=cantidad_inciertos)


def _unir_viajeros(servicios: list[dict]) -> list[dict]:
    """Une viajeros[] de todos los pasajes del evento, sin duplicar personas.
    Dedup por viajeroId cuando existe; si no, por nombre normalizado. Si la misma
    persona aparece como "titular" en una copia y "acompanante" en otra (pasa: cada
    pasaje individual suele traer a su único viajero como "titular"), se queda con
    "titular"."""
    vistos: dict[str, dict] = {}
    orden: list[str] = []
    for s in servicios:
        for v in s.get("viajeros") or []:
            clave = v.get("viajeroId") or _normalizar(v.get("nombreNormalizado") or v.get("nombreEnDocumento"))
            if not clave:
                continue
            if clave not in vistos:
                vistos[clave] = dict(v)
                orden.append(clave)
            elif v.get("rol") == "titular":
                vistos[clave]["rol"] = "titular"
    return [vistos[c] for c in orden]


def _pax_total(servicios: list[dict]) -> int | None:
    """El pax.total más alto declarado entre las copias del grupo -- no se
    inventan personas, solo se toma el conteo más informativo que ya dieron los
    documentos."""
    totales = [((s.get("pax") or {}).get("total")) for s in servicios]
    totales = [t for t in totales if isinstance(t, int)]
    return max(totales) if totales else None


def agrupar_en_eventos(servicios: list[dict]) -> list[dict]:
    """Agrupa una lista de servicios (normalmente ya confirmados) en eventos.
    Un evento con 1 solo servicio es el caso normal, sin duplicados. Devuelve
    los eventos en el mismo orden relativo de aparición de su primer servicio."""
    grupos: dict[tuple, list[dict]] = {}
    orden: list[tuple] = []
    for s in servicios:
        clave = clave_evento(s)
        if clave not in grupos:
            grupos[clave] = []
            orden.append(clave)
        grupos[clave].append(s)

    eventos = []
    for clave in orden:
        grupo = grupos[clave]
        eventos.append({
            "id": _id_evento(clave),
            "claveEvento": clave,
            "representante": _mejor_representante(grupo),
            "servicios": grupo,
            "viajerosUnion": _unir_viajeros(grupo),
            "paxTotal": _pax_total(grupo),
            "requiereRevision": any((s.get("extraccion") or {}).get("requiereRevision") for s in grupo),
        })
    return eventos
