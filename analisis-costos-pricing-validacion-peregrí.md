# Peregrí — costos, unit economics y pricing a validar

**Fecha:** 16 de julio de 2026  
**Moneda:** USD, sin impuestos ni comisiones de cobro  
**Propósito:** definir una hipótesis de costos y precios antes de construir el SaaS y usarla para validar interés real con 5–6 agencias.

## Conclusión ejecutiva

El parseo con IA es muy barato frente al valor que puede entregar Peregrí. En la muestra completa de documentos de este proyecto —un caso deliberadamente cargado— el presupuesto razonable es de **USD 0,03 por viaje** usando el flujo eficiente, o **USD 0,05 por viaje** si todo se procesa como imagen. Por eso no conviene fijar el precio a partir de los tokens.

Para un SaaS multi-agencia compartido, la infraestructura inicial debería presupuestarse en **USD 60/mes**. Con una arquitectura realmente multi-tenant ese monto se comparte entre todas las agencias; si se despliega una instancia separada por agencia, el costo fijo se multiplica y el modelo pierde atractivo.

La propuesta a testear es cobrar por **viajes nuevos creados por mes**, con una política de uso razonable de documentos. Como hipótesis inicial de precio de lista: **USD 79 / 179 / 399 mensuales**. No son “el precio correcto”: son precios concretos para verificar si las agencias comprarían, no sólo si encuentran lindo el prototipo.

---

## 1. Qué se midió

Se revisaron los seis archivos de `DocumentosEjemplo/`. En conjunto representan un viaje con mucha documentación: e-ticket, hotel, traslados/excursión, paquete/actividades, pases de parque y una imagen recibida por WhatsApp.

| Muestra | Tipo | Páginas / equivalentes | Texto extraíble | Tamaño |
|---|---|---:|---:|---:|
| Paquete Tortuguero + alquiler de auto | PDF | 6 | 7.887 caracteres | 0,47 MB |
| Hotel Lomas del Volcán | PDF | 1 | 4.992 caracteres | 0,09 MB |
| Universal Express Pass x4 | PDF | 10 | 28.577 caracteres | 0,27 MB |
| E-ticket aéreo | PDF | 1 | 3.879 caracteres | 0,02 MB |
| Traslados y excursión | PDF | 2 | 4.377 caracteres | 0,13 MB |
| Imagen de WhatsApp | JPEG | 1 | — | 0,18 MB |
| **Total de la muestra** | **6 archivos** | **21** | **49.712 caracteres** | **1,16 MB** |

Los cinco PDFs tienen texto seleccionable. Eso importa: una implementación que primero extrae texto del PDF y sólo usa visión para escaneos/imágenes cuesta menos y es más controlable que mandar todo como imagen.

Esta muestra debe tomarse como un **caso alto**, no como un supuesto de viaje promedio. La tarifa propuesta incluye hasta 10 documentos y 30 páginas/equivalentes por viaje; el caso medido entra en ese límite.

---

## 2. Costo variable: parsear documentos con IA

### Modelo y método de cálculo

Para presupuestar se usa **GPT-5.4 mini** con salida JSON estructurada y revisión humana obligatoria. Sus precios estándar publicados son **USD 0,75 por millón de tokens de entrada** y **USD 4,50 por millón de tokens de salida**. Es un punto de partida de calidad; antes de producción hay que evaluarlo contra una muestra etiquetada de vouchers reales. [Precios oficiales de OpenAI](https://developers.openai.com/api/docs/pricing)

Para imágenes, el cálculo usa páginas normalizadas con lado largo de 1.280 px. OpenAI explica que estos modelos dividen la imagen en parches de 32×32 px y que GPT-5.4 mini aplica un multiplicador de 1,62; también limita el detalle alto a 1.536 parches. [Regla oficial de tokenización de visión](https://developers.openai.com/api/docs/guides/images-vision)

No se deben enviar documentos originales sin límite de resolución. La aplicación debe:

1. Extraer texto localmente si el PDF lo contiene.
2. Enviar texto + esquema JSON al modelo.
3. Convertir a imagen sólo las páginas escaneadas o que no tengan texto útil.
4. Registrar `input_tokens`, `output_tokens`, documento y confianza de cada parseo.
5. Mostrar siempre los campos para revisión y confirmación humana antes de guardarlos.

### Escenario A — recomendado: PDF con texto + visión sólo donde hace falta

| Concepto de la muestra completa | Tokens presupuestados | Costo |
|---|---:|---:|
| Texto de los PDFs: 49.712 caracteres, estimado conservador + instrucciones/esquemas | 14.928 tokens de entrada | USD 0,0112 |
| Imagen de WhatsApp, normalizada | 1.750 tokens de entrada | USD 0,0013 |
| JSON de salida de los seis documentos (margen amplio) | 2.400 tokens de salida | USD 0,0108 |
| **Una pasada** | **16.678 entrada + 2.400 salida** | **USD 0,0233** |
| Reserva del 20% para reintento/validación | — | USD 0,0047 |
| **Presupuesto por viaje documentado** | — | **USD 0,028 ≈ USD 0,03** |

La estimación de texto usa una aproximación de 4 caracteres por token; la facturación real se debe tomar del campo `usage` de la API. El margen del 20% evita prometer una precisión que todavía no tenemos.

### Escenario B — conservador: todas las páginas como imagen

| Tipo de página normalizada | Cantidad | Tokens de visión por página | Tokens de visión |
|---|---:|---:|---:|
| Carta (6 páginas) | 6 | 2.009 | 12.053 |
| A4 (14 páginas) | 14 | 1.879 | 26.309 |
| JPEG de WhatsApp | 1 | 1.750 | 1.750 |
| Instrucciones y esquema JSON | — | — | 2.500 |
| **Entrada total** | **21** | — | **42.612** |
| Salida JSON presupuestada | — | — | **2.400** |

Costo de una pasada: `(42.612 × 0,75 + 2.400 × 4,50) / 1.000.000 = USD 0,0428`. Con 20% de reserva: **USD 0,051 ≈ USD 0,05 por viaje**.

### Qué usar para presupuestar

Usaría **USD 0,03 por viaje** como costo operativo de IA en las proyecciones y **USD 0,05** como tope conservador para este tipo de viaje cargado. Es preferible calcular los planes con USD 0,03 y monitorear el percentil 95 de costo real: si supera USD 0,05 por viaje durante dos meses, se revisa el límite de páginas o el pipeline.

Hay modelos más baratos, por ejemplo GPT-5.4 nano, pero no conviene elegirlos sólo por precio. La diferencia sería de centavos; una fecha, pasajero o tramo de vuelo mal extraído cuesta más en soporte y confianza que lo que se ahorra en tokens.

### Almacenamiento documental

La muestra completa pesa 1,16 MB. Incluso 1.000 viajes mensuales retenidos por 24 meses sumarían aproximadamente 28 GB. En Cloudflare R2 los primeros 10 GB-mes son gratuitos; luego el almacenamiento estándar cuesta USD 0,015/GB-mes, sin cargo de egreso. Eso da alrededor de **USD 0,27/mes** en este escenario de 24.000 viajes archivados. [Precios oficiales de Cloudflare R2](https://developers.cloudflare.com/r2/pricing/)

El almacenamiento tampoco es el driver de costo al inicio. De todos modos, hay que definir una política: por ejemplo, documentos originales por 24 meses y luego archivo o borrado a pedido de la agencia.

---

## 3. Infraestructura fija mensual

### Arquitectura supuesta

Una única plataforma multi-tenant: aplicación web/PWA y funciones de servidor, base de datos compartida con aislamiento por agencia, autenticación, almacenamiento privado de documentos y envío de magic links. Cada agencia cambia logo/color y puede usar un subdominio, pero **no recibe un servidor o base de datos propios**.

| Rubro | Servicio / supuesto | Mensual |
|---|---|---:|
| Web, panel y funciones de servidor | Vercel Pro, una cuenta | USD 20,00 |
| Base de datos, Auth, API y backups | Supabase Pro, primer proyecto | USD 25,00 |
| Documentos | R2; dentro de 10 GB y operaciones gratuitas | USD 0,00 |
| Emails transaccionales | Resend Free; hasta 3.000 emails/mes y 100/día | USD 0,00 |
| Dominio principal | Reserva de USD 18/año | USD 1,50 |
| Observabilidad inicial | Planes gratuitos y alertas básicas | USD 0,00 |
| **Subtotal operativo** | | **USD 46,50** |
| Reserva del 25% por uso, logs y desvíos | | USD 11,63 |
| **Presupuesto fijo recomendado** | | **USD 58,13 → USD 60/mes** |

Vercel Pro figura en USD 20/mes e incluye crédito de uso; Supabase Pro parte de USD 25/mes, incluye el primer proyecto, 8 GB de base, 100 GB de archivos y backups diarios de 7 días. [Vercel Pricing](https://vercel.com/pricing) · [Supabase Pricing](https://supabase.com/pricing). Resend ofrece 3.000 emails/mes en su plan gratuito; al superar esa necesidad, el siguiente escalón es USD 20/mes por 50.000 emails. [Resend Pricing](https://resend.com/pricing?product=transactional)

### Escalones prácticos de gasto

| Momento | Fijo mensual que conviene prever | Qué cambió |
|---|---:|---|
| Validación / 5–6 agencias | **USD 60** | Una plataforma compartida, email gratuito |
| Más de 3.000 emails/mes | **USD 80** | Se suma Resend Pro |
| Mayor tráfico o base de datos | **USD 100–150** | Más cómputo/egreso, no otra plataforma por agencia |

Los montos no incluyen IVA, percepciones, comisiones de tarjeta, procesamiento de cobros, WhatsApp, soporte humano, horas de desarrollo, asesoramiento legal/privacidad ni una app nativa en tiendas. Para agencias argentinas, es más sano expresar el precio en USD de referencia y facturar el equivalente en ARS según una regla contractual clara, en vez de dejar el precio fijo en pesos por muchos meses.

### Advertencia importante: multi-tenant real

Si se crea una instalación independiente por agencia, la base de USD 60 se volvería aproximadamente **USD 360/mes para seis agencias**, antes de IA. No lo recomiendo para esta etapa. La arquitectura correcta es una sola plataforma con `agency_id`, Row Level Security, storage privado y configuración de marca por tenant. El aislamiento dedicado sólo tendría sentido como plan Enterprise, cobrado aparte.

---

## 4. Unit economics y planes de precio a testear

### Definición simple de unidad

Un **viaje incluido** es un viaje nuevo creado durante el mes, con hasta **10 documentos y 30 páginas/equivalentes** para parseo IA. Los viajes ya creados no vuelven a consumir cupo; reparsear el mismo documento por un error sí queda registrado. Esto hace que el plan sea entendible para la agencia y protege contra usar Peregrí como procesador genérico de cientos de PDFs.

Los costos siguientes usan USD 0,03 de IA por viaje, incluso para la muestra alta. También reservan **5% del precio** para el cobro, aunque el proveedor de pagos concreto puede variar.

| Plan a validar | Precio mensual | Viajes nuevos/mes | Costo máx. IA incluido | Cobro estimado 5% | Margen antes de soporte y fijo |
|---|---:|---:|---:|---:|---:|
| **Esencial** | USD 79 | 30 | USD 0,90 | USD 3,95 | **USD 74,15 (94%)** |
| **Crecimiento** | USD 179 | 150 | USD 4,50 | USD 8,95 | **USD 165,55 (92%)** |
| **Pro** | USD 399 | 500 | USD 15,00 | USD 19,95 | **USD 364,05 (91%)** |

Reglas sugeridas:

- Cargo por viaje adicional: **USD 1,50**, o upgrade automático si conviene más.
- Onboarding y configuración de marca: **USD 199 una vez**, bonificable para las primeras agencias de diseño. El trabajo humano de alta, marca y capacitación no debería ser gratis por defecto.
- Dominio propio, integración especial, cuenta de usuario adicional o aislamiento dedicado: cotización aparte.
- No vender “documentos ilimitados”. Incluir el límite de uso razonable sin convertir la conversación comercial en una discusión de tokens.

### Punto de equilibrio de infraestructura

Con este precio, **una sola agencia Esencial cubre los USD 60 de infraestructura**, pero no cubre tu tiempo. El costo relevante no es el servidor: son ventas, onboarding, soporte, correcciones y recuperar la inversión de desarrollo.

El presupuesto previo del proyecto estima aproximadamente USD 26.700 para PWA + SaaS multi-agencia. Si se tomara como inversión a recuperar, seis agencias en una mezcla de 2 Esencial, 3 Crecimiento y 1 Pro aportarían:

| Concepto | Monto mensual |
|---|---:|
| MRR: 2 × 79 + 3 × 179 + 1 × 399 | USD 1.094,00 |
| Comisión de cobro estimada | - USD 54,70 |
| IA incluida | - USD 30,30 |
| Infraestructura | - USD 60,00 |
| **Contribución antes de soporte/impuestos** | **USD 949,00** |
| Recupero teórico de USD 26.700 | **~28 meses** |

Esto no es una proyección de ventas: muestra por qué un plan de USD 20–40/mes sería peligroso. Para recuperar desarrollo en 36 meses, sin contar soporte, hacen falta alrededor de USD 742/mes de contribución sólo para esa inversión. Con seis agencias, el promedio neto debe estar cerca de USD 124 por agencia antes de sumar soporte y riesgo de churn.

---

## 5. Cómo validar precio con 5–6 agencias

No preguntaría únicamente “¿cuánto pagarías?”. Es una pregunta hipotética: suele generar respuestas amables pero poco útiles. La validación debe buscar compromiso y contexto de uso.

### Guion sugerido de entrevista

1. Pedir que cuenten el último viaje real que armaron: cuántos documentos recibió, quién cargó los datos, cuánto tardó y qué salió mal.
2. Preguntar el costo actual: tiempo del operador, reenvío de PDFs por WhatsApp, consultas del pasajero, errores y sensación de marca poco profesional.
3. Mostrar el prototipo sólo después de entender ese flujo. Preguntar qué parte usarían semanalmente y qué campo no confiarían a una IA.
4. Mostrar **un plan y precio concretos**: por ejemplo, “USD 179/mes hasta 150 viajes nuevos, con documentos y app del viajero incluidos”. Preguntar: “¿qué tendría que ser cierto para que lo contrates en los próximos 30 días?”
5. Cambiar el precio entre entrevistas, no durante la misma conversación: probar USD 79/179/399 como anclas según el tamaño de agencia y registrar objeciones exactas.
6. Cerrar con una señal fuerte: piloto pago con precio fundador, carta de intención o seña acreditable contra los primeros meses. Un “avisame cuando esté” no valida disposición a pagar.

### Criterio de avance recomendado

Antes de invertir en el desarrollo completo, buscaría al menos **3 compromisos concretos de 6 conversaciones**, de los cuales al menos 2 acepten explícitamente un precio mensual de USD 79 o más (o su equivalente). Si el interés existe pero el precio no, no es momento de bajar precio: primero hay que entender si falta valor, confianza en el parseo, integración con su operación o urgencia.

---

## 6. Riesgos y decisiones a resolver antes de construir

- **La mayor incógnita es la precisión, no el costo.** Armar un set de 50–100 documentos reales anonimizados, definir campos esperados y medir exactitud por tipo de documento antes de comprometer una promesa comercial.
- **Los datos son sensibles.** Hay nombres, reservas, vuelos y potencialmente pasaportes. Definir retención, borrado, acceso por agencia, URLs firmadas, auditoría y términos de tratamiento de datos desde el diseño; no dejar documentos públicos.
- **No construir app nativa primero.** Para validar, una PWA y panel responsive tienen mejor relación aprendizaje/costo. Las tiendas y offline avanzado se pueden decidir después de confirmar venta.
- **Separar “parseo” de “resultado confiable”.** El producto debe vender revisión rápida, no automatización ciega. La confirmación humana que ya propone el prototipo es una buena decisión de producto.
- **Medir por agencia desde el día uno.** Viajes creados, documentos procesados, tiempo hasta confirmación, correcciones y viajeros que abren su itinerario. Esos datos determinarán si se mantiene la métrica “viajes” o si hay que pasar a “viajes + documentos”.

## Próximo paso concreto

Usar este documento para preparar seis entrevistas y ofrecer un piloto fundador de 30 días. Mientras se valida, implementar sólo un pequeño experimento técnico de parseo sobre documentos anonimizados para confirmar el costo y la precisión. No hace falta construir la plataforma completa para contestar las dos preguntas críticas: **“¿lo usarían?”** y **“¿pagarían este precio?”**.
