"""
Llama a Gemini (Interactions API) para parsear un documento de viaje contra el
contrato ya definido en ../parseo/ (prompt v3 + JSON Schema de la salida), y mide
tokens/costo/latencia reales de la llamada -- esa medición es el resultado que
busca esta POC (ver analisis-costos-pricing-validacion-peregrí.md).

No usa esquema-servicio.gemini.schema.json (el dialecto `nullable:true` de la
API vieja de generateContent) sino esquema-servicio.schema.json (JSON Schema
estándar draft 2020-12), porque la Interactions API actual soporta JSON Schema
posta -- incluidos `type:["string","null"]` y `anyOf`. Como no está confirmado
que soporte `$ref`/`$defs` con nombre (sólo se documenta la auto-referencia
`"$ref":"#"`), acá los resolvemos a mano antes de mandar el schema, así no
dependemos de qué tan completo sea el soporte del lado de la API.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from google import genai

RAIZ = Path(__file__).resolve().parent.parent  # .../agencia
PARSEO_DIR = RAIZ / "parseo"

PROMPT_VERSION = "v3"
PROMPT_BASE = (PARSEO_DIR / f"PROMPT-PARSEO-{PROMPT_VERSION}.md").read_text(encoding="utf-8")

# Precios oficiales por 1M tokens (USD), verificados contra ai.google.dev/gemini-api/docs/pricing
# al momento de esta POC. Overrideables por .env (GEMINI_PRECIO_IN/OUT) para probar
# otro modelo sin tocar código. Nota: "gemini-2.5-flash"/"gemini-2.5-flash-lite" ya no
# están disponibles para API keys nuevas (la API redirige a la familia 3.x).
PRECIOS_USD_POR_MILLON = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.6-flash": (0.75, 3.75),
}
PRECIO_DEFAULT = (0.25, 1.50)


class ErrorParseo(Exception):
    """Cualquier falla al parsear: sin API key, error de red/API, o salida no-JSON.
    Se atrapa siempre en el endpoint -- nunca debe llegar como 500 crudo al agenciero."""


def _resolver_schema() -> dict:
    data = json.loads((PARSEO_DIR / "esquema-servicio.schema.json").read_text(encoding="utf-8"))
    defs = data.get("$defs", {})

    def resolver(nodo):
        if isinstance(nodo, dict):
            ref = nodo.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolver(defs[ref.split("/")[-1]])
            return {k: resolver(v) for k, v in nodo.items() if k not in ("$schema", "$id", "$defs")}
        if isinstance(nodo, list):
            return [resolver(x) for x in nodo]
        return nodo

    return resolver(data)


SCHEMA = _resolver_schema()


def _bloque_contexto(viaje: dict | None, viajeros: list[dict], servicios_confirmados: list[dict]) -> str:
    """Arma {{CONTEXTO_VIAJE}} según PROMPT-PARSEO-v1.md §8 / MODELO-DATOS.md.
    Si no hay viaje (documento suelto) devuelve "" y no se inyecta nada."""
    if not viaje:
        return ""
    lineas = ["{{CONTEXTO_VIAJE}}"]
    salida, vuelta = viaje.get("salida"), viaje.get("vuelta")
    if salida or vuelta:
        lineas.append(f"Viaje: {viaje.get('nombre')} · Salida {salida or '?'} → Vuelta {vuelta or '?'}")
    else:
        # Degradado parcial (MODELO-DATOS.md): sin fechas, se omite la línea de fechas
        # en vez de mandar null literal.
        lineas.append(f"Viaje: {viaje.get('nombre')}")
    destinos = [{"ciudad": d.get("ciudad"), "pais": d.get("pais")} for d in viaje.get("destinos", [])]
    lineas.append("Destinos: " + json.dumps(destinos, ensure_ascii=False))
    viajeros_ctx = [{"id": v["id"], "nombreCompleto": v["name"]} for v in viajeros]
    lineas.append("Viajeros cargados: " + json.dumps(viajeros_ctx, ensure_ascii=False))
    servicios_ctx = [
        {
            "tipo": s.get("tipo"),
            "titulo": s.get("titulo"),
            "fechaInicio": (s.get("temporal") or {}).get("inicio", {}).get("fechaHoraLocal"),
        }
        for s in servicios_confirmados
    ]
    lineas.append("Servicios ya cargados en este viaje: " + json.dumps(servicios_ctx, ensure_ascii=False))
    return "\n".join(lineas)


def _precio(modelo: str) -> tuple[float, float]:
    override_in = os.environ.get("GEMINI_PRECIO_IN") or None
    override_out = os.environ.get("GEMINI_PRECIO_OUT") or None
    base_in, base_out = PRECIOS_USD_POR_MILLON.get(modelo, PRECIO_DEFAULT)
    return (float(override_in) if override_in else base_in, float(override_out) if override_out else base_out)


def parsear_documento(
    contenido: bytes,
    mime_type: str,
    viaje: dict | None = None,
    viajeros: list[dict] | None = None,
    servicios_confirmados: list[dict] | None = None,
) -> dict:
    """Devuelve el JSON completo del schema (`documento` + `servicios`) más un bloque
    `medicion` con tokens/costo/latencia. Lanza ErrorParseo ante cualquier falla."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ErrorParseo(
            "Falta GEMINI_API_KEY. Copiá poc/.env.example a poc/.env y completá tu clave "
            "(se consigue gratis en https://aistudio.google.com/apikey)."
        )

    modelo = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    contexto = _bloque_contexto(viaje, viajeros or [], servicios_confirmados or [])
    prompt = PROMPT_BASE + (f"\n\n{contexto}" if contexto else "")
    parte_tipo = "image" if mime_type.startswith("image/") else "document"

    entrada = [
        {"type": parte_tipo, "data": base64.b64encode(contenido).decode("ascii"), "mime_type": mime_type},
        {"type": "text", "text": prompt},
    ]

    client = genai.Client(api_key=api_key)
    inicio = time.monotonic()
    try:
        interaction = client.interactions.create(
            model=modelo,
            input=entrada,
            response_format={"type": "text", "mime_type": "application/json", "schema": SCHEMA},
            # Sin este límite explícito, medimos llamadas de ~160s que además truncaban el
            # JSON a mitad de camino -- 12000 cubre con margen el caso más grande visto
            # (paquete-tortuguero.pdf, 5 servicios) sin dejar la generación sin techo.
            generation_config={"max_output_tokens": 12000},
        )
    except Exception as exc:  # noqa: BLE001 -- POC: cualquier falla de red/API se muestra al agenciero, no rompe el request
        raise ErrorParseo(f"Gemini no pudo procesar el documento: {exc}") from exc
    segundos = round(time.monotonic() - inicio, 2)

    if interaction.status != "completed":
        raise ErrorParseo(f"Gemini no completó la respuesta (status={interaction.status}) -- probablemente el documento necesita más tokens de los reservados.")

    try:
        salida = json.loads(interaction.output_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ErrorParseo(f"La respuesta de Gemini no fue JSON válido: {exc}") from exc

    # El precio publicado de "salida" incluye los tokens de thinking (algunos modelos
    # de la familia 3.x razonan por default y eso no aparece en total_output_tokens) --
    # sin sumarlos acá el costo medido queda subestimado para esos modelos.
    uso = interaction.usage
    tok_in = getattr(uso, "total_input_tokens", 0) or 0
    tok_out = (
        (getattr(uso, "total_output_tokens", 0) or 0)
        + (getattr(uso, "total_thought_tokens", 0) or 0)
        + (getattr(uso, "total_tool_use_tokens", 0) or 0)
    )
    precio_in, precio_out = _precio(modelo)
    costo_usd = round((tok_in * precio_in + tok_out * precio_out) / 1_000_000, 6)

    salida["medicion"] = {
        "modelo": modelo,
        "tokensEntrada": tok_in,
        "tokensSalida": tok_out,
        "costoUsd": costo_usd,
        "segundos": segundos,
    }
    return salida
