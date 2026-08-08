# Expediente Digital CAPEX

Tablero tipo "caminito": muestra cada proyecto CAPEX como un roadmap de 6 pasos
(Alternativas, Búsqueda de proveedores, Precalificación, Riesgos, Cotizaciones,
Seguimiento), con el estatus real de cada uno y un botón directo a la
herramienta que corresponde.

## Probarla ahora mismo (con datos de ejemplo)

```bash
cd expediente_app
pip install -r requirements.txt
streamlit run app.py
```

Va a cargar `sample_expediente.csv`, que incluye el proyecto real del
compresor (Planta 2 Monterrey) que ya trabajamos con el agente, más 2
proyectos demo.

## Conectarla a tu Google Sheet real

1. Abre el Google Sheet donde ya tienes la hoja "Historicos internos".
2. Agrega una hoja nueva llamada **Expediente** con estas columnas exactas
   en la fila 1 (puedes copiar y pegar los datos de
   `expediente_capex_plantilla.xlsx`, hoja "Expediente", que ya te compartí):

   `ID Proyecto | Nombre del Proyecto | Etapa 1 Estatus | Etapa 1 Link | Etapa 2 Estatus | Etapa 2 Link | Etapa 3 Estatus | Etapa 3 Link | Etapa 4 Estatus | Etapa 4 Link | Etapa 5 Estatus | Etapa 5 Link | Etapa 6 Estatus | Etapa 6 Link | Responsable | Riesgo | Ahorro Estimado | Próxima Acción | Última Actualización`

   Estatus válidos: `Pendiente`, `En proceso`, `Completo`.
   Riesgo válido: `Bajo`, `Medio`, `Alto`.

3. En el menú del Sheet: **Archivo → Compartir → Publicar en la web**.
   Elige la hoja "Expediente", formato **CSV**, y dale a Publicar. Copia el
   link que te da.
4. Pega ese link en `app.py`, en la línea:

   ```python
   GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/.../pub?gid=...&single=true&output=csv"
   ```

5. Vuelve a correr `streamlit run app.py` — ahora va a leer tus datos
   reales en vez del ejemplo.

Nota: "Publicar en la web" hace la hoja legible por cualquiera que tenga el
link (no editable). Si el expediente tiene información sensible, en vez de
publicarlo puedes usar una cuenta de servicio de Google (gspread +
credenciales) — dime y te preparo esa versión, es un poco más de setup pero
mantiene la hoja privada.

## Ajustar los links de cada etapa

En `app.py`, el diccionario `TOOL_LINKS` define a dónde manda el botón de
cada etapa (chat de Copilot, Jotform, la app de cotizaciones, Power BI).
Ya están precargados los links que conozco — solo falta que agregues el
del tablero de Power BI en la etapa 6, y si tienes más de un formulario de
Jotform, ajusta cuál va en la etapa 3.

## Desplegarla (como la app de cotizaciones)

1. Sube esta carpeta a un repo de GitHub (puede ser privado).
2. Entra a [share.streamlit.io](https://share.streamlit.io), conecta el
   repo, y selecciona `app.py` como archivo principal.
3. Listo — te da una URL pública, igual que tu app de cotizaciones.
