# Contexto del proyecto — Peregrí

> Léeme antes de tocar cualquier archivo de este repo. El objetivo es que un agente nuevo entienda de qué trata el producto sin tener que interpretar los prototipos HTML desde cero.

## Qué es esto

**Peregrí** es una plataforma **SaaS white-label** que se vende a **múltiples agencias de viajes**. No es una app para una sola agencia: cada agencia que la contrata obtiene su propia instancia con su marca puesta, tanto para operar internamente como para entregarle una experiencia digital a sus clientes.

La propuesta de valor: hoy una agencia arma el viaje de un cliente a mano (WhatsApp, mails sueltos, PDFs de vuelos/hoteles/excursiones) y el cliente termina con la información dispersa. Peregrí le da a la agencia:
1. Un **panel de gestión** para cargar el viaje completo (vuelos, hotel, seguro, excursiones, documentos).
2. Una **app para el viajero** donde ese cliente ve todo su viaje ordenado, con su itinerario armado automáticamente.
3. Un **parseo de documentos con IA**: la agencia sube el PDF que ya tiene (e-ticket, voucher de hotel, póliza de seguro) y el sistema extrae los datos en vez de tipearlos a mano.

No existe una agencia real llamada "Peregrí" — Peregrí es el **nombre del producto/plataforma**, no de ninguna agencia cliente.

## Los dos frentes del producto

### 1. App del viajero
Lo que ve el **cliente final** de la agencia (el turista). Es mobile-first: itinerario día a día, detalle de vuelos, hotel, documentos (boarding pass, voucher, pasaporte), seguro de viaje, y una sección para explorar el destino y ver excursiones reservadas.

- Prototipo: `prototipo-app-viajero.html`
- Es un **"design board"**: un único HTML que renderiza varios mockups de teléfono lado a lado, cada uno mostrando una pantalla de arranque distinta. Dentro de cada teléfono hay navegación real por tabs/botones (JS vanilla, sin routing de verdad).

### 2. Panel de la agencia
Lo que usa el **agenciero** (el operador de la agencia) para armar y gestionar los viajes de sus clientes: dashboard de viajes activos, alta de viajeros, alta de viajes, carga de servicios (vuelos/hotel/seguro/excursiones), carga de documentos con parseo IA, y una vista previa de cómo el viajero ve todo en su app.

- Prototipo: `prototipo-panel-agencia.html`
- Es una SPA simulada: sidebar + contenido, login → dashboard → detalle de viaje con tabs.

**Relación entre ambos:** el panel es donde se *carga* la información; la app del viajero es donde esa información se *consume*. El tab "Vista previa del viajero" del panel muestra un mini-mockup de la app del viajero para que el agenciero vea el resultado final sin salir del panel.

## Modelo de marca (agnóstico vs. custom)

Este es el punto de diseño más importante del producto, porque define cómo se vende a distintas agencias:

- **App del viajero → agnóstica de la agencia + personalización liviana.** El layout, la navegación y el sistema de diseño son estándar de Peregrí. Lo único que cambia por agencia es **logo + color de marca**. El objetivo es minimalismo y consistencia: cualquier agencia que se sume debe verse bien sin rediseño a medida.
- **Panel de la agencia → bien custom.** Cada agencia elige su **logo** y su **color primario** (con un default de marca Peregrí si no configuran nada), y ese branding se aplica a todo el panel: sidebar, avatares, botones, acentos. Existe una pantalla de **Configuración/Personalización** para esto.

**Cómo está implementado en el código:** ambos prototipos usan **variables CSS de marca** (`--brand`, `--brand-2`, `--brand-soft`, etc. en `:root`) en vez de colores hardcodeados. Cambiar el theming de una agencia es, en principio, cuestión de cambiar esas variables (y en el panel, además, hay un objeto de estado JS con el logo/color de la agencia actual). El **default de plataforma es Peregrí**; las demos usan **Hybris Turismo** como agencia de ejemplo para probar que el theming funciona con una marca distinta del default.

> Agencia de ejemplo en las demos: **Hybris Turismo**. Es un nombre ficticio elegido para no atarse a ninguna agencia real — no confundir con "Peregrí" (la plataforma).

## Feature estrella: parseo de documentos con IA

El flujo que más vende el producto: la agencia **sube el documento que ya tiene** (e-ticket de vuelo, voucher de hotel, póliza de seguro, boarding pass) y la IA extrae los datos estructurados en vez de que alguien los tipee a mano.

**Patrón UX (human-in-the-loop), así está pensado en ambos prototipos:**
1. La agencia sube o arrastra el archivo.
2. Aparece un estado de "Leyendo con IA…" (spinner).
3. Se revelan los campos extraídos en una card de revisión.
4. La agencia **revisa y confirma** ("Confirmar y guardar") — nunca se guarda automáticamente sin revisión.
5. Al confirmar, se crea el "servicio" correspondiente (vuelo, hotel, seguro, excursión) y el documento queda listado; el **itinerario del viaje se regenera** ordenando por fecha/hora todos los servicios cargados.

**Tipos de documento soportados (según los ejemplos reales del proyecto):**
- **E-ticket de vuelo** → aerolínea, código de reserva, ruta, horarios, pasajero, equipaje.
- **Voucher de hotel** → check-in/out, noches, habitación, régimen, huéspedes.
- **Traslados / excursión** → servicio, fecha/hora, punto de encuentro, teléfono de emergencia.
- **Paquete / actividades** (ej. tours, entradas a parques) → proveedor, voucher, fechas, pasajeros.
- **Póliza de seguro de viaje** → coberturas, número de póliza, teléfono SOS.
- **Boarding pass** → vuelo, asiento, puerta.

La carpeta `DocumentosEjemplo/` contiene PDFs e imágenes **reales** de estos tipos (vuelo, hotel, traslados, paquete/excursión) que se usan como insumo de datos para las demos de parseo — son el material de referencia para que la simulación de IA en el prototipo tenga datos creíbles.

## Estado real del código (qué es real vs. simulado)

Importante para no sobreestimar el prototipo:

- Ambos archivos son **HTML autocontenidos** (HTML + CSS + JS vanilla, sin frameworks, sin build, sin dependencias externas ni CDNs). Se abren directo en el navegador.
- **No hay backend.** Todo el estado vive en memoria (variables JS) y se pierde al recargar la página.
- El **parseo de IA es una simulación**: no se lee el contenido real del archivo ni se llama a ningún modelo; se dispara un timeout y se muestran datos de ejemplo ya escritos, elegidos para representar lo que una extracción real devolvería.
- La estimación de desarrollo para construir esto de verdad (backend, apps reales, etc.) está en `estimacion-wanda-viajes.md` — ese documento es un presupuesto comercial anterior a la definición de marca "Peregrí"/multi-agencia; su contenido de horas/costos sigue siendo válido como referencia, pero su nombre de archivo y el approach mono-agencia ("Wanda Viajes") están desactualizados respecto a la dirección actual del producto (SaaS multi-agencia).

## Glosario

- **Agenciero**: el operador humano de una agencia de viajes que usa el panel para cargar y gestionar los viajes de sus clientes.
- **Viajero**: el cliente final de la agencia, quien usa la app del viajero para ver su viaje.
- **Agencia**: el cliente de Peregrí (el negocio que contrata la plataforma). Cada agencia tiene su propio branding.
- **Magic link**: método de acceso del viajero a su app sin contraseña (link enviado por email/WhatsApp que loguea directo).
- **Voucher**: comprobante de un servicio reservado (hotel, excursión, traslado) emitido por el proveedor.
- **E-ticket**: comprobante electrónico de un pasaje aéreo.
- **White-label**: producto que se re-marca con la identidad de cada cliente (acá: cada agencia) en vez de mostrar la marca del fabricante.

## Archivos del proyecto

| Archivo | Qué es |
|---|---|
| `CONTEXTO-PROYECTO.md` | Este archivo. |
| `prototipo-app-viajero.html` | Prototipo de la app del viajero (mobile-first, design board de varias pantallas). |
| `prototipo-panel-agencia.html` | Prototipo del panel web del agenciero. |
| `estimacion-wanda-viajes.md` | Presupuesto de desarrollo del MVP (horas/costos). Nombre y enfoque desactualizados (ver arriba), contenido numérico aún de referencia. |
| `DocumentosEjemplo/` | PDFs e imagen reales (e-ticket, voucher de hotel, traslados/excursión, paquete) usados como insumo de datos para las demos de parseo IA. |
| `parseo/` | Contrato real de parseo IA (todavía no cableado a los prototipos): el prompt versionado (`PROMPT-PARSEO-v1.md`), el JSON Schema de la salida (`esquema-servicio.schema.json`), el modelo de datos NoSQL completo (`MODELO-DATOS.md` — las seis colecciones: `agencias`, `usuarios`, `viajeros`, `viajes`, `documentos_fuente`, `servicios`, incluyendo el gate de precondiciones antes de parsear) y los fixtures de regresión para cada documento de `DocumentosEjemplo/` (`fixtures/`). |
