# Fixtures de parseo — test de regresión

Un JSON por documento de `DocumentosEjemplo/`, con la salida **correcta** que
`PROMPT-PARSEO-v1.md` debería producir para ese archivo. No son ejemplos de
referencia sueltos: son el test de regresión para cuando cambies el prompt — si
una versión nueva del prompt deja de reproducir estos resultados en los campos
que importan, es una regresión, no una mejora.

Cada archivo trae un campo `_comentario_fixture` al tope explicando qué caso
difícil de `PROMPT-PARSEO-v1.md` ejercita. **Ese campo no forma parte del
contrato real**: es documentación para quien mantiene el fixture. Al comparar
contra una salida real de la IA (que nunca va a incluirlo), quitalo antes de
diffear o validar — así lo hace el snippet de validación de abajo.

## Cómo comparar una salida nueva contra un fixture

1. **Validar contra el schema primero** (`../esquema-servicio.schema.json`).
   Si la salida nueva no valida, no hace falta ni comparar contra el fixture:
   ya está mal.
2. **Ignorar al comparar**: `_comentario_fixture` (no existe en salidas reales),
   `extraccion.confianza` (número, no exacto), `extraccion.fragmentoFuente`
   (paráfrasis aceptable mientras cite el fragmento correcto), y `claveLocal`
   (el valor exacto no importa, solo que las referencias internas —
   `complementoDe`, `grupo.clave` — sean consistentes entre sí).
3. **Comparar exacto**: `tipo`, `estado`, `temporal.modo`,
   `temporal.*.fechaHoraLocal`, `temporal.*.precision`, `esComplemento`,
   `complementoDe` (en relación, no en valor literal), y las claves presentes
   en `datos` (no necesariamente el string exacto de cada valor, pero sí que la
   IA haya encontrado/omitido los mismos campos).
4. **El de `paquete-tortuguero.json` es el más importante para correr primero**:
   si una versión nueva del prompt deja de separar los 5 servicios, o deja de
   marcar `svc-4`/`svc-5` como `esComplemento` de `svc-3`, es la señal más clara
   de que la regla de granularidad (sección 1 del prompt) se rompió.

## Snippet de validación (Python)

```python
import json, jsonschema, glob

schema = json.load(open("../esquema-servicio.schema.json"))
validator = jsonschema.Draft202012Validator(schema)

for path in sorted(glob.glob("*.json")):
    if path.endswith("README.md"):
        continue
    data = json.load(open(path))
    data.pop("_comentario_fixture", None)
    errors = list(validator.iter_errors(data))
    print(path, "OK" if not errors else f"{len(errors)} error(es)")
    for e in errors:
        print(" ", list(e.path), e.message)
```

## Cobertura real vs. cobertura del schema — sé honesto con esto

Al validar los 6 fixtures (comando de arriba) y recorrer los enums usados, la
cobertura real es:

| Campo | Valores que SÍ aparecen en los 6 fixtures | Valores definidos que NO aparecen |
|---|---|---|
| `temporal.modo` | `instante`, `rango`, `dia_completo` | `transversal`, `sin_fecha` |
| `*.precision` | `minuto`, `dia`, `aproximada` | `ambigua` |
| `estado` | `confirmado`, `no_incluido` | `pendiente`, `cancelado` |
| `esComplemento:true` | sí (`paquete-tortuguero.json`, 2 casos) | — |
| `viajeroId:null` con `pax.total>1` | sí (10 servicios) | — |

**Por qué faltan `transversal`, `sin_fecha` y `ambigua`, y por qué eso no es un
error**: ninguno de los 6 documentos de `DocumentosEjemplo/` es una póliza de
seguro de viaje (que es el caso de uso pensado para `transversal`), ninguno
carece completamente de fecha para algún servicio (`sin_fecha`), y —de forma
más interesante— **toda fecha problemática de los 6 documentos se resolvió**
aplicando las reglas del prompt (verificación por día de la semana en el
e-ticket, convención por idioma en el voucher de hotel, formato `MM/DD`
inequívoco en Universal, o inferencia marcada `aproximada` en Tortuguero). Eso
es, si acaso, una demostración más fuerte de que las reglas funcionan que forzar
un fixture artificial "no se pudo resolver" — fabricar ese caso solo para
completar el enum falsearía lo que el documento realmente dice.

Quedan como **gaps conocidos**, no corregidos acá: cuando aparezca un documento
real (una póliza de seguro, o un voucher con una fecha genuinamente
irresoluble ni con contexto), agregalo como séptimo fixture y listalo en esta
tabla. Mismo comentario para `estado: 'pendiente'` y `estado: 'cancelado'`: son
estados de negocio (una reserva aún no confirmada, o cancelada después de
cargada) que ningún voucher de ejemplo dispara — se ejercen recién cuando el
agenciero edita el estado a mano o cuando un documento de cancelación real entre
al set de prueba.
