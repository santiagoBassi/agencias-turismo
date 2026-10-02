# Modelo de datos — parseo de documentos → itinerario

> Complementa `PROMPT-PARSEO-v2.md` (qué le pedimos a la IA) y
> `esquema-servicio.schema.json` (la forma exacta que valida esa salida). Este
> documento describe **dónde vive** ese JSON una vez parseado: las colecciones de
> la base no relacional y cómo el front deriva lo que muestra a partir de ellas.
>
> **Dos variantes del schema, mismo contrato:** `esquema-servicio.schema.json`
> es JSON Schema 2020-12 estándar (con `$ref`/`$defs` y uniones `["string","null"]`)
> — es el que valida `fixtures/` y el que usarías con una API que soporte JSON
> Schema completo (ej. tool use de Claude). `esquema-servicio.gemini.schema.json`
> es la misma forma pero aplanada y reescrita con `"nullable": true` en vez de
> uniones de tipo y sin `$ref` (los tipos van en minúscula, `"string"`/`"object"`/
> `"array"`, no el enum `Type` en mayúsculas de la API nativa de Gemini — se
> mantiene JSON Schema estándar para poder reusar el mismo validador). Si cambia
> uno, hay que replicar el cambio en el otro a mano — no hay generación
> automática entre ambos todavía.

## Las seis colecciones

El parseo no es la primera cosa que pasa en la vida de un viaje — es la última
antes del itinerario. Antes tiene que existir el tenant, el operador que sube el
documento, el viajero al que pertenece, y el viaje que le da contexto. Sin esas
cuatro colecciones, `documentos_fuente.agenciaId`, `.viajeId`, `.subidoPor` y
`servicios.viajeros[].viajeroId` son claves foráneas que apuntan al vacío — y el
bloque `{{CONTEXTO_VIAJE}}` que `PROMPT-PARSEO-v1.md` (§8) y
`PROMPT-PARSEO-v2.md` (regla 10) esperan para desambiguar fechas y matchear
viajeros no tiene de dónde salir.

| Colección | Qué guarda | Depende de |
|---|---|---|
| `agencias` | El tenant: cada cliente de Peregrí, con su branding white-label. | — |
| `usuarios` | El agenciero (operador humano) que usa el panel. | `agencias` |
| `viajeros` | El cliente final de la agencia (el turista), reutilizable entre viajes. | `agencias` |
| `viajes` | El contenedor con título, destinos, fechas y pasajeros asignados. | `agencias`, `viajeros` |
| `documentos_fuente` | Un registro por archivo subido, con el estado del pipeline de parseo. | `agencias`, `viajes`, `usuarios` |
| `servicios` | Un registro por servicio extraído (o cargado a mano). | `agencias`, `viajes`, `documentos_fuente`, `viajeros` |

Las primeras cuatro se detallan a continuación, en orden de dependencia.
`documentos_fuente` y `servicios` ya estaban documentadas; sus secciones quedan
como estaban, solo se agregan las colecciones a las que ahora sí pueden
referenciar.

## `agencias` — el tenant

```js
{
  _id: ObjectId,
  nombre: 'Hybris Turismo',
  slug: 'hybristurismo',           // = agencySlug() en prototipo-panel-agencia.html:966
  emailContacto: 'hola@hybristurismo.com',
  branding: {
    logo: '✈',                     // emoji/ícono fallback
    logoUrl: null,                 // URL si subieron un logo real
    colorPrimario: '#0e7490',
  },
  plan: 'trial' | 'activo' | 'suspendido',
  activa: true,
  creadaEn: ISODate,
}
```

**Índices sugeridos:** `{ slug: 1 }` único.

Es la raíz del aislamiento multi-tenant: **toda** query sobre `usuarios`,
`viajeros`, `viajes`, `documentos_fuente` y `servicios` filtra por `agenciaId`.
Dejarlo escrito acá evita que sea una convención implícita que alguien rompe al
agregar un endpoint nuevo. `branding` es exactamente `state.agency` en
`prototipo-panel-agencia.html:776`, lo que hoy alimenta `applyBrand()` (`:957`).

## `usuarios` — el agenciero

```js
{
  _id: ObjectId,
  agenciaId: ObjectId,
  nombreCompleto: string,
  email: string,
  rol: 'owner' | 'agenciero' | 'lectura',
  activo: true,
  creadoEn: ISODate,
  ultimoAccesoEn: ISODate | null,
}
```

**Índices sugeridos:** `{ email: 1 }` único (login es global, no por agencia);
`{ agenciaId: 1 }`.

Es el destino de `documentos_fuente.subidoPor` y de `servicios.revision.revisadoPor`.
**No** se documenta acá ningún campo de credenciales (`passwordHash` o similar):
el mecanismo de auth todavía no está decidido, y es mejor dejar el campo afuera
que sugerir uno a mano que probablemente haya que rehacer.

## `viajeros` — el cliente final de la agencia

```js
{
  _id: ObjectId,
  agenciaId: ObjectId,
  nombreCompleto: string,
  dni: string,                     // identificador principal del viajero — requerido al dar de alta
  email: string | null,            // el prototipo admite '—' cuando no hay dato
  telefono: string | null,
  documento: {                     // documento de VIAJE (pasaporte/otro) — distinto del `dni` identificador,
    tipo: 'pasaporte' | 'dni' | 'otro',   // puede coincidir en valor pero cubre casos como pasaporte extranjero
    numero: string,
    paisEmision: string,
    vencimiento: ISODate,
  } | null,
  acceso: {
    magicLinkEnviadoEn: ISODate | null,   // = accessSent en el prototipo
    ultimoAccesoEn: ISODate | null,
  },
  creadoPor: ObjectId,              // usuarios._id
  creadoEn: ISODate,
  actualizadoEn: ISODate,
}
```

**Índices sugeridos:**
- `{ agenciaId: 1, dni: 1 }` **único** — es el identificador real de la persona
  (a diferencia de email/teléfono, que pueden faltar o compartirse entre
  integrantes de un mismo grupo familiar). Alta de viajero (`createTraveler()`
  y los altas rápidas embebidas en `createTrip()`/`addTravelersToTrip()`,
  `prototipo-panel-agencia.html`) lo pide siempre — es el único campo, junto al
  nombre, que bloquea la creación si falta.
- `{ agenciaId: 1, email: 1 }` único **parcial** (solo cuando `email` no es
  `null`/`'—'`) — el prototipo ya admite viajeros sin email, así que un único a
  secas rechazaría el segundo viajero sin email.
- `{ agenciaId: 1, nombreCompleto: 1 }` — buscador de `renderTravelers()`.

Un viajero es **reutilizable entre viajes**: vive a nivel agencia, no dentro de
un viaje puntual. Es lo que permite que `servicios.viajeros[].viajeroId` sea un
match estable entre documentos distintos de la misma persona, y que el conteo
"N viajes" que muestra `renderTravelers()` sea una query (`viajes` filtrado por
`pasajeros.viajeroId`) y no un scan en memoria.

## `viajes` — el contenedor que faltaba

```js
{
  _id: ObjectId,
  agenciaId: ObjectId,
  titulo: 'Crucero por el Mediterráneo',   // requerido, no vacío
  tipo: 'ciudad' | 'multi' | 'crucero' | 'roadtrip' | 'playa'
      | 'aventura' | 'negocios' | 'otro',  // = TRIP_TYPES, prototipo-panel-agencia.html:887
  destinos: [
    // `codigoPais` (ISO-3166 alpha-2) es lo que permite resolver moneda/tipo de
    // cambio contra `catalogo_paises` — `pais` es texto libre en español y no
    // alcanza como clave. Ver § Catálogos de plataforma más abajo.
    { ciudad: string, pais: string | null, codigoPais: string | null, flag: string | null },
  ],
  fechas: {
    salida: 'YYYY-MM-DD' | null,
    vuelta: 'YYYY-MM-DD' | null,
    noches: number | null,          // derivado de salida/vuelta al crear
  },
  pasajeros: [
    {
      viajeroId: ObjectId,
      nombreCompleto: string,       // snapshot de conveniencia, no fuente de verdad
      rol: 'titular' | 'acompanante',
      agregadoEn: ISODate,
    },
  ],
  estado: 'borrador' | 'en_armado' | 'listo' | 'en_curso'
        | 'finalizado' | 'cancelado',
  creadoPor: ObjectId,              // usuarios._id
  creadoEn: ISODate,
  actualizadoEn: ISODate,
}
```

**Índices sugeridos:**
- `{ agenciaId: 1, estado: 1, 'fechas.salida': 1 }` — el dashboard de
  `renderDashboard()` (`prototipo-panel-agencia.html:999`).
- `{ agenciaId: 1, 'pasajeros.viajeroId': 1 }` — **multikey**; resuelve "todos
  los viajes de un viajero" sin necesitar una colección puente.

**Decisiones de diseño:**
- **Pasajeros embebidos, no colección puente.** Un viaje tiene pocos pasajeros
  y el 100% de las lecturas los necesita junto al viaje (header del viaje,
  dashboard, armado de `{{CONTEXTO_VIAJE}}`) — embebido evita un join en cada
  render. La única query que favorecería una colección puente ("viajes de un
  viajero") ya la resuelve el índice multikey de arriba.
- **`titulo` requerido**, con el mismo fallback que ya usa el prototipo:
  `createTrip()` (`:1314`) cae al nombre del primer destino si el campo viene
  vacío. Así el título nunca es nulo aunque el agenciero no lo tipee a mano.
- **`nombreCompleto` en `pasajeros[]` es un snapshot**, no la fuente de verdad
  — esa es `viajeros.nombreCompleto`. Al editar un viajero, un update multi
  refresca el snapshot en sus viajes no finalizados; si por lo que sea queda
  desactualizado, se ve un nombre viejo, nunca se rompe el vínculo (lo que
  importa para matching y queries es `viajeroId`).
- **`progreso` no se persiste.** Es derivado, lo calcula `computeProgress()`
  (`:870`) a partir de los `servicios` del viaje en el momento de leer.
  Persistirlo obligaría a recalcularlo en cada escritura de `servicios` y se
  desincroniza tarde o temprano.
- **`fechas` puede estar incompleta** (`salida`/`vuelta` en `null`) sin que eso
  bloquee crear el viaje — pero degrada el `{{CONTEXTO_VIAJE}}` que se le pasa
  al parseo (ver más abajo).

## Precondiciones antes de parsear

El orden en el que un viaje se vuelve apto para recibir documentos:

1. Existe un `viaje` con `titulo` no vacío.
2. El viaje tiene **al menos un pasajero**, y exactamente uno con
   `rol: 'titular'`.
3. `estado` pasa de `borrador` a `en_armado` cuando se cumplen 1 y 2 — es la
   transición que **habilita** subir documentos a ese viaje.
4. Solo entonces se acepta un `documentos_fuente` con ese `viajeId`.

Esto formaliza algo que el modelo ya insinuaba sin exigirlo:
`documentos_fuente.viajeId` está comentado como "contexto para el parseo", pero
nada impedía que apuntara a un viaje vacío — con lo cual el parseo pierde
justamente el contexto por el que ese campo existe. La validación va del lado
del servidor al crear el `documentos_fuente`, no solo como guardrail de UI.

**Caso explícito: el documento que llega antes que el viaje.** El agenciero
recibe el PDF por WhatsApp/mail y todavía no armó nada en el panel. El prompt
ya define ese modo degradado (`PROMPT-PARSEO-v1.md:208`, "documento suelto, sin
viaje asociado"). Regla del modelo: se permite, se parsea con `viajeId: null`,
y **todo servicio resultante nace con `extraccion.requiereRevision: true`** —
porque ninguna fecha ambigua ni ningún `viajeroId` pudo verificarse contra un
contexto que no existía. Al asociar después el documento a un viaje real, esos
servicios se re-evalúan.

## Cómo se arma `{{CONTEXTO_VIAJE}}`

Mapeo campo por campo del bloque que definen `PROMPT-PARSEO-v1.md:189-195`
(§8) y la regla 10 de `PROMPT-PARSEO-v2.md:81`, para que quede claro que ahora
es derivable de la base sin inventar nada:

| Línea del bloque | Origen |
|---|---|
| `Viaje: {nombre} · Salida … → Vuelta …` | `viajes.titulo`, `viajes.fechas.salida`, `viajes.fechas.vuelta` |
| `Destinos: [{ciudad, pais}, ...]` | `viajes.destinos[]` |
| `Viajeros cargados: [{id, nombreCompleto}, ...]` | `viajes.pasajeros[]` — `viajeroId` + `nombreCompleto`, en una sola lectura |
| `Servicios ya cargados: [{tipo, titulo, fechaInicio}, ...]` | `servicios` del mismo `viajeId`, proyectando `{ tipo, titulo, 'temporal.inicio.fechaHoraLocal' }`, con `estado != 'cancelado'` |

La tercera fila es el argumento más fuerte a favor de embeber `pasajeros[]` en
`viajes`: sale del mismo documento que las dos primeras, en la misma lectura.
Con una colección puente, armar este bloque en cada subida costaría un lookup
extra.

**Degradado parcial:** si `fechas.salida`/`vuelta` son `null`, esa línea se
omite del bloque en vez de mandar un `null` literal — la regla 10 de
`PROMPT-PARSEO-v2.md` dice "si te lo paso", y un `null` escrito es peor pista
para el modelo que la ausencia de la línea.

## Nomenclatura: "pasajero" vs. "viajero"

Tres arrays con nombres parecidos que conviene no confundir:

- **`viajeros`** (colección): la persona como entidad de la agencia,
  reutilizable entre viajes.
- **`viajes.pasajeros[]`**: la asignación de esa persona a *este* viaje
  puntual, con su rol (`titular`/`acompanante`).
- **`servicios.viajeros[]`**: los nombres **tal como los imprime el
  documento** (`nombreEnDocumento`), que la IA intenta matchear contra
  `viajes.pasajeros[]` para completar `viajeroId` + `confianzaMatch`.

El tercero es salida del parseo y puede no matchear ninguno de los dos
primeros — por ejemplo, un acompañante que figura en el voucher pero que el
agenciero nunca cargó como pasajero. Eso **no es un error del parseo**: es
exactamente el caso que dispara `requiereRevision`.

## Por qué `documentos_fuente` y `servicios` van separadas

Un documento subido (PDF o imagen) casi nunca es "un servicio": el voucher de
Tortuguero trae 5, el e-ticket trae 2 (ida y vuelta), los traslados+excursión
traen 3. Modelarlo 1 documento → 1 registro obligaría a mezclar "metadata del
archivo" con "datos del servicio N veces", o a guardar arrays anidados que se
vuelven difíciles de indexar, editar y mostrar por separado.

Se usan dos colecciones:

- **`documentos_fuente`**: un registro por archivo subido. Guarda metadata del
  archivo, el estado del pipeline de parseo, y la lista de servicios que generó.
- **`servicios`**: un registro por servicio extraído (o cargado a mano). Cada uno
  referencia al documento fuente que lo originó (o `null` si es carga manual).

Es el mismo patrón "documento padre + N documentos hijos con referencia" que ya
usás implícitamente en los prototipos (`trip.docs` vs `trip.services.*`), solo
que acá el vínculo es explícito y vive en la base, no en la posición dentro de un
array en memoria.

## Colección `documentos_fuente`

```js
{
  _id: ObjectId,
  agenciaId: ObjectId,          // multi-tenant: todo documento pertenece a una agencia
  viajeId: ObjectId,            // a qué viaje se subió (contexto para el parseo)
  subidoPor: ObjectId,          // usuario agenciero
  subidoEn: ISODate,

  archivo: {
    nombreOriginal: 'E-TKT Giemenez Nelida Raquel.pdf',
    storageKey: 's3://.../agencia123/viaje456/....pdf',   // o el path que uses
    mimeType: 'application/pdf' | 'image/jpeg' | 'image/png',
    tamanoBytes: 24151,
    sha256: '...',              // dedupe: mismo archivo no se re-parsea dos veces
    paginas: 2 | null,          // null para imágenes
  },

  parseo: {
    estado: 'pendiente' | 'procesando' | 'parseado' | 'revision' | 'error',
    modelo: 'claude-sonnet-5',
    promptVersion: 'v1',
    schemaVersion: '1.0.0',
    intentos: 1,
    procesadoEn: ISODate | null,
    tokensEntrada: 4200 | null,
    tokensSalida: 1100 | null,
    errorMsg: string | null,
  },

  idiomaDetectado: 'es' | 'en' | null,
  tipoDocumentoDetectado: 'e_ticket' | 'voucher_hotel' | 'voucher_traslado'
                        | 'voucher_excursion' | 'voucher_paquete' | 'entrada'
                        | 'poliza_seguro' | 'boarding_pass' | 'otro',
  confianzaGlobal: 0.0-1.0,

  serviciosGenerados: [ObjectId, ObjectId, ...],  // referencia a `servicios`
}
```

**Índices sugeridos:**
- `{ agenciaId: 1, viajeId: 1 }` — listar documentos de un viaje.
- `{ agenciaId: 1, 'archivo.sha256': 1 }` único parcial — evita re-parsear un
  archivo ya subido (los agencieros resuben el mismo PDF seguido).
- `{ 'parseo.estado': 1 }` — cola de trabajo para el worker de parseo.

**Estados del pipeline** (`parseo.estado`):
1. `pendiente` → recién subido, en cola.
2. `procesando` → llamada a la IA en curso.
3. `parseado` → salida válida contra el schema, sin banderas de revisión en
   ninguno de sus servicios.
4. `revision` → parseó, pero al menos un servicio tiene
   `extraccion.requiereRevision:true` — el agenciero tiene que confirmar antes de
   que impacte el itinerario del viajero (ver `PROMPT-PARSEO-v1.md` regla 8, el
   mismo patrón *human-in-the-loop* que ya está en `CONTEXTO-PROYECTO.md`).
5. `error` → no se pudo parsear (archivo ilegible, timeout, salida inválida tras
   el reintento). `errorMsg` para mostrarle algo útil al agenciero.

## Colección `servicios`

Es el corazón del modelo. Un documento por servicio, con cinco bloques de
responsabilidad separada — así el motor de itinerario, el front y el humano que
revisa cada uno leen solo la parte que les importa.

```js
{
  _id: ObjectId,
  agenciaId: ObjectId,
  viajeId: ObjectId,
  documentoFuenteId: ObjectId | null,   // null si origenDatos === 'manual'
  origenDatos: 'ia' | 'ia_editado' | 'manual',
  creadoEn: ISODate,
  actualizadoEn: ISODate,

  // ═══ A. NÚCLEO NORMALIZADO — lo único que el motor de itinerario necesita ═══
  tipo: 'vuelo' | 'tren' | 'bus' | 'ferry' | 'crucero' | 'traslado'
      | 'alquiler_auto' | 'hotel' | 'excursion' | 'entrada' | 'circuito'
      | 'paquete' | 'seguro' | 'otro',
  subtipo: string | null,               // ej. 'pase_multidia', 'entrada_parque'
  titulo: string,                       // "AM 0029 — EZE → MEX"
  subtitulo: string | null,             // "Aeroméxico · Economy · 9h 40m"
  estado: 'confirmado' | 'pendiente' | 'no_incluido' | 'cancelado',

  temporal: {
    modo: 'instante' | 'rango' | 'dia_completo' | 'transversal' | 'sin_fecha',
    inicio: {
      fechaHoraLocal: '2025-10-08T23:25',   // YYYY-MM-DDTHH:mm, siempre local naive
      zonaHoraria: 'America/Mexico_City' | null,
      precision: 'minuto' | 'dia' | 'aproximada' | 'ambigua',
    } | null,
    fin: { /* misma forma */ } | null,
  },

  ubicacion: {
    // Nota: las claves reales son exactamente estas — sin `coords`. `$defs.lugar`
    // en esquema-servicio.schema.json tiene additionalProperties:false y no lo declara.
    inicio: { nombre, direccion, ciudad, pais, codigo: 'EZE' | null } | null,
    fin: { /* misma forma */ } | null,
  },

  grupo: { clave: 'ida' | 'vuelta' | string, etiqueta: 'Ida', orden: 1 } | null,
  esComplemento: false,
  complementoDe: 'clave-local-del-servicio-padre' | null,

  proveedor: {
    nombre: string | null,
    telefono: string | null,
    telefonoEmergencia: string | null,
    email: string | null,
    contacto: string | null,
    direccion: string | null,
    // Solo si está IMPRESO en el documento (ej. la web de la agencia emisora del
    // voucher). Nunca la web pública conocida de una aerolínea o aseguradora —
    // eso es conocimiento del mundo, prohibido por la regla anti-alucinación
    // (PROMPT-PARSEO-v1.md §3 / v2 regla 3). Ese enriquecimiento vive en los
    // catálogos de plataforma — ver § Catálogos de plataforma más abajo.
    sitioWeb: string | null,
  },

  referencias: [
    { etiqueta: 'Código de reserva', valor: 'LQRKKZ', tipo: 'pnr' | 'voucher' | 'booking' | 'poliza' | 'confirmacion' | 'otro' },
  ],

  viajeros: [
    {
      nombreEnDocumento: 'GIMENEZ/NELIDA RAQUEL',
      nombreNormalizado: 'Nélida Raquel Giménez',
      rol: 'titular' | 'acompanante',
      viajeroId: ObjectId | null,       // match contra la colección de viajeros
      confianzaMatch: 0.95 | null,
    },
  ],
  pax: { adultos: 4, menores: 0, infantes: 0, total: 4 },

  // ═══ B. DATOS TIPADOS — nullable, la forma exacta depende de `tipo` (ver abajo) ═══
  datos: { /* ... */ },

  // ═══ C. LO QUE LA IA NO PUDO ENCUADRAR EN EL SCHEMA ═══
  camposExtra: [ { etiqueta: 'Emisión estimada', valor: '349.73 kg CO2' } ],
  notas: [ 'Reconfirmar 24 horas antes con el operador' ],   // accionable → se muestra
  letraChica: string | null,                                 // T&C legal → no se muestra

  // ═══ D. TRAZABILIDAD Y REVISIÓN ═══
  extraccion: {
    confianza: 0.0-1.0,
    requiereRevision: boolean,
    motivoRevision: string | null,
    camposInciertos: ['temporal.inicio'],   // paths dentro de este mismo documento
    paginasFuente: [1],
    fragmentoFuente: 'Traslado el día 09/10/2025 ... a las 07:30 am.',
  },
  revision: {
    revisadoPor: ObjectId,
    revisadoEn: ISODate,
    camposEditados: ['temporal.inicio'],
  } | null,

  // ═══ E. DERIVADO POR CÓDIGO AL LEER — NUNCA ESCRITO POR LA IA ═══
  camposMostrar: [
    { clave: 'aerolinea', etiqueta: 'Aerolínea', valor: 'Aeroméxico', destacado: false, ambito: 'ambos' },
  ],
  icono: '✈',
}
```

### Por qué `datos` (tipado) *y además* `camposExtra` (libre)

Si todo fuera key-value libre, dos parseos del mismo tipo de documento podrían
etiquetar lo mismo distinto ("Aerolínea" vs "Compañía aérea"), rompiendo la
consistencia que es el objetivo de este trabajo. Si todo fuera un schema rígido,
perderíamos datos reales de documentos raros (la emisión de CO2 del e-ticket, el
teléfono de "Contacto de Servicio al Cliente" de Tortuguero) o cada tipo de
documento nuevo exigiría tocar el schema antes de poder cargarlo.

La solución híbrida:
- **`datos`** cubre los campos que el **front necesita para lógica**, no solo para
  mostrar: fechas para el timeline, IATA para íconos de ruta, régimen del hotel
  para filtrar. Estructurado, con claves fijas por `tipo`.
- **`camposExtra`** es la válvula de escape: cualquier dato concreto que el
  documento declare y no entre en `datos`, ya con `{etiqueta, valor}` en español
  listo para pintar tal cual.
- **`camposMostrar`** (bloque E) es lo único que el front realmente `.map()`ea
  para las pantallas de detalle — se arma en el backend/frontend a partir de
  `datos` + `camposExtra`, **nunca lo escribe la IA**. Esto es lo que garantiza
  consistencia: por más que el modelo varíe una extracción de sinónimos, las
  etiquetas que ve el viajero siempre salen del mismo registry.

### Bloques `datos` por tipo (todos los campos nullable)

| tipo | campos de `datos` |
|---|---|
| `vuelo` | `aerolinea, codigoAerolinea, numeroVuelo, cabina, origen, destino` (ambos `$defs.lugar`: `{nombre, direccion, ciudad, pais, codigo}` — el IATA va en `codigo`, no hay clave `iata` ni `terminal` propia), `duracion, aeronave, escalas[], asientos[], equipajeBodega, equipajeCabina, numeroETicket, estadoVuelo` |
| `hotel` | `nombreHotel, categoria, direccion, zona, noches, habitaciones[{descripcion, regimen, ocupantes[]}], horaCheckIn, horaCheckOut, telefonoHotel, localizadorExterno` |
| `traslado` | `modalidad('privado'\|'regular'\|'compartido'), desde, hasta, vueloReferencia{numero, hora, aeropuerto}, puntoEncuentro[], esperaMaxima, direccionServicio('llegada'\|'salida'\|'interno')` |
| `excursion` / `circuito` | `nombre, duracion, idiomaGuia, lugarRecogida, horaRecogida, incluye[], noIncluye[], ciudadesVisitadas[]` |
| `entrada` | `atraccion, tipoPase, validezDesde, validezHasta, diasDeUso, numeroConfirmacion, codigoBarras, restricciones[]` |
| `alquiler_auto` | `categoriaVehiculo, transmision, lugarRetiro, horaRetiro, lugarDevolucion, horaDevolucion, coberturas[], kilometraje` |
| `paquete` | `nombre, duracion, incluye[], noIncluye[], serviciosComponentes[]` |
| `seguro` | `aseguradora, numeroPoliza, plan, vigenciaDesde, vigenciaHasta, coberturas[{concepto,monto}], telefonoSOS, territorio` |
| `tren`/`bus`/`ferry`/`crucero` | igual forma que `vuelo` sin `aeronave`/`asientos` |
| `otro` | ninguno — solo núcleo + `camposExtra` |

Ver la forma exacta y los tipos de cada campo en `esquema-servicio.schema.json`
(sección `$defs.datosPorTipo`).

## Registry `camposMostrar` (vive en código, no en la IA)

Un mapa estático `tipo → [ {clave, etiqueta, desde, formato?, destacado?, ambito} ]`
que el backend (o el propio front) recorre para armar `camposMostrar` a partir de
`datos` + `temporal` + `camposExtra`. Ejemplo para `vuelo`:

```js
const REGISTRY_CAMPOS = {
  vuelo: [
    { clave:'aerolinea', etiqueta:'Aerolínea',   desde:'datos.aerolinea',                          ambito:'ambos' },
    { clave:'vuelo',     etiqueta:'Vuelo',        desde:'datos.numeroVuelo',        destacado:true, ambito:'ambos' },
    { clave:'cabina',    etiqueta:'Cabina',       desde:'datos.cabina',                             ambito:'detalle' },
    { clave:'salida',    etiqueta:'Salida',       desde:'temporal.inicio',          formato:'fechaHora', ambito:'ambos' },
    { clave:'llegada',   etiqueta:'Llegada',      desde:'temporal.fin',             formato:'fechaHora', ambito:'ambos' },
    { clave:'duracion',  etiqueta:'Duración',     desde:'datos.duracion',                           ambito:'detalle' },
    { clave:'equipaje',  etiqueta:'Equipaje',     desde:['datos.equipajeBodega','datos.equipajeCabina'], formato:'unir', ambito:'detalle' },
    { clave:'estado',    etiqueta:'Estado',       desde:'estado',                   formato:'pillEstado', ambito:'ambos' },
  ],
  hotel: [
    { clave:'checkin',  etiqueta:'Check-in',    desde:'temporal.inicio', formato:'fechaHora', ambito:'ambos' },
    { clave:'checkout', etiqueta:'Check-out',   desde:'temporal.fin',    formato:'fechaHora', ambito:'ambos' },
    { clave:'noches',   etiqueta:'Duración',    desde:'datos.noches',    formato:'noches',    ambito:'ambos' },
    { clave:'habitacion', etiqueta:'Habitación', desde:'datos.habitaciones.0.descripcion',      ambito:'ambos' },
    { clave:'regimen',  etiqueta:'Régimen',     desde:'datos.habitaciones.0.regimen',           ambito:'ambos' },
    { clave:'telefono', etiqueta:'Teléfono hotel', desde:'datos.telefonoHotel',                 ambito:'detalle' },
    { clave:'estado',   etiqueta:'Estado',      desde:'estado', formato:'pillEstado',           ambito:'ambos' },
  ],
  // ... un bloque análogo por cada tipo, cubriendo lo que ya pintan los
  // prototipos: filas `.dr-l`/`.dr-v` en prototipo-app-viajero.html y
  // `ai-field-lbl`/`ai-field-val` en prototipo-panel-agencia.html.
};
```

**Reglas del builder que arma `camposMostrar` a partir del registry:**
1. Recorrer el registry del `tipo` del servicio, en orden.
2. Resolver `desde` (path o array de paths) contra el servicio. Si el valor es
   `null`/`undefined`/`[]` → **omitir la fila entera** (no mostrar "Cabina: —").
3. Si `desde` es un array de paths, aplicar `formato:'unir'` (concatenar los que
   existan) en vez de fallar si falta uno.
4. Aplicar `formato` (`fechaHora`, `noches`, `pillEstado`, `unir`, ...) para
   convertir el valor crudo en el string final a mostrar.
5. Al final, anexar una fila por cada entrada de `camposExtra` tal cual vino.
6. Si `clave` (o el path `desde`) aparece en `extraccion.camposInciertos`, marcar
   la fila con un flag visual (ej. ícono "revisar") — no ocultarla.
7. `ambito:'resumen'` → solo en cards/resumen; `'detalle'` → solo en la pantalla
   de detalle completo; `'ambos'` → en las dos.

Este registry es exactamente lo que hace hoy, a mano y por servicio, el HTML de
`prototipo-app-viajero.html` (bloques `<div class="dr">...`) y
`prototipo-panel-agencia.html` (`SAMPLE_EXTRACTIONS[...].fields`) — la diferencia
es que pasa a ser una tabla de configuración única por `tipo`, no texto
hardcodeado por viaje.

## Catálogos de plataforma (enriquecimiento, nunca escrito por la IA)

Tres pedidos de producto —link de check-in de la aerolínea, link/portal de la
aseguradora, tipo de cambio del destino— tienen algo en común: son datos que
**no vienen impresos en el documento** y que el prompt de parseo prohíbe
inventar (regla anti-alucinación, `PROMPT-PARSEO-v1.md` §3 / `PROMPT-PARSEO-v2.md`
regla 3 — "nunca completar con conocimiento general del mundo"). No son un dato
del *tenant* tampoco: la web de check-in de Aerolíneas Argentinas es la misma
para todas las agencias que usan Peregrí. Por eso viven como catálogos propios
de la **plataforma**, con el mismo espíritu que el registry `camposMostrar` de
arriba: derivados por código al leer, resueltos por una clave que sí sale del
parseo o del viaje.

```js
// catalogo_aerolineas — resuelto por servicios.datos.codigoAerolinea (IATA)
{ iata:'AR', nombre:'Aerolíneas Argentinas', web:'https://www.aerolineas.com.ar',
  urlCheckin:'https://www.aerolineas.com.ar/checkin', ventanaCheckinHoras:48,
  urlEstadoVuelo:'https://www.aerolineas.com.ar/estado-de-vuelo' }

// catalogo_aseguradoras — resuelto normalizando servicios.datos.aseguradora
{ claveNormalizada:'assist card', nombre:'Assist Card', web:'https://www.assistcard.com',
  portalCliente:'https://www.assistcard.com/mi-cuenta',
  urlTelemedicina:'https://www.assistcard.com/telemedicina', telefonoSOSGlobal:null }

// catalogo_paises — resuelto por viajes.destinos[].codigoPais (ver más abajo)
{ iso2:'IT', nombreEs:'Italia', flag:'🇮🇹', moneda:'EUR', simboloMoneda:'€' }
```

**Precedencia:** si el documento sí trae el dato (`proveedor.sitioWeb` de un
servicio puntual), ese gana — el catálogo es *fallback* y enriquecimiento, no
una fuente que pise lo que dice el voucher. La resolución del check-in
(`estadoCheckin`: `cerrado` / `abierto` / `vencido`, comparando `NOW` contra
`temporal.inicio` menos `ventanaCheckinHoras`) es la misma lógica implementada
como mock en `prototipo-app-viajero.html` (catálogos `AEROLINEAS`/`ASEGURADORAS`,
función `estadoCheckin()`), con la salvedad de que ahí `NOW` es una constante
fija y acá sería el reloj real del servidor.

## País y moneda en `viajes`

`viajes.destinos[]` suma `codigoPais` (ISO-3166 alpha-2, ej. `'IT'`) junto al
`pais` en español que ya existía:

```js
destinos: [
  { ciudad: 'Roma', pais: 'Italia', codigoPais: 'IT', flag: '🇮🇹' },
],
```

Sin `codigoPais` no hay forma confiable de mapear un destino a `catalogo_paises`
y de ahí a su moneda: `pais` es texto libre en español (a veces sin tilde, ver
`servicios.ubicacion.*.pais` / `datos.origen.pais`), no un identificador
estable. La moneda del conversor de tipo de cambio **no se persiste** en
`viajes` — se deriva de `codigoPais` contra `catalogo_paises` en el momento de
mostrarla, igual que `camposMostrar` se deriva de `datos` en vez de guardarse.
`$defs.lugar` del schema de parseo (`servicios.ubicacion.*`, `datos.origen`/
`datos.destino`/`datos.desde`/`datos.hasta`) **no se toca** — sigue siendo texto
libre; el mapeo a ISO es responsabilidad del viaje, no del servicio individual.

## Servir el archivo original (visor de PDF/imagen en la app del viajero)

El pedido de "PDF crudo dentro del detalle de cada paso" necesita que el
viajero pueda pedir el archivo real detrás de un `servicio`, no solo sus datos
parseados. La cadena de resolución:

1. `servicios.documentoFuenteId` → `documentos_fuente._id`.
2. `documentos_fuente.archivo.storageKey` → `GET /api/documentos/:id/archivo`,
   que devuelve una **URL firmada de vida corta** (no el `storageKey` crudo, que
   es una ruta interna de storage) tras verificar que el viajero autenticado
   pertenece al `viajeId` del documento.
3. La vista de detalle abre el visor apuntando a `extraccion.paginasFuente[0]`
   de ese servicio (`#page=N` en el visor de PDF) — salta directo a la página de
   la que salieron los datos, no a la página 1 del archivo.

Como un documento genera varios `servicios` (`documentos_fuente.serviciosGenerados[]`
— ver "Por qué `documentos_fuente` y `servicios` van separadas" más arriba),
varios pasos del itinerario pueden apuntar al **mismo** archivo, cada uno con su
propio `pagina` de `paginasFuente`: el voucher de traslados+excursión que trae 3
servicios es el ejemplo real en `fixtures/traslados-y-excursion.json`. Si
`documentoFuenteId` es `null` (servicio cargado a mano), el visor muestra el
estado vacío en vez de intentar resolver un archivo — es el mismo criterio que
usa `prototipo-app-viajero.html` con `paso.documento === null`.

## Cómo se arma el itinerario (consumo de `servicios`)

El motor de itinerario (ya esbozado como `rebuildItinerary()` en
`prototipo-panel-agencia.html:1128`) pasa a leer directamente la colección
`servicios` de un viaje:

1. Traer todos los `servicios` de `viajeId` con `estado != 'cancelado'`.
2. Para cada uno, tomar `temporal.inicio` (y `temporal.fin` si aplica, ej.
   check-out de hotel o el traslado de salida) como los puntos que aparecen en la
   línea de tiempo.
3. Ordenar por fecha/hora. Los de `modo:'sin_fecha'` van a una sección aparte
   ("sin fecha asignada"); los de `modo:'transversal'` (seguro) no aparecen como
   paso del timeline sino en una sección fija de "Documentos del viaje".
4. Agrupar visualmente por día calendario para el layout `tl-day` de
   `prototipo-app-viajero.html`.
5. `esComplemento:true` no genera una fila propia en el timeline: se anexa como
   línea secundaria dentro de la card de su `complementoDe`.
6. `estado:'no_incluido'` sí aparece, con un tratamiento visual distinto (aviso,
   no confirmación) — el viajero necesita saber que ese tramo no está resuelto.

## Relación con el flujo *human-in-the-loop* existente

Sigue siendo el mismo patrón que ya describe `CONTEXTO-PROYECTO.md` (subir →
"Leyendo con IA…" → revisar → confirmar): la llamada al modelo escribe los
`servicios` con `origenDatos:'ia'` y el `documentos_fuente.parseo.estado` en
`parseado` o `revision`. Nada impacta el itinerario del viajero hasta que el
agenciero confirma — en `revision`, la card de confirmación resalta justamente
los campos de `extraccion.camposInciertos`. Al confirmar sin cambios,
`origenDatos` queda en `'ia'`; si edita algo, pasa a `'ia_editado'` y se completa
`revision`.
