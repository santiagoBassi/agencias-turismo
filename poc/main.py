"""
POC del panel de agencia (Peregrí): API en FastAPI + JSON como base de datos.

Sin auth, sin base de datos real -- el objetivo es probar de punta a punta que
el parseo de documentos con Gemini funciona y medir su costo real (ver
../analisis-costos-pricing-validacion-peregrí.md). Todo el estado vive en
db.json, se relee entero en cada request y se reescribe entero en cada mutación:
para una POC de un solo usuario alcanza y sobra, no hace falta una base de
datos de verdad todavía.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import tempfile
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import eventos
import parseo
import vista

load_dotenv()

RAIZ = Path(__file__).resolve().parent
STATIC_DIR = RAIZ / "static"
UPLOADS_DIR = RAIZ / "uploads"
DB_PATH = RAIZ / "db.json"
UPLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Peregrí POC")

# db.json se lee entero y se reescribe entero (ver guardar_db) -- si dos subidas
# de documentos concurrentes hacen su propio cargar_db()/guardar_db() sin
# coordinarse, la segunda en guardar pisa los cambios de la primera ("lost
# update"). Este lock serializa sólo esas secciones de lectura-modificación-
# escritura; la llamada lenta a Gemini (parseo.parsear_documento) queda afuera
# a propósito para que N subidas sí corran en paralelo.
db_lock = asyncio.Lock()

# Cuántos documentos como máximo llaman a Gemini al mismo tiempo. Subir muchos
# archivos juntos dispara un request por archivo (ver POST /documentos) -- sin
# este tope, tirar 20+ documentos a la vez satura la API y termina devolviendo
# 429 para todos. Overrideable por .env para ajustar según el rate limit real
# de la cuenta.
GEMINI_MAX_CONCURRENTE = int(os.environ.get("GEMINI_MAX_CONCURRENTE", "4"))
gemini_semaforo = asyncio.Semaphore(GEMINI_MAX_CONCURRENTE)


# ── Persistencia (JSON como base de datos) ───────────────────────────────────
def _db_default() -> dict:
    return {
        "agency": {
            "name": "Hybris Turismo",
            "email": "hola@hybristurismo.com",
            "logo": "✈",
            "logoImg": None,
            "color": "#0e7490",
            "civitatisUrl": None,
        },
        "travelers": [],
        "trips": [],
    }


def cargar_db() -> dict:
    if not DB_PATH.exists():
        db = _db_default()
        guardar_db(db)
        return db
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def guardar_db(db: dict) -> None:
    """Escritura atómica: a un temp en el mismo directorio + os.replace, para no
    dejar db.json a medio escribir si el proceso se corta en el medio."""
    fd, tmp_path = tempfile.mkstemp(dir=RAIZ, prefix=".db-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, DB_PATH)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def nuevo_id(prefijo: str) -> str:
    return f"{prefijo}_{uuid.uuid4().hex[:10]}"


def _tokens_nombre(nombre: str | None) -> list[str]:
    """Normalización conservadora para comparar nombres de viajeros.

    No se usa para mostrar ni reescribir el nombre impreso: sólo permite
    reconocer capitalización, tildes, puntuación y orden de palabras.
    """
    if not nombre:
        return []
    sin_acentos = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode()
    limpio = "".join(caracter.lower() if caracter.isalnum() else " " for caracter in sin_acentos)
    return sorted(token for token in limpio.split() if token)


def _distancia_edicion(izquierda: str, derecha: str) -> int:
    """Distancia de Levenshtein pequeña, sin dependencia externa."""
    if izquierda == derecha:
        return 0
    if len(izquierda) < len(derecha):
        izquierda, derecha = derecha, izquierda
    fila_anterior = list(range(len(derecha) + 1))
    for indice_izquierda, caracter_izquierda in enumerate(izquierda, 1):
        fila_actual = [indice_izquierda]
        for indice_derecha, caracter_derecha in enumerate(derecha, 1):
            costo = 0 if caracter_izquierda == caracter_derecha else 1
            fila_actual.append(min(
                fila_actual[-1] + 1,
                fila_anterior[indice_derecha] + 1,
                fila_anterior[indice_derecha - 1] + costo,
            ))
        fila_anterior = fila_actual
    return fila_anterior[-1]


def _confianza_nombre(nombre_documento: str | None, nombre_canonico: str | None) -> float:
    """Da 1 para el mismo nombre y .9 para una única errata menor.

    La variante menor exige la misma cantidad de palabras, al menos una palabra
    idéntica y una sola palabra con distancia de edición uno. Así
    ``Camino Vanesa`` puede mapearse a ``Vanesa Caminos``, pero no se fuerza un
    match amplio entre personas distintas.
    """
    tokens_documento = _tokens_nombre(nombre_documento)
    tokens_canonicos = _tokens_nombre(nombre_canonico)
    if not tokens_documento or not tokens_canonicos:
        return 0
    if tokens_documento == tokens_canonicos:
        return 1.0
    if len(tokens_documento) != len(tokens_canonicos) or len(tokens_documento) < 2:
        return 0
    diferencias = [
        (documento, canonico)
        for documento, canonico in zip(tokens_documento, tokens_canonicos)
        if documento != canonico
    ]
    if len(diferencias) == 1 and _distancia_edicion(*diferencias[0]) == 1:
        return 0.9
    return 0


def _resolver_viajero(nombre: str | None, viajeros: list[dict]) -> tuple[dict | None, float]:
    """Busca un único viajero asignado que coincida de forma segura."""
    coincidencias = [
        (viajero, _confianza_nombre(nombre, viajero.get("name")))
        for viajero in viajeros
    ]
    mejor_confianza = max((confianza for _, confianza in coincidencias), default=0)
    candidatos = [viajero for viajero, confianza in coincidencias if confianza == mejor_confianza and confianza > 0]
    return (candidatos[0], mejor_confianza) if len(candidatos) == 1 else (None, 0)


def reconciliar_viajeros_servicios(servicios: list[dict], viajeros: list[dict]) -> None:
    """Completa de forma determinística el match que el modelo dejó incompleto.

    ``nombreEnDocumento`` siempre conserva la evidencia original. Cuando hay un
    candidato único entre los viajeros asignados, se guarda su id y su nombre
    canónico para que la agrupación no convierta una errata del proveedor en una
    persona adicional.
    """
    viajeros_por_id = {viajero.get("id"): viajero for viajero in viajeros if viajero.get("id")}
    for servicio in servicios:
        for viajero_documento in servicio.get("viajeros") or []:
            nombre_fuente = viajero_documento.get("nombreEnDocumento") or viajero_documento.get("nombreNormalizado")
            viajero_resuelto, confianza = _resolver_viajero(nombre_fuente, viajeros)
            id_devuelto = viajero_documento.get("viajeroId")

            # Un ID del modelo sólo es confiable si pertenece al viaje y la
            # evidencia textual lleva a esa misma persona. Sin nombre legible,
            # conservarlo evita perder un match explícito del documento.
            if viajero_resuelto is None and not nombre_fuente and id_devuelto in viajeros_por_id:
                viajero_resuelto, confianza = viajeros_por_id[id_devuelto], 1.0

            if viajero_resuelto is None:
                viajero_documento["viajeroId"] = None
                continue

            viajero_documento["viajeroId"] = viajero_resuelto["id"]
            viajero_documento["nombreNormalizado"] = viajero_resuelto["name"]
            viajero_documento["confianzaMatch"] = confianza


def procesar_servicios_parseados(servicios_raw: list[dict], documento_id: str, *, confirmado: bool = False) -> list[dict]:
    """Asigna ids reales a los servicios que acaba de devolver Gemini y remapea
    `complementoDe` (que llega como `claveLocal` intra-respuesta, ver
    esquema-servicio.schema.json) a esos ids reales -- si no, el link al padre se
    pierde en cuanto se persiste. Compartido entre la subida normal
    (subir_documento) y el script de re-parseo (reparsear_documentos.py)."""
    mapa_ids = {s.get("claveLocal"): nuevo_id("svc") for s in servicios_raw}
    servicios_out = []
    for s in servicios_raw:
        s["id"] = mapa_ids[s.get("claveLocal")]
        if s.get("complementoDe"):
            s["complementoDe"] = mapa_ids.get(s["complementoDe"], s["complementoDe"])
        s["documentoId"] = documento_id
        s["confirmado"] = confirmado
        s["origenDatos"] = "ia"
        servicios_out.append(s)
    return servicios_out


def _buscar_trip(db: dict, tid: str) -> dict | None:
    return next((t for t in db["trips"] if t["id"] == tid), None)


def _fecha_es(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def _es_paso_itinerario(evento: dict) -> bool:
    representante = evento["representante"]
    return not representante.get("esComplemento") and (representante.get("temporal") or {}).get("modo") != "transversal"


def _alerta_viajeros_evento(evento: dict, traveler_ids: list[str], resoluciones: dict) -> dict | None:
    """Devuelve la alerta pendiente o resuelta de un paso del itinerario.

    La huella incorpora los viajeros esperados y detectados. Si cualquiera de
    los dos cambia después de una resolución, la agencia vuelve a verla.
    """
    if not _es_paso_itinerario(evento):
        return None
    esperados = len(set(traveler_ids))
    viajeros_detectados = evento.get("viajerosUnion") or []
    detectados = len(viajeros_detectados)
    if not esperados or detectados == esperados:
        return None
    identidades_detectadas = sorted(
        str(viajero.get("viajeroId") or "nombre:" + " ".join(_tokens_nombre(
            viajero.get("nombreNormalizado") or viajero.get("nombreEnDocumento")
        )))
        for viajero in viajeros_detectados
    )
    base_huella = json.dumps(
        {"esperados": sorted(set(traveler_ids)), "detectados": identidades_detectadas},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    huella = hashlib.sha1(base_huella.encode("utf-8")).hexdigest()
    resolucion = resoluciones.get(evento["id"], {}) if isinstance(resoluciones, dict) else {}
    if not isinstance(resolucion, dict):
        resolucion = {}
    return {
        "esperados": esperados,
        "detectados": detectados,
        "pendiente": resolucion.get("huella") != huella,
        "huella": huella,
    }


def _alerta_viajeros_ui(alerta: dict | None) -> dict | None:
    if alerta is None:
        return None
    return {clave: alerta[clave] for clave in ("esperados", "detectados", "pendiente")}


EXT_POR_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _extension_de(nombre_original: str | None, mime_type: str) -> str:
    if nombre_original:
        ext = Path(nombre_original).suffix
        if ext:
            return ext
    return EXT_POR_MIME.get(mime_type) or mimetypes.guess_extension(mime_type) or ".bin"


ICONO_TIPO_DOC = {
    "e_ticket": "✈", "voucher_hotel": "🏨", "voucher_traslado": "🚐",
    "voucher_excursion": "🗺", "voucher_paquete": "📦", "entrada": "🎟",
    "poliza_seguro": "🛡", "boarding_pass": "✈", "otro": "📄",
}


# ── Construcción del estado para el front (misma forma que el prototipo) ────
def construir_estado(db: dict) -> dict:
    trips_out = []
    for trip in db["trips"]:
        documentos_por_id = {documento["id"]: documento for documento in trip["documentos"]}
        viajeros_asignados = [
            viajero for viajero in db["travelers"] if viajero["id"] in trip["travelerIds"]
        ]
        servicios_confirmados = [
            s for documento in trip["documentos"] for s in documento["servicios"] if s.get("confirmado")
        ]
        # Corrige en memoria documentos históricos que se guardaron antes del
        # reconciliador. La fuente original no se reescribe durante un GET.
        reconciliar_viajeros_servicios(servicios_confirmados, viajeros_asignados)
        # Un mismo evento del mundo real (vuelo, tren, traslado) puede haber
        # entrado en N documentos distintos -- típicamente un viaje multipasajero
        # con un e-ticket/pasaje por persona (ver eventos.py). Se agrupa acá, en
        # lectura, sin fusionar nada: cada servicio sigue existiendo 1:1 con su
        # documento, el evento sólo decide qué fila del itinerario comparten.
        eventos_trip = eventos.agrupar_en_eventos(servicios_confirmados)
        alertas_viajeros_por_evento = {
            evento["id"]: _alerta_viajeros_evento(
                evento,
                trip["travelerIds"],
                trip.get("revisionesViajerosPorEvento", {}),
            )
            for evento in eventos_trip
        }
        # Un ajuste manual nunca reescribe la extracción original (por ejemplo,
        # el rango real de check-in/check-out de un hotel). Es una ancla efectiva
        # sólo para el orden del itinerario y se replica en todos los servicios
        # fuente de un mismo evento agrupado.
        horarios_itinerario_por_evento = {}
        for ev in eventos_trip:
            hora_original = ((ev["representante"].get("temporal") or {}).get("inicio") or {}).get("fechaHoraLocal")
            horas_manuales = {
                (servicio.get("ajusteItinerario") or {}).get("fechaHoraEfectiva")
                for servicio in ev["servicios"]
                if (servicio.get("ajusteItinerario") or {}).get("fechaHoraEfectiva")
            }
            # El endpoint mantiene el valor idéntico en todo el evento. Si una
            # edición vieja dejara valores contradictorios, se conserva el orden
            # extraído hasta que el agenciero vuelva a guardar un ajuste.
            hora_manual = next(iter(horas_manuales)) if len(horas_manuales) == 1 else None
            horarios_itinerario_por_evento[ev["id"]] = {
                "efectiva": hora_manual or hora_original,
                "original": hora_original,
                "ajustada": hora_manual is not None,
            }
        # `requiereRevision` debe expresar trabajo pendiente, no la alerta
        # histórica de Gemini. Si el agenciero ya confirmó el documento fuente,
        # el evento deja de advertirlo en Servicios e Itinerario.
        revisiones_pendientes_por_evento = {
            ev["id"]: any(
                (servicio.get("extraccion") or {}).get("requiereRevision")
                and not (documentos_por_id.get(servicio.get("documentoId")) or {}).get("revisionConfirmada")
                for servicio in ev["servicios"]
            )
            for ev in eventos_trip
        }
        # complementoDe (ver subir_documento) ya apunta al id real del servicio
        # padre, pero las filas del itinerario ahora son eventos -- este mapa
        # traduce "soy complemento del servicio X" a "soy complemento del evento
        # que contiene a X", que es lo que el front puede buscar.
        evento_de_servicio = {s["id"]: ev["id"] for ev in eventos_trip for s in ev["servicios"]}

        # La pestaña Servicios muestra categorías separadas; ordenamos primero
        # todos los eventos por su inicio para que, al agregarlos a cada categoría,
        # cada lista conserve cronología. Los servicios sin fecha quedan al final.
        def clave_cronologica(ev: dict) -> tuple[bool, str]:
            hora = horarios_itinerario_por_evento[ev["id"]]["efectiva"]
            return (hora is None, hora or "")

        eventos_ordenados = sorted(eventos_trip, key=clave_cronologica)

        services = {"transport": [], "hotel": [], "excursions": [], "insurance": []}
        for ev in eventos_ordenados:
            item = vista.servicio_item_ui(ev["representante"])
            item["id"] = ev["id"]
            item["requiereRevision"] = revisiones_pendientes_por_evento[ev["id"]]
            item["alertaViajeros"] = _alerta_viajeros_ui(alertas_viajeros_por_evento[ev["id"]])
            item["horaItinerario"] = horarios_itinerario_por_evento[ev["id"]]["efectiva"]
            item["horarioAjustado"] = horarios_itinerario_por_evento[ev["id"]]["ajustada"]
            cantidad_viajeros = len(ev["viajerosUnion"])
            if cantidad_viajeros > 1:
                badge = f"👥 {cantidad_viajeros} viajeros"
                item["tag"] = f"{item['tag']} · {badge}" if item.get("tag") else badge
            services[vista.categoria_de(ev["representante"]["tipo"])].append(item)

        docs_out = []
        revisiones_pendientes = []
        for documento in trip["documentos"]:
            parseo_documento = documento.get("parseo") or {}
            if documento.get("confirmado"):
                tipo_doc = (documento.get("documento") or {}).get("tipoDocumentoDetectado")
                docs_out.append({
                    "id": documento["id"],
                    "icon": ICONO_TIPO_DOC.get(tipo_doc, "📄"),
                    "name": documento["nombreOriginal"],
                    "sub": f"Subido {_fecha_es(documento['subidoEn'])} · Cargado por IA",
                    "tag": "⚠ Revisar" if parseo_documento.get("estado") == "revision" and not documento.get("revisionConfirmada") else "✓ Parseado",
                    "archivo": f"/api/archivos/{documento['id']}/{quote(documento['nombreOriginal'])}",
                })

            # Un parseo con advertencias necesita una confirmación humana aunque
            # el documento ya haya quedado disponible en el viaje. La resolución
            # se persiste por separado para que no vuelva a aparecer en cada carga.
            if parseo_documento.get("estado") == "revision" and not documento.get("revisionConfirmada"):
                tipo_doc = (documento.get("documento") or {}).get("tipoDocumentoDetectado")
                servicios_revision = []
                for servicio in documento.get("servicios") or []:
                    extraccion = servicio.get("extraccion") or {}
                    servicios_revision.append({
                        "icon": vista.icono_de(servicio.get("tipo", "otro")),
                        "titulo": servicio.get("titulo") or "Servicio detectado",
                        "subtitulo": servicio.get("subtitulo"),
                        "motivoRevision": extraccion.get("motivoRevision"),
                        "requiereRevision": bool(extraccion.get("requiereRevision")),
                        "filas": vista.filas_desde_servicio(servicio),
                    })
                revisiones_pendientes.append({
                    "id": documento["id"],
                    "icon": ICONO_TIPO_DOC.get(tipo_doc, "📄"),
                    "name": documento["nombreOriginal"],
                    "archivo": f"/api/archivos/{documento['id']}/{quote(documento['nombreOriginal'])}",
                    "tipoDocumento": tipo_doc,
                    "confianzaGlobal": (documento.get("documento") or {}).get("confianzaGlobal"),
                    "modelo": parseo_documento.get("modelo"),
                    "servicios": servicios_revision,
                })

        slots = [len(services["transport"]) > 0, len(services["hotel"]) > 0,
                 len(services["insurance"]) > 0, len(services["excursions"]) > 0, len(docs_out) > 0]
        progreso = round(sum(slots) / len(slots) * 100)

        serviciosRicos = []
        for ev in eventos_trip:
            rep = ev["representante"]
            pasajes = []
            for s in ev["servicios"]:
                nombres = [v.get("nombreNormalizado") or v.get("nombreEnDocumento") for v in (s.get("viajeros") or [])]
                pasajes.append({
                    "servicioId": s["id"],
                    "documentoId": s.get("documentoId"),
                    "viajero": ", ".join(n for n in nombres if n) or None,
                    "filas": vista.filas_desde_servicio(s),
                })
            complemento_de = rep.get("complementoDe")
            serviciosRicos.append({
                **rep,
                "id": ev["id"],
                "complementoDe": evento_de_servicio.get(complemento_de, complemento_de),
                "icon": vista.icono_de(rep["tipo"]),
                "requiereRevision": revisiones_pendientes_por_evento[ev["id"]],
                "alertaViajeros": _alerta_viajeros_ui(alertas_viajeros_por_evento[ev["id"]]),
                "horaItinerario": horarios_itinerario_por_evento[ev["id"]]["efectiva"],
                "horaOriginal": horarios_itinerario_por_evento[ev["id"]]["original"],
                "horarioAjustado": horarios_itinerario_por_evento[ev["id"]]["ajustada"],
                "pasajes": pasajes,
                "viajerosUnion": ev["viajerosUnion"],
                "paxTotal": ev["paxTotal"],
            })

        trips_out.append({
            "id": trip["id"], "nombre": trip["nombre"], "tipo": trip["tipo"],
            "destinos": trip["destinos"], "travelerIds": trip["travelerIds"],
            "salida": trip["salida"], "vuelta": trip["vuelta"], "noches": trip["noches"],
            "services": services, "docs": docs_out, "reviewDocs": revisiones_pendientes,
            "serviciosRicos": serviciosRicos,
            "progreso": progreso,
        })
    return {"agency": db["agency"], "travelers": db["travelers"], "trips": trips_out}


# ── Modelos de request ────────────────────────────────────────────────────────
class NuevoViajero(BaseModel):
    name: str
    dni: str
    email: str | None = None
    phone: str | None = None


class Destino(BaseModel):
    ciudad: str
    pais: str | None = None
    flag: str | None = None


class NuevoViaje(BaseModel):
    nombre: str | None = None
    tipo: str = "ciudad"
    destinos: list[Destino] = []
    salida: str | None = None
    vuelta: str | None = None
    travelerIds: list[str] = []


class AsignarViajeros(BaseModel):
    travelerIds: list[str]


class EditarViaje(BaseModel):
    """Los datos editables de la ficha de un viaje existente.

    Los documentos y servicios no forman parte de este modelo a propósito: son
    evidencia cargada para el viaje y cambiar su nombre, destinos o fechas no
    debería borrar ni reescribir esa información.
    """
    nombre: str | None = None
    tipo: str = "ciudad"
    destinos: list[Destino]
    salida: str | None = None
    vuelta: str | None = None
    travelerIds: list[str] = []


class AjusteHorarioItinerario(BaseModel):
    fechaHoraEfectiva: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/estado")
def obtener_estado():
    return construir_estado(cargar_db())


@app.post("/api/viajeros")
def crear_viajero(body: NuevoViajero):
    name = body.name.strip()
    dni = body.dni.strip()
    if not name:
        raise HTTPException(400, "Ingresá un nombre.")
    if not dni:
        raise HTTPException(400, "Ingresá el DNI.")
    db = cargar_db()
    viajero = {
        "id": nuevo_id("trv"), "name": name, "dni": dni,
        "email": (body.email or "").strip() or "—",
        "phone": (body.phone or "").strip() or "—",
    }
    db["travelers"].append(viajero)
    guardar_db(db)
    return viajero


@app.post("/api/viajes")
def crear_viaje(body: NuevoViaje):
    destinos = [d.model_dump() for d in body.destinos if d.ciudad.strip()]
    if not destinos:
        raise HTTPException(400, "Ingresá al menos un destino.")
    nombre = (body.nombre or "").strip() or destinos[0]["ciudad"]

    noches = 0
    if body.salida and body.vuelta:
        try:
            noches = max(0, (datetime.fromisoformat(body.vuelta) - datetime.fromisoformat(body.salida)).days)
        except ValueError:
            pass

    db = cargar_db()
    ids_validos = {t["id"] for t in db["travelers"]}
    trip = {
        "id": nuevo_id("trp"), "nombre": nombre, "tipo": body.tipo, "destinos": destinos,
        "travelerIds": [tid for tid in body.travelerIds if tid in ids_validos],
        "salida": body.salida or None, "vuelta": body.vuelta or None, "noches": noches,
        "documentos": [],
    }
    db["trips"].append(trip)
    guardar_db(db)
    return {"id": trip["id"]}


@app.post("/api/viajes/{tid}/viajeros")
def asignar_viajeros(tid: str, body: AsignarViajeros):
    db = cargar_db()
    trip = _buscar_trip(db, tid)
    if trip is None:
        raise HTTPException(404, "Viaje no encontrado.")
    ids_validos = {t["id"] for t in db["travelers"]}
    for tvid in body.travelerIds:
        if tvid in ids_validos and tvid not in trip["travelerIds"]:
            trip["travelerIds"].append(tvid)
    guardar_db(db)
    return {"ok": True}


@app.patch("/api/viajes/{tid}")
def editar_viaje(tid: str, body: EditarViaje):
    """Actualiza la ficha del viaje sin afectar sus documentos ni servicios."""
    destinos = []
    for destino in body.destinos:
        ciudad = destino.ciudad.strip()
        if not ciudad:
            continue
        destinos.append({
            "ciudad": ciudad,
            "pais": (destino.pais or "").strip(),
            "flag": (destino.flag or "").strip(),
        })
    if not destinos:
        raise HTTPException(400, "Ingresá al menos un destino.")

    salida = body.salida.strip() if body.salida else None
    vuelta = body.vuelta.strip() if body.vuelta else None
    try:
        fecha_salida = datetime.strptime(salida, "%Y-%m-%d").date() if salida else None
        fecha_vuelta = datetime.strptime(vuelta, "%Y-%m-%d").date() if vuelta else None
    except ValueError as exc:
        raise HTTPException(400, "Las fechas deben tener el formato AAAA-MM-DD.") from exc
    if fecha_salida and fecha_vuelta and fecha_vuelta < fecha_salida:
        raise HTTPException(400, "La fecha de regreso no puede ser anterior a la salida.")

    db = cargar_db()
    trip = _buscar_trip(db, tid)
    if trip is None:
        raise HTTPException(404, "Viaje no encontrado.")

    ids_validos = {viajero["id"] for viajero in db["travelers"]}
    traveler_ids = list(dict.fromkeys(body.travelerIds))
    ids_inexistentes = [viajero_id for viajero_id in traveler_ids if viajero_id not in ids_validos]
    if ids_inexistentes:
        raise HTTPException(400, "Uno de los viajeros seleccionados ya no existe.")

    trip.update({
        "nombre": (body.nombre or "").strip() or destinos[0]["ciudad"],
        "tipo": body.tipo,
        "destinos": destinos,
        "salida": salida,
        "vuelta": vuelta,
        "noches": (fecha_vuelta - fecha_salida).days if fecha_salida and fecha_vuelta else 0,
        "travelerIds": traveler_ids,
    })
    guardar_db(db)
    return {"ok": True}


@app.patch("/api/viajes/{tid}/itinerario/{eid}/horario")
def ajustar_horario_itinerario(tid: str, eid: str, body: AjusteHorarioItinerario):
    """Guarda o restaura el ancla manual usada sólo para ordenar un evento.

    El evento es una vista agrupada (por ejemplo, varios pasajes del mismo
    vuelo), por eso el ajuste se persiste en cada servicio fuente que lo forma.
    """
    db = cargar_db()
    trip = _buscar_trip(db, tid)
    if trip is None:
        raise HTTPException(404, "Viaje no encontrado.")

    servicios_confirmados = [
        servicio
        for documento in trip["documentos"]
        for servicio in documento["servicios"]
        if servicio.get("confirmado")
    ]
    evento = next((ev for ev in eventos.agrupar_en_eventos(servicios_confirmados) if ev["id"] == eid), None)
    if evento is None:
        raise HTTPException(404, "Paso del itinerario no encontrado.")

    representante = evento["representante"]
    modo_temporal = (representante.get("temporal") or {}).get("modo")
    if modo_temporal == "transversal" or representante.get("esComplemento"):
        raise HTTPException(400, "Este servicio no participa de la línea cronológica.")

    fecha_hora = body.fechaHoraEfectiva
    if fecha_hora is not None:
        if "T" not in fecha_hora:
            raise HTTPException(400, "Ingresá una fecha y hora válidas.")
        try:
            fecha_parseada = datetime.fromisoformat(fecha_hora)
        except ValueError as exc:
            raise HTTPException(400, "Ingresá una fecha y hora válidas.") from exc
        if fecha_parseada.tzinfo is not None:
            raise HTTPException(400, "La fecha y hora deben ser locales, sin zona horaria.")
        fecha_hora = fecha_parseada.isoformat(timespec="minutes")

    for servicio in evento["servicios"]:
        if fecha_hora is None:
            servicio.pop("ajusteItinerario", None)
        else:
            servicio["ajusteItinerario"] = {
                "fechaHoraEfectiva": fecha_hora,
                "actualizadoEn": datetime.now().isoformat(timespec="seconds"),
            }
    guardar_db(db)
    return {"ok": True, "fechaHoraEfectiva": fecha_hora}


@app.post("/api/viajes/{tid}/itinerario/{eid}/revision-viajeros/confirmar")
def confirmar_revision_viajeros(tid: str, eid: str):
    """Confirma una diferencia de viajeros de un evento sin alterar su fuente."""
    db = cargar_db()
    trip = _buscar_trip(db, tid)
    if trip is None:
        raise HTTPException(404, "Viaje no encontrado.")

    viajeros_asignados = [
        viajero for viajero in db["travelers"] if viajero["id"] in trip["travelerIds"]
    ]
    servicios_confirmados = [
        servicio
        for documento in trip["documentos"]
        for servicio in documento["servicios"]
        if servicio.get("confirmado")
    ]
    reconciliar_viajeros_servicios(servicios_confirmados, viajeros_asignados)
    evento = next((ev for ev in eventos.agrupar_en_eventos(servicios_confirmados) if ev["id"] == eid), None)
    if evento is None or not _es_paso_itinerario(evento):
        raise HTTPException(404, "Paso del itinerario no encontrado.")

    resoluciones = trip.setdefault("revisionesViajerosPorEvento", {})
    if not isinstance(resoluciones, dict):
        resoluciones = trip["revisionesViajerosPorEvento"] = {}
    alerta = _alerta_viajeros_evento(evento, trip["travelerIds"], resoluciones)
    if alerta is None:
        raise HTTPException(400, "La cantidad de viajeros de este paso ya coincide con la del viaje.")

    resoluciones[eid] = {
        "huella": alerta["huella"],
        "resueltaEn": datetime.now().isoformat(timespec="seconds"),
    }
    guardar_db(db)
    return {"ok": True, "esperados": alerta["esperados"], "detectados": alerta["detectados"]}


@app.post("/api/viajes/{tid}/documentos")
async def subir_documento(tid: str, archivo: UploadFile = File(...), forzar: bool = Form(False)):
    contenido = await archivo.read()
    mime_type = archivo.content_type or mimetypes.guess_type(archivo.filename or "")[0] or "application/octet-stream"
    hash_archivo = hashlib.sha256(contenido).hexdigest()

    async with db_lock:
        db = cargar_db()
        trip = _buscar_trip(db, tid)
        if trip is None:
            raise HTTPException(404, "Viaje no encontrado.")
        # Precondición del modelo de datos (parseo/MODELO-DATOS.md § Precondiciones antes
        # de parsear): sin pasajeros asignados no hay {{CONTEXTO_VIAJE}} que valga la pena.
        if not trip["travelerIds"]:
            raise HTTPException(400, "Este viaje todavía no tiene viajeros asignados -- asigná al menos uno antes de subir documentos.")
        # Mismo archivo (byte a byte) subido dos veces al mismo viaje, con o sin
        # el mismo nombre -- no es un caso hipotético: pasó en la práctica con dos
        # PDFs de traslados resubidos con nombres distintos, y cada resubida le
        # cuesta plata a la agencia (una llamada a Gemini de más). En vez de
        # bloquear en silencio, se lo avisamos al agenciero y que decida
        # (`forzar=true` para subirlo igual): mismo patrón human-in-the-loop que
        # ya usa el resto del flujo de parseo.
        if not forzar:
            existente = next(
                (d for d in trip["documentos"] if d.get("archivoSha256") == hash_archivo), None
            )
            if existente is not None:
                raise HTTPException(409, detail={
                    "tipo": "archivo_duplicado",
                    "mensaje": f'Este archivo ya lo subiste como "{existente["nombreOriginal"]}".',
                    "documentoExistenteId": existente["id"],
                    "nombreExistente": existente["nombreOriginal"],
                })
        viajeros_asignados = [t for t in db["travelers"] if t["id"] in trip["travelerIds"]]
        servicios_confirmados = [s for d in trip["documentos"] for s in d["servicios"] if s.get("confirmado")]

    documento_id = nuevo_id("doc")
    ruta = UPLOADS_DIR / f"{documento_id}{_extension_de(archivo.filename, mime_type)}"
    ruta.write_bytes(contenido)

    documento = {
        "id": documento_id,
        "nombreOriginal": archivo.filename or documento_id,
        "archivoPath": str(ruta),
        "archivoSha256": hash_archivo,
        "mimeType": mime_type,
        "subidoEn": datetime.now().isoformat(timespec="seconds"),
        "confirmado": False,
    }

    # Fuera del lock y detrás de un semáforo: acá es donde se espera la red hacia
    # Gemini (varios segundos), así que N subidas concurrentes de verdad se
    # solapan en vez de hacer cola una detrás de otra. to_thread() porque el SDK
    # de genai que usa parseo.py es síncrono/bloqueante.
    try:
        async with gemini_semaforo:
            resultado = await asyncio.to_thread(
                parseo.parsear_documento,
                contenido, mime_type,
                viaje=trip, viajeros=viajeros_asignados, servicios_confirmados=servicios_confirmados,
            )
    except parseo.ErrorParseo as exc:
        documento["parseo"] = {
            "estado": "error", "modelo": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            "tokensEntrada": 0, "tokensSalida": 0, "costoUsd": 0, "segundos": 0, "errorMsg": str(exc),
        }
        documento["documento"] = None
        documento["servicios"] = []
        async with db_lock:
            db = cargar_db()
            trip = _buscar_trip(db, tid)
            if trip is not None:
                trip["documentos"].append(documento)
                guardar_db(db)
        raise HTTPException(502, detail=str(exc))

    medicion = resultado.pop("medicion")
    servicios_raw = resultado.get("servicios", [])
    reconciliar_viajeros_servicios(servicios_raw, viajeros_asignados)
    servicios_out = procesar_servicios_parseados(servicios_raw, documento_id)
    requiere_revision = any((s.get("extraccion") or {}).get("requiereRevision") for s in servicios_out)

    documento["parseo"] = {
        "estado": "revision" if requiere_revision else "parseado",
        "modelo": medicion["modelo"], "tokensEntrada": medicion["tokensEntrada"],
        "tokensSalida": medicion["tokensSalida"], "costoUsd": medicion["costoUsd"],
        "segundos": medicion["segundos"], "errorMsg": None,
    }
    documento["documento"] = resultado.get("documento")
    documento["servicios"] = servicios_out

    async with db_lock:
        db = cargar_db()
        trip = _buscar_trip(db, tid)
        if trip is None:
            raise HTTPException(404, "Viaje no encontrado (fue borrado mientras se parseaba el documento).")
        trip["documentos"].append(documento)
        guardar_db(db)

    return JSONResponse({
        "documentoId": documento_id,
        "estadoParseo": documento["parseo"]["estado"],
        "medicion": medicion,
        "documento": documento["documento"],
        "servicios": [
            {
                "id": s["id"], "tipo": s["tipo"], "titulo": s.get("titulo"),
                "subtitulo": s.get("subtitulo"), "icon": vista.icono_de(s["tipo"]),
                "requiereRevision": bool((s.get("extraccion") or {}).get("requiereRevision")),
                "filas": vista.filas_desde_servicio(s),
            }
            for s in servicios_out
        ],
    })


@app.post("/api/viajes/{tid}/documentos/{did}/confirmar")
def confirmar_documento(tid: str, did: str):
    db = cargar_db()
    trip = _buscar_trip(db, tid)
    if trip is None:
        raise HTTPException(404, "Viaje no encontrado.")
    documento = next((d for d in trip["documentos"] if d["id"] == did), None)
    if documento is None:
        raise HTTPException(404, "Documento no encontrado.")
    if documento["parseo"]["estado"] == "error":
        raise HTTPException(400, "Este documento no se pudo parsear -- no hay nada para confirmar.")
    documento["confirmado"] = True
    if documento["parseo"]["estado"] == "revision":
        documento["revisionConfirmada"] = True
        documento["revisionConfirmadaEn"] = datetime.now().isoformat(timespec="seconds")
    for s in documento["servicios"]:
        s["confirmado"] = True
    guardar_db(db)
    return {"ok": True}


@app.delete("/api/viajes/{tid}/documentos/{did}", status_code=204)
def descartar_documento(tid: str, did: str):
    db = cargar_db()
    trip = _buscar_trip(db, tid)
    if trip is None:
        raise HTTPException(404, "Viaje no encontrado.")
    idx = next((i for i, d in enumerate(trip["documentos"]) if d["id"] == did), None)
    if idx is None:
        raise HTTPException(404, "Documento no encontrado.")
    documento = trip["documentos"].pop(idx)
    Path(documento["archivoPath"]).unlink(missing_ok=True)
    guardar_db(db)


@app.get("/api/archivos/{did}/{filename}", include_in_schema=False)
def obtener_archivo(did: str, filename: str):
    db = cargar_db()
    for trip in db["trips"]:
        for documento in trip["documentos"]:
            if documento["id"] == did:
                ruta = Path(documento["archivoPath"])
                if not ruta.exists():
                    raise HTTPException(404, "El archivo ya no está en disco.")
                # El archivo se abre dentro de un iframe desde la app. Con la
                # disposición por defecto ("attachment"), el navegador fuerza
                # una descarga en lugar de renderizar PDFs e imágenes inline.
                return FileResponse(
                    ruta,
                    media_type=documento["mimeType"],
                    filename=documento["nombreOriginal"],
                    content_disposition_type="inline",
                )
    raise HTTPException(404, "Documento no encontrado.")
