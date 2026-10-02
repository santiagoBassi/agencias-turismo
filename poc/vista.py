"""
Traduce un "servicio" tal como sale del schema de parseo (parseo/esquema-servicio*.json)
a las formas chicas que ya sabe pintar el prototipo del panel: una fila por caja de
servicio (transport/hotel/excursions/insurance), y una lista de filas etiqueta/valor
para la card de revisión y el detalle.

No implementa el registry `camposMostrar` por tipo que describe
parseo/MODELO-DATOS.md (§ Registry camposMostrar) -- para esta POC alcanza con un
recorrido genérico de `datos`, que es justo lo que hace falta para juzgar si el
parseo extrajo bien. El registry por tipo queda como refinamiento posterior.
"""
from __future__ import annotations

# tipo del schema -> categoría de caja del prototipo (state.trips[].services.*)
TIPO_A_CATEGORIA = {
    "vuelo": "transport",
    "tren": "transport",
    "bus": "transport",
    "ferry": "transport",
    "crucero": "transport",
    "traslado": "transport",
    "alquiler_auto": "transport",
    "hotel": "hotel",
    "seguro": "insurance",
    # excursion, entrada, circuito, paquete, otro -> excursions (catch-all)
}

ICONOS = {
    "vuelo": "✈", "tren": "🚆", "bus": "🚌", "ferry": "⛴", "crucero": "🚢",
    "traslado": "🚐", "alquiler_auto": "🚗", "hotel": "🏨", "excursion": "🗺",
    "entrada": "🎟", "circuito": "🧭", "paquete": "📦", "seguro": "🛡", "otro": "📄",
}

# clave en `datos` -> etiqueta en español para las filas de la card de revisión.
ETIQUETAS_DATOS = {
    "aerolinea": "Aerolínea", "codigoAerolinea": "Código aerolínea",
    "numeroVuelo": "Vuelo", "cabina": "Cabina", "duracion": "Duración",
    "aeronave": "Aeronave", "equipajeBodega": "Equipaje en bodega",
    "equipajeCabina": "Equipaje de cabina", "numeroETicket": "N.º e-ticket",
    "estadoVuelo": "Estado del vuelo", "escalas": "Escalas", "asientos": "Asientos",
    "nombreHotel": "Hotel", "categoria": "Categoría", "direccion": "Dirección",
    "zona": "Zona", "noches": "Noches", "horaCheckIn": "Hora de check-in",
    "horaCheckOut": "Hora de check-out", "telefonoHotel": "Teléfono del hotel",
    "localizadorExterno": "Localizador externo", "modalidad": "Modalidad",
    "esperaMaxima": "Espera máxima", "direccionServicio": "Dirección del servicio",
    "nombre": "Nombre", "idiomaGuia": "Idioma del guía",
    "lugarRecogida": "Lugar de recogida", "horaRecogida": "Hora de recogida",
    "incluye": "Incluye", "noIncluye": "No incluye",
    "ciudadesVisitadas": "Ciudades visitadas", "atraccion": "Atracción",
    "tipoPase": "Tipo de pase", "validezDesde": "Válido desde",
    "validezHasta": "Válido hasta", "diasDeUso": "Días de uso",
    "numeroConfirmacion": "N.º de confirmación", "codigoBarras": "Código de barras",
    "restricciones": "Restricciones", "categoriaVehiculo": "Categoría de vehículo",
    "transmision": "Transmisión", "lugarRetiro": "Lugar de retiro",
    "horaRetiro": "Hora de retiro", "lugarDevolucion": "Lugar de devolución",
    "horaDevolucion": "Hora de devolución", "coberturas": "Coberturas",
    "kilometraje": "Kilometraje", "serviciosComponentes": "Servicios incluidos",
    "aseguradora": "Aseguradora", "numeroPoliza": "N.º de póliza", "plan": "Plan",
    "vigenciaDesde": "Vigencia desde", "vigenciaHasta": "Vigencia hasta",
    "telefonoSOS": "Teléfono SOS", "territorio": "Territorio",
}

# claves cuyo valor es un sub-objeto {nombre,ciudad,pais,...} en vez de un escalar.
CAMPOS_UBICACION_ANIDADA = {"origen", "destino", "desde", "hasta"}
ETIQUETAS_UBICACION_ANIDADA = {
    "origen": "Origen", "destino": "Destino", "desde": "Desde", "hasta": "Hasta",
}


def _fmt_valor(v) -> str | None:
    """Convierte un valor crudo de `datos` en el string a mostrar, o None si está vacío."""
    if v is None:
        return None
    if isinstance(v, list):
        items = [str(x) for x in v if x not in (None, "")]
        return ", ".join(items) if items else None
    if isinstance(v, bool):
        return "Sí" if v else "No"
    s = str(v).strip()
    return s or None


def _fmt_ubicacion(u: dict) -> str | None:
    if not isinstance(u, dict):
        return None
    partes = [u.get("nombre"), u.get("ciudad"), u.get("pais")]
    partes = [p for p in partes if p]
    return ", ".join(partes) if partes else None


def filas_desde_servicio(servicio: dict) -> list[dict]:
    """Arma la lista de filas {etiqueta, valor, incierto} para la card de revisión
    y el detalle: primero los campos tipados de `datos`, luego `referencias[]` y
    por último `camposExtra[]` -- en ese orden, tal como describe MODELO-DATOS.md."""
    filas = []
    inciertos = set((servicio.get("extraccion") or {}).get("camposInciertos") or [])
    datos = servicio.get("datos") or {}

    for clave, valor in datos.items():
        if clave in CAMPOS_UBICACION_ANIDADA:
            texto = _fmt_ubicacion(valor)
        elif clave == "habitaciones" and isinstance(valor, list):
            partes = []
            for h in valor:
                if not isinstance(h, dict):
                    continue
                sub = [h.get("descripcion"), h.get("regimen")]
                sub = [s for s in sub if s]
                if h.get("ocupantes"):
                    sub.append("Ocupantes: " + ", ".join(h["ocupantes"]))
                if sub:
                    partes.append(" · ".join(sub))
            texto = " / ".join(partes) if partes else None
            clave_etq = "Habitación"
            if texto:
                filas.append({"etiqueta": clave_etq, "valor": texto, "incierto": clave in inciertos})
            continue
        elif clave == "vueloReferencia" and isinstance(valor, dict):
            sub = [valor.get("numero"), valor.get("hora"), valor.get("aeropuerto")]
            sub = [s for s in sub if s]
            texto = " · ".join(sub) if sub else None
            if texto:
                filas.append({"etiqueta": "Vuelo de referencia", "valor": texto, "incierto": clave in inciertos})
            continue
        elif clave == "puntoEncuentro":
            texto = _fmt_valor(valor)
        else:
            texto = _fmt_valor(valor)
        if texto is None:
            continue
        etiqueta = ETIQUETAS_UBICACION_ANIDADA.get(clave) or ETIQUETAS_DATOS.get(clave) or clave
        filas.append({"etiqueta": etiqueta, "valor": texto, "incierto": clave in inciertos})

    for ref in servicio.get("referencias") or []:
        if ref.get("valor"):
            filas.append({"etiqueta": ref.get("etiqueta") or "Referencia", "valor": ref["valor"], "incierto": False})

    for extra in servicio.get("camposExtra") or []:
        if extra.get("valor"):
            filas.append({"etiqueta": extra.get("etiqueta") or "Dato adicional", "valor": extra["valor"], "incierto": False})

    return filas


def categoria_de(tipo: str) -> str:
    return TIPO_A_CATEGORIA.get(tipo, "excursions")


def icono_de(tipo: str) -> str:
    return ICONOS.get(tipo, "📄")


def _fecha_corta(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        fecha, hora = iso.split("T")
        y, m, d = fecha.split("-")
        return f"{d}/{m}/{y}" + (f" {hora}" if hora and hora != "00:00" else "")
    except Exception:
        return iso


def resumen_temporal(servicio: dict) -> str | None:
    """Un string corto de fecha para el detalle en las listas de servicios."""
    temporal = servicio.get("temporal") or {}
    modo = temporal.get("modo")
    inicio = (temporal.get("inicio") or {}).get("fechaHoraLocal")
    fin = (temporal.get("fin") or {}).get("fechaHoraLocal")
    if modo == "transversal":
        ini, f = _fecha_corta(inicio), _fecha_corta(fin)
        return f"{ini} – {f}" if ini and f else "Vigente todo el viaje"
    if modo == "sin_fecha":
        return None
    if fin and fin != inicio:
        return f"{_fecha_corta(inicio)} → {_fecha_corta(fin)}"
    return _fecha_corta(inicio)


def servicio_item_ui(servicio: dict) -> dict:
    """Forma chica que consume serviceItemHtml() del prototipo: {id, icon, title, detail, source, tag}."""
    detalle = servicio.get("subtitulo") or ""
    fecha = resumen_temporal(servicio)
    if fecha:
        detalle = f"{detalle} · {fecha}" if detalle else fecha
    tag = None
    grupo = servicio.get("grupo") or {}
    if grupo.get("etiqueta"):
        tag = grupo["etiqueta"]
    elif servicio.get("estado") == "no_incluido":
        tag = "No incluido"
    return {
        "id": servicio["id"],
        "icon": icono_de(servicio.get("tipo")),
        "title": servicio.get("titulo") or "Servicio",
        "detail": detalle,
        "source": "ia" if servicio.get("origenDatos", "ia").startswith("ia") else "manual",
        "tag": tag,
        "sitioWeb": (servicio.get("proveedor") or {}).get("sitioWeb"),
        "requiereRevision": bool((servicio.get("extraccion") or {}).get("requiereRevision")),
    }
