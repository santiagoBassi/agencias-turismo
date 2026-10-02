# POC — Panel de agencia (Peregrí)

Prueba de concepto: viajes, viajeros, carga de documentos y parseo real con Gemini
para armar el itinerario. Sin auth, sin base de datos real — `db.json` como
persistencia, FastAPI como API, un único HTML (copia cableada del prototipo) como
front. Ver `RESULTADOS-POC.md` para los números reales de costo/calidad medidos.

## Correrlo

```bash
cd poc
cp .env.example .env        # si todavía no existe
# completar GEMINI_API_KEY en .env (gratis en https://aistudio.google.com/apikey)
uv run uvicorn main:app --reload --port 8000
```

Abrir `http://localhost:8000`. El botón "Ingresar al panel" no valida nada (sin
auth) — solo carga el estado real desde el backend.

`db.json` y `uploads/` se crean solos al primer uso y no están versionados
(`.gitignore`). Para arrancar de cero, borrarlos.

## Flujo de punta a punta

1. Crear un viajero (sidebar → Viajeros → **+ Nuevo viajero**).
2. Crear un viaje y asignarle ese viajero.
3. Dentro del viaje → tab **Documentos** → subir un PDF/imagen de
   `../DocumentosEjemplo/`. Nota: subir un documento a un viaje **sin viajeros
   asignados** devuelve un error a propósito — es la precondición de
   `../parseo/MODELO-DATOS.md`.
4. Revisar los campos que devolvió Gemini (con la barra de tokens/costo/segundos
   arriba) y **Confirmar y guardar**.
5. Ver el resultado en los tabs **Servicios** e **Itinerario**.

## Verificar el parseo contra los fixtures de regresión

```bash
uv run python probar_fixtures.py
```

Corre los 6 documentos de `../DocumentosEjemplo/`, compara contra
`../parseo/fixtures/` y termina con la tabla de costo real total — el resultado
que buscaba esta POC.

## Cambiar de modelo

Un solo lugar: `GEMINI_MODEL` en `.env` (ver el comentario ahí para precios y
notas sobre modelos que activan "thinking" por defecto). No hace falta tocar
código para comparar.

## Archivos

| Archivo | Qué hace |
|---|---|
| `main.py` | Endpoints FastAPI + persistencia en `db.json` |
| `parseo.py` | Llamada a Gemini (prompt + schema de `../parseo/`) y medición de costo |
| `vista.py` | Traduce un servicio del schema a filas/cards para la UI |
| `static/index.html` | Front — copia cableada de `../prototipo-panel-agencia.html` |
| `probar_fixtures.py` | Corre y valida el parseo contra los fixtures de regresión |
| `RESULTADOS-POC.md` | Números reales medidos (costo y calidad) |
