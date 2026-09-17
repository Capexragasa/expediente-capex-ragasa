"""
Expediente Digital CAPEX - Ragasa
Tablero tipo "caminito": un roadmap por proyecto con las 6 etapas del proceso
de Compras CAPEX. Cada etapa tiene 3 checks concretos (lo que realmente hay
que hacer) mas una nota corta opcional; el estatus (Pendiente / En proceso /
Completo), el % de avance y las alertas de proyectos sin movimiento se
calculan solos, no se escriben a mano. Incluye un dashboard general con
metricas, una tabla filtrable con detalle al hacer clic, y lee los datos en
vivo desde un Google Sheet compartido (no hace falta tener la cuenta del
dueno del Sheet).

Antes del paso 5 (Cotizaciones) se agrega un modulo de riesgos de mercado:
tipo de cambio, inflacion, commodity del proyecto (historico + proyeccion
por regresion lineal) y una referencia de mano de obra, con una
recomendacion automatica de compra (comprar ahora / esperar / buscar
alternativas).

Como correrlo:
    pip install -r requirements.txt
    streamlit run app.py
"""

import re
from datetime import date, datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------

# Hoja "Expediente CAPEX - Ragasa (v2 checklist)" en Google Sheets. Compartida
# como "Cualquiera con el enlace - Lector", asi que cualquiera que abra la app
# (jefe, junior, quien sea) ve los datos reales sin necesitar la cuenta del
# dueno del Sheet. Marcar/desmarcar los checks = editar esta hoja.
SHEET_ID = "1nn2_AU-jGTHOL2QuaCaHQziNMryUn2XYBE--XSJj2NA"
SHEET_GID = "1587291527"
GOOGLE_SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"
GOOGLE_SHEET_EDIT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

# Link directo al agente "Asistente IA Compras CAPEX" en M365 Copilot. Ojo:
# para que el jefe o un junior lo puedan abrir, el agente tiene que estar
# compartido con ellos desde Agent Builder (boton "Compartir") - ese paso es
# manual en Microsoft 365, esta app no lo puede hacer por ti.
AGENTE_CAPEX_URL = "https://m365.cloud.microsoft/chat/?titleId=T_9bb37296-de18-3b4d-fc79-4a2610bf843a"

# Link directo al agente "CAPEX Market & Risk Intelligence" en M365 Copilot
# (el que analiza commodities/tipo de cambio/inflacion). Mismo requisito que
# el de arriba: tiene que estar compartido desde Agent Builder para que el
# jefe o un junior lo puedan abrir sin permisos de edicion.
COMMODITY_AGENT_URL = "https://m365.cloud.microsoft/chat/?titleId=T_4acf91d3-d628-e995-f9dc-3a75d993bb64"

# Los 3 formularios de precalificacion en Jotform, uno por tipo de proveedor.
# Se muestran los 3 en la etapa de Precalificacion para que se elija el
# correcto segun el proveedor y se copie/comparta ese link con el.
JOTFORM_FORMS = [
    {
        "tipo": "Fabricante",
        "descripcion": "Proveedor que fabrica o distribuye el equipo/material.",
        "url": "https://form.jotform.com/261668973439071",
    },
    {
        "tipo": "Contratista",
        "descripcion": "Proveedor que instala, construye o da servicio en sitio.",
        "url": "https://form.jotform.com/261668288562067",
    },
    {
        "tipo": "Ingeniería",
        "descripcion": "Proveedor de diseño, ingenieria o consultoria tecnica.",
        "url": "https://form.jotform.com/261668264570060",
    },
]

# Liga fija a cada herramienta, segun la etapa. Ajusta las que falten
# (Power BI).
TOOL_LINKS = {
    1: {"label": "Abrir Asistente CAPEX", "url": AGENTE_CAPEX_URL},
    2: {"label": "Abrir Asistente CAPEX", "url": AGENTE_CAPEX_URL},
    3: {"label": "Elegir formulario Jotform", "url": None},  # se maneja aparte
    4: {"label": "Abrir Asistente CAPEX", "url": AGENTE_CAPEX_URL},
    5: {"label": "Abrir app de cotizaciones", "url": "https://apex-nl-app-b3vcn5wdtbuikvz8v9guio.streamlit.app/"},
    6: {"label": "Ver tablero Power BI", "url": ""},
}

ETAPA_NOMBRES = {
    1: "Alternativas",
    2: "Busqueda de proveedores",
    3: "Precalificacion",
    4: "Evaluacion de riesgos",
    5: "Comparar cotizaciones",
    6: "Seguimiento y cierre",
}

ETAPA_DESCRIPCIONES = {
    1: "Comparar opciones tecnicas antes de salir a buscar proveedores.",
    2: "Identificar y validar posibles proveedores para el proyecto.",
    3: "Calificar formalmente a los proveedores candidatos con el formulario correcto.",
    4: "Revisar riesgos de proveedor, tecnicos, cronograma, financieros y normativos.",
    5: "Comparar las cotizaciones recibidas y elegir la mejor opcion.",
    6: "Cerrar la decision, dar seguimiento y documentar el resultado final.",
}

# Los 3 checks concretos que definen cada etapa. El estatus y el % de avance
# se calculan solos a partir de estos (no se escriben a mano en el Sheet).
ETAPA_CHECKS = {
    1: ["E1 Opciones comparadas", "E1 Equipo actual documentado", "E1 Alternativa definida"],
    2: ["E2 Proveedores identificados", "E2 Evidencia tecnica revisada", "E2 Lista confirmada"],
    3: ["E3 Formulario enviado", "E3 Formulario respondido", "E3 Rubrica aplicada"],
    4: ["E4 Riesgos identificados", "E4 Mitigaciones definidas", "E4 Riesgo global calculado"],
    5: ["E5 Cotizaciones recibidas", "E5 Comparativo hecho", "E5 Proveedor seleccionado"],
    6: ["E6 Enviado a aprobacion", "E6 Orden generada", "E6 Cierre documentado"],
}

ETAPA_NOTA_COL = {n: f"E{n} Nota" for n in range(1, 7)}

STATUS_COLORS = {
    "Completo": {"bg": "#e1f5ee", "text": "#085041", "icon": "check"},
    "En proceso": {"bg": "#faeeda", "text": "#854f0b", "icon": "clock"},
    "Pendiente": {"bg": "#f1efe8", "text": "#5f5e5a", "icon": "circle"},
}

RIESGO_COLORS = {
    "Alto": ("#fcebeb", "#791f1f"),
    "Medio": ("#faeeda", "#854f0b"),
    "Bajo": ("#eaf3de", "#27500a"),
}

RIESGO_EMOJI = {"Alto": "\U0001F534", "Medio": "\U0001F7E1", "Bajo": "\U0001F7E2"}

# Si un proyecto abierto (no Cerrado) no se ha tocado en mas de este numero de
# dias, se marca automaticamente como "sin movimiento" en el roadmap y en el
# resumen, sin que nadie tenga que revisarlo a mano.
DIAS_SIN_MOVIMIENTO_ALERTA = 5

# ---------------------------------------------------------------------------
# RIESGOS DE MERCADO: FX, INFLACION, COMMODITIES, MANO DE OBRA
# ---------------------------------------------------------------------------
# Todo esto alimenta el modulo que se muestra en el roadmap ANTES del paso 5
# (Cotizaciones), usando las columnas "Pais Proveedor", "Commodity
# Relacionado" y "Moneda Cotizacion" del Google Sheet. Fuentes gratuitas:
#   - FX y commodities: Alpha Vantage (limite: 25 requests/dia en el plan
#     gratuito -> por eso el cache es de horas, no de segundos).
#   - Inflacion Mexico: Banxico SIE (necesita un token gratuito que se
#     genera a mano en banxico.org.mx por un captcha; si no esta
#     configurado, se usa Banco Mundial como respaldo).
#   - Inflacion de otros paises: Banco Mundial (gratis, sin registro).
#   - Mano de obra: referencia cualitativa fija (no hay una fuente publica,
#     gratuita y en vivo para esto), claramente marcada como orientativa.


def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


# Key gratuita de Alpha Vantage (25 requests/dia). Se puede sobreescribir
# desde Settings -> Secrets en Streamlit Cloud con ALPHA_VANTAGE_API_KEY sin
# tocar el codigo.
ALPHA_VANTAGE_API_KEY = _get_secret("ALPHA_VANTAGE_API_KEY", "H3ODJAW773QN5V9W")
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"

# Token de Banxico SIE (64 caracteres). Se genera en
# https://www.banxico.org.mx/SieAPIRest/service/v1/token (requiere resolver
# un captcha manualmente, por eso no viene precargado). Configuralo en
# Settings -> Secrets como BANXICO_TOKEN.
BANXICO_TOKEN = _get_secret("BANXICO_TOKEN", "")
BANXICO_SERIE_INPC = "SP1"  # INPC general

# URL del Apps Script "puente" (Extensiones > Apps Script, en el propio Sheet,
# implementado como aplicacion web) que permite ESCRIBIR en el Sheet: marcar
# checks solos y guardar nuevas solicitudes sin copiar/pegar CSV a mano.
# Configuralo en Settings -> Secrets como APPS_SCRIPT_URL y APPS_SCRIPT_TOKEN
# (el token debe ser EXACTAMENTE igual al definido dentro del script). Si no
# esta configurado, la app sigue funcionando normal, solo en modo lectura
# para esa parte (se siguen pudiendo descargar CSVs para pegar a mano).
APPS_SCRIPT_URL = _get_secret("APPS_SCRIPT_URL", "")
APPS_SCRIPT_TOKEN = _get_secret("APPS_SCRIPT_TOKEN", "")


def escribir_en_sheet(payload: dict, timeout: int = 15):
    """POST generico al Apps Script puente. Devuelve (ok, info).

    Nunca truena la app: si no hay URL configurada o la llamada falla (Sheet
    no disponible, token incorrecto, etc.), regresa ok=False con un mensaje
    claro para mostrar en la UI, en vez de lanzar una excepcion."""
    if not APPS_SCRIPT_URL:
        return False, "Escritura automática no configurada (falta APPS_SCRIPT_URL en Secrets)."
    body = dict(payload)
    body["token"] = APPS_SCRIPT_TOKEN
    try:
        r = requests.post(APPS_SCRIPT_URL, json=body, timeout=timeout)
        data = r.json()
        if data.get("ok"):
            return True, data
        return False, data.get("error", "Error desconocido al escribir en el Sheet.")
    except Exception as e:
        return False, f"No se pudo conectar con el Sheet: {e}"


def marcar_check_sheet(id_proyecto: str, columna: str, valor: bool):
    return escribir_en_sheet(
        {"accion": "marcar_check", "idProyecto": id_proyecto, "columna": columna, "valor": valor}
    )


def actualizar_campo_sheet(id_proyecto: str, columna: str, valor):
    return escribir_en_sheet(
        {"accion": "actualizar_campo", "idProyecto": id_proyecto, "columna": columna, "valor": valor}
    )


def agregar_fila_sheet(datos: dict):
    return escribir_en_sheet({"accion": "agregar_fila", "datos": datos})


COUNTRY_INFO = {
    "México": {"moneda": "MXN", "wb_code": "MEX"},
    "Estados Unidos": {"moneda": "USD", "wb_code": "USA"},
    "China": {"moneda": "CNY", "wb_code": "CHN"},
    "Alemania": {"moneda": "EUR", "wb_code": "DEU"},
}

# Commodity (tal como aparece en el desplegable del Sheet) -> funcion de
# Alpha Vantage. No hay endpoint directo de "acero"; para proyectos con
# estructura/tuberia de acero se usa Cobre como proxy metalico.
COMMODITY_AV_FUNCTION = {
    "Cobre": "COPPER",
    "Aluminio": "ALUMINUM",
    "Petróleo WTI": "WTI",
    "Petróleo Brent": "BRENT",
    "Gas Natural": "NATURAL_GAS",
    "Trigo": "WHEAT",
    "Maíz": "CORN",
    "Algodón": "COTTON",
    "Azúcar": "SUGAR",
    "Café": "COFFEE",
}

# Mapeo automatico proyecto -> commodity(s) relevante(s), por palabras clave en
# el nombre/descripcion del proyecto. Se usa cuando la columna "Commodity
# Relacionado" del Sheet esta vacia (o en "Otro / No aplica"), para que
# cualquier proyecto nuevo -de hoy o futuro- se habilite solo, sin tener que
# configurar nada a mano fila por fila. A diferencia de la version anterior,
# aqui se pueden detectar VARIOS commodities relevantes a la vez (ej. un
# generador electrico usa cobre Y acero Y aluminio), cada uno con un nivel de
# relevancia, en vez de quedarse con el primero que matchee.
RELEVANCIA_RANK = {"Alta": 3, "Media": 2, "Baja": 1}

COMMODITY_KEYWORD_MAP = {
    # Cobre: bobinados, cableado, motores/generadores, subestaciones.
    "cobre": ("Cobre", "Alta"),
    "cableado": ("Cobre", "Alta"),
    "cable": ("Cobre", "Media"),
    "bobina": ("Cobre", "Alta"),
    "bobinas": ("Cobre", "Alta"),
    "devanado": ("Cobre", "Alta"),
    "devanados": ("Cobre", "Alta"),
    "alternador": ("Cobre", "Alta"),
    "generador": ("Cobre", "Alta"),
    "electrico": ("Cobre", "Media"),
    "electrica": ("Cobre", "Media"),
    "subestacion": ("Cobre", "Alta"),
    "motor": ("Cobre", "Media"),
    "compresor": ("Cobre", "Media"),
    "bomba": ("Cobre", "Media"),
    "chiller": ("Cobre", "Media"),
    "hvac": ("Cobre", "Media"),
    "aire acondicionado": ("Cobre", "Media"),
    "refrigeracion": ("Cobre", "Media"),
    "maquinaria": ("Cobre", "Baja"),
    # Acero: sin indice de materia prima directo en las fuentes gratuitas
    # aprobadas (Alpha Vantage no tiene STEEL). Se detecta y se muestra como
    # driver, pero se marca explicitamente sin dato en vivo (no se usa cobre
    # disfrazado de acero).
    "acero": ("Acero", "Alta"),
    "estructura": ("Acero", "Alta"),
    "estructural": ("Acero", "Alta"),
    "chasis": ("Acero", "Media"),
    "carcasa": ("Acero", "Media"),
    "tuberia": ("Acero", "Media"),
    "ducto": ("Acero", "Media"),
    # Aluminio
    "aluminio": ("Aluminio", "Alta"),
    "banda transportadora": ("Aluminio", "Media"),
    "transportador": ("Aluminio", "Media"),
    "conveyor": ("Aluminio", "Media"),
    "montacargas": ("Aluminio", "Baja"),
    "disipacion": ("Aluminio", "Media"),
    # Energia / combustibles
    "combustible": ("Gas Natural", "Alta"),
    "diesel": ("Gas Natural", "Media"),
    "caldera": ("Gas Natural", "Alta"),
    "gas natural": ("Gas Natural", "Alta"),
    "petroleo": ("Petróleo WTI", "Alta"),
    # Textil / empaque
    "empaque": ("Algodón", "Media"),
    "embalaje": ("Algodón", "Media"),
    "textil": ("Algodón", "Alta"),
}


def _normaliza_busqueda(texto: str) -> str:
    """minusculas y sin acentos, para que las palabras clave matcheen sin
    importar si el texto original trae o no tildes."""
    import unicodedata

    texto = str(texto or "").lower()
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def detectar_commodities(texto: str):
    """Devuelve (lista_commodities, fue_generico).

    lista_commodities es [(commodity, relevancia), ...] ordenada de mayor a
    menor relevancia, sin duplicar commodity (se queda con la relevancia mas
    alta encontrada para cada uno). Si no matchea nada, regresa Cobre como
    generico por defecto y fue_generico=True."""
    texto_norm = _normaliza_busqueda(texto)
    encontrados = {}
    for kw, (commodity, relevancia) in COMMODITY_KEYWORD_MAP.items():
        if kw in texto_norm:
            actual = encontrados.get(commodity)
            if not actual or RELEVANCIA_RANK[relevancia] > RELEVANCIA_RANK[actual]:
                encontrados[commodity] = relevancia
    if not encontrados:
        return [("Cobre", "Media")], True
    ordenado = sorted(encontrados.items(), key=lambda kv: -RELEVANCIA_RANK[kv[1]])
    return ordenado, False

# Referencia cualitativa de costo de mano de obra industrial por pais del
# proveedor. No es un dato en vivo (no encontramos una fuente publica y
# gratuita de series salariales por pais con API estable): es una nota de
# contexto para el comprador, marcada como tal en la UI.
LABOR_COST_REF = {
    "México": "Bajo-medio frente a EUA y Alemania (ventaja historica de manufactura en Mexico).",
    "Estados Unidos": "Alto; presiones salariales sostenidas en manufactura desde 2021.",
    "China": "Medio, en aumento sostenido en la ultima decada (ya no es 'mano de obra barata').",
    "Alemania": "Muy alto; de los costos laborales industriales mas altos del mundo.",
}


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def av_fx_rate(from_ccy: str, to_ccy: str):
    """Tipo de cambio actual entre dos monedas via Alpha Vantage."""
    if not from_ccy or not to_ccy or from_ccy == to_ccy:
        return None
    try:
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_ccy,
            "to_currency": to_ccy,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }
        r = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=10)
        data = r.json().get("Realtime Currency Exchange Rate", {})
        if not data:
            return None
        return {
            "rate": float(data.get("5. Exchange Rate", 0)),
            "fecha": data.get("6. Last Refreshed", ""),
        }
    except Exception:
        return None


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def av_commodity_series(commodity: str):
    """Serie mensual historica (ultimos ~24 meses) de un commodity via Alpha Vantage."""
    func = COMMODITY_AV_FUNCTION.get(commodity)
    if not func:
        return None
    try:
        params = {"function": func, "interval": "monthly", "apikey": ALPHA_VANTAGE_API_KEY}
        r = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=10)
        data = r.json().get("data", [])
        serie = [
            (d["date"], float(d["value"]))
            for d in data
            if d.get("value") not in (None, ".", "")
        ]
        serie.sort(key=lambda x: x[0])
        return serie[-24:]
    except Exception:
        return None


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def banxico_inpc_series():
    """Ultimos 13 meses del INPC general (Mexico) via Banxico SIE, si hay token."""
    if not BANXICO_TOKEN:
        return None
    try:
        url = f"https://www.banxico.org.mx/SieAPIRest/service/v1/series/{BANXICO_SERIE_INPC}/datos"
        r = requests.get(url, headers={"Bmx-Token": BANXICO_TOKEN}, timeout=10)
        datos = r.json()["bmx"]["series"][0]["datos"]
        serie = [(d["fecha"], float(str(d["dato"]).replace(",", ""))) for d in datos]
        return serie[-13:]
    except Exception:
        return None


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def world_bank_inflation(wb_code: str):
    """Inflacion anual (precios al consumidor) mas reciente disponible, Banco Mundial."""
    if not wb_code:
        return None
    try:
        url = f"https://api.worldbank.org/v2/country/{wb_code}/indicator/FP.CPI.TOTL.ZG?format=json&per_page=10"
        r = requests.get(url, timeout=10)
        datos = r.json()[1]
        for d in datos:
            if d.get("value") is not None:
                return {"valor": float(d["value"]), "anio": d["date"]}
        return None
    except Exception:
        return None


def regresion_lineal_commodity(serie):
    """Regresion lineal simple sobre el historico de un commodity.

    serie: lista de (fecha_str, valor) ordenada cronologicamente.
    Devuelve un dict con el nivel actual, el promedio de 12 meses, la
    proyeccion a 3 meses y las variaciones porcentuales que alimentan la
    recomendacion de compra.
    """
    if not serie or len(serie) < 4:
        return None
    valores = np.array([v for _, v in serie], dtype=float)
    x = np.arange(len(valores))
    pendiente, intercepto = np.polyfit(x, valores, 1)
    proyeccion_x = len(valores) + 2  # ~3 meses adelante (0-based)
    proyeccion = pendiente * proyeccion_x + intercepto
    actual = float(valores[-1])
    promedio_12m = float(valores[-12:].mean()) if len(valores) >= 12 else float(valores.mean())
    tendencia_pct = ((proyeccion - actual) / actual * 100) if actual else 0.0
    nivel_pct = ((actual - promedio_12m) / promedio_12m * 100) if promedio_12m else 0.0
    return {
        "actual": actual,
        "promedio_12m": promedio_12m,
        "proyeccion_3m": float(proyeccion),
        "tendencia_pct": float(tendencia_pct),
        "nivel_pct": float(nivel_pct),
        "fechas": [f for f, _ in serie],
        "valores": valores.tolist(),
    }


def recomendacion_compra(analisis):
    """Recomendacion de compra en 3 sabores: comprar ahora / esperar / buscar
    alternativas, a partir de la regresion lineal del commodity."""
    if not analisis:
        return (
            "Sin datos suficientes",
            "Se necesitan por lo menos 4 meses de historico del commodity para estimar una tendencia.",
        )
    tendencia = analisis["tendencia_pct"]
    nivel = analisis["nivel_pct"]
    if nivel > 15:
        return (
            "Buscar alternativas / negociar",
            f"El precio actual esta {nivel:.1f}% por encima de su promedio de 12 meses; conviene "
            "negociar o explorar proveedores/commodities sustitutos antes de comprar.",
        )
    if tendencia > 5:
        return (
            "Comprar ahora",
            f"La proyeccion a 3 meses (regresion lineal sobre el historico) sugiere un alza de "
            f"{tendencia:.1f}%; conviene cerrar la compra antes de que suba mas.",
        )
    if tendencia < -5:
        return (
            "Esperar",
            f"La proyeccion a 3 meses sugiere una baja de {abs(tendencia):.1f}%; conviene esperar "
            "un poco si el cronograma del proyecto lo permite.",
        )
    return (
        "Proceder segun cronograma",
        "El precio se mantiene relativamente estable (sin tendencia fuerte ni nivel inusual); no "
        "hay una senal de mercado que justifique adelantar o atrasar la compra.",
    )


RIESGO_NIVEL_RANK = {"Bajo": 1, "Medio": 2, "Medio-Alto": 3, "Alto": 4}
RIESGO_NIVEL_STYLE = {
    "Bajo": ("#eaf3de", "#27500a", "\U0001F7E2"),
    "Medio": ("#faeeda", "#854f0b", "\U0001F7E1"),
    "Medio-Alto": ("#fbe4d5", "#7a3b12", "\U0001F7E1\U0001F534"),
    "Alto": ("#fcebeb", "#791f1f", "\U0001F534"),
}


def clasificar_riesgo_commodity(analisis) -> str:
    """Nivel de riesgo del commodity a partir de la regresion (nivel vs
    promedio 12m y tendencia proyectada). Mismos umbrales que
    recomendacion_compra, para que ambas lecturas sean consistentes."""
    if not analisis:
        return "Medio"
    nivel = abs(analisis["nivel_pct"])
    tendencia = abs(analisis["tendencia_pct"])
    if nivel > 20 or tendencia > 15:
        return "Alto"
    if nivel > 10 or tendencia > 8:
        return "Medio-Alto"
    if nivel > 3 or tendencia > 3:
        return "Medio"
    return "Bajo"


def clasificar_riesgo_inflacion(valor_pct) -> str:
    """Heuristica simple sobre inflacion anual (no es un estandar oficial,
    solo para dar una referencia visual consistente)."""
    if valor_pct is None:
        return "Medio"
    v = abs(valor_pct)
    if v > 6:
        return "Alto"
    if v > 4:
        return "Medio-Alto"
    if v > 2.5:
        return "Medio"
    return "Bajo"


def clasificar_riesgo_cambiario(hay_exposicion: bool, cobertura: bool = False) -> str:
    if not hay_exposicion:
        return "Bajo"
    return "Medio" if cobertura else "Alto"


def combinar_riesgo(niveles) -> str:
    """El riesgo combinado es el nivel mas alto entre los que se le pasen
    (no un promedio): una sola variable muy expuesta ya es motivo de
    atencion aunque las demas esten tranquilas."""
    niveles = [n for n in niveles if n]
    if not niveles:
        return "Medio"
    return max(niveles, key=lambda n: RIESGO_NIVEL_RANK.get(n, 2))


def badge_riesgo_html(nivel: str) -> str:
    bg, txt, emoji = RIESGO_NIVEL_STYLE.get(nivel, RIESGO_NIVEL_STYLE["Medio"])
    return (
        f"<span style='background:{bg};color:{txt};font-size:12px;font-weight:600;"
        f"padding:2px 10px;border-radius:6px;white-space:nowrap;'>{emoji} {nivel}</span>"
    )


# ---------------------------------------------------------------------------
# PARSER DE DESCRIPCION LIBRE (para "Nueva solicitud")
# ---------------------------------------------------------------------------
# Extrae de un texto libre (titulo + descripcion de la solicitud, con el
# formato que normalmente ya se comparte: proveedor, pais, monedas, monto,
# fechas, condiciones de pago) los datos estructurados que antes habia que
# capturar a mano en el Sheet. Si un dato no aparece en el texto, se deja
# vacio -no se inventa- igual que hace el resto de la app.


def parsear_descripcion_libre(texto: str) -> dict:
    t = str(texto or "")

    def buscar(patrones):
        for p in patrones:
            m = re.search(p, t, re.IGNORECASE)
            if m:
                return m.group(1).strip().rstrip(".").strip()
        return ""

    datos = {}
    datos["proveedor"] = buscar([
        r"proveedor:\s*([^\n]+)",
    ])
    datos["pais"] = buscar([
        r"pa[ií]s de fabricaci[oó]n:\s*([^\n\.]+)",
        r"pa[ií]s (?:del )?proveedor:\s*([^\n\.]+)",
        r"pa[ií]s:\s*([^\n\.]+)",
    ])
    datos["moneda_cotizacion"] = buscar([
        r"moneda de cotizaci[oó]n:\s*([A-Za-z]{3})",
        r"moneda cotizaci[oó]n:\s*([A-Za-z]{3})",
    ]).upper()
    datos["moneda_presupuesto"] = buscar([
        r"moneda presupuestal:\s*([A-Za-z]{3})",
        r"moneda (?:de )?presupuesto:\s*([A-Za-z]{3})",
    ]).upper()

    m_monto = re.search(r"monto\s*(?:cotizado)?:?\s*([\d,\.]+)\s*([A-Za-z]{3})", t, re.IGNORECASE)
    if m_monto:
        try:
            datos["monto"] = float(m_monto.group(1).replace(",", ""))
        except ValueError:
            datos["monto"] = None
        datos["moneda_monto"] = m_monto.group(2).upper()
    else:
        datos["monto"] = None
        datos["moneda_monto"] = ""

    datos["fecha_cotizacion"] = buscar([r"fecha de cotizaci[oó]n:\s*([^\n\.]+)"])
    datos["fecha_compra"] = buscar([r"compra estimada:\s*([^\n\.]+)"])
    datos["fecha_entrega"] = buscar([r"entrega requerida:\s*([^\n\.]+)"])
    datos["vigencia"] = buscar([r"vigencia hasta\s*([^\n\.]+)"])

    pagos = []
    for m in re.finditer(
        r"(\d{1,3})\s*%\s*(anticipo|al iniciar[^\n\.,]*|inicio[^\n\.,]*|contra entrega|entrega)",
        t,
        re.IGNORECASE,
    ):
        pagos.append({"pct": int(m.group(1)), "momento": m.group(2).strip()})
    datos["pagos"] = pagos

    datos["sin_cobertura"] = bool(re.search(r"no existe cobertura|sin cobertura", t, re.IGNORECASE))
    datos["con_cobertura"] = bool(
        re.search(r"\bcobertura\b", t, re.IGNORECASE)
    ) and not datos["sin_cobertura"]

    return datos


def render_riesgo_mercado(row) -> None:
    """Modulo de riesgos de mercado (FX, inflacion, commodity, mano de obra),
    con recomendacion automatica. Se muestra en el roadmap justo antes del
    paso 5 (Cotizaciones)."""

    st.markdown(
        "<p style='font-weight:600;font-size:14px;margin:10px 0 2px;'>"
        "&#128225; Riesgos de mercado antes de cotizar: commodities, tipo de cambio e inflacion</p>"
        "<p style='font-size:11.5px;color:#9a988f;margin:0 0 10px;line-height:1.4;'>"
        "Insight automatico previo al paso 5: commodity del proyecto, tipo de cambio, inflacion "
        "y mano de obra del pais del proveedor.</p>"
        f"<a href='{COMMODITY_AGENT_URL}' target='_blank' "
        "style='font-size:13px;text-decoration:none;'>Abrir Agente CAPEX Market &amp; Risk Intelligence &#8599;</a>",
        unsafe_allow_html=True,
    )

    pais_proveedor = str(row.get("País Proveedor", "") or row.get("Pais Proveedor", "")).strip()
    commodity_sheet = str(row.get("Commodity Relacionado", "")).strip()
    moneda_cotizacion = str(row.get("Moneda Cotización", "") or row.get("Moneda Cotizacion", "")).strip()
    descripcion_extra = str(row.get("Descripción", "") or row.get("Descripcion", ""))

    if commodity_sheet and commodity_sheet not in ("Otro / No aplica", "Otro"):
        commodities = [(commodity_sheet, "Alta")]
        commodity_auto = False
    else:
        texto_deteccion = f"{row.get('Nombre del Proyecto', '')} {descripcion_extra}"
        commodities, commodity_auto = detectar_commodities(texto_deteccion)

    commodity = commodities[0][0]  # el de mayor relevancia es el que se grafica a detalle

    st.markdown(
        "<div style='background:#fbfaf7;border:1px solid #eeece3;border-radius:10px;"
        "padding:14px 18px 6px;margin-bottom:10px;'>",
        unsafe_allow_html=True,
    )

    if len(commodities) > 1:
        etiquetas = ", ".join(f"{c} ({r})" for c, r in commodities)
        st.markdown(
            f"**Commodities relevantes**{' (auto)' if commodity_auto else ''}<br>{etiquetas}",
            unsafe_allow_html=True,
        )
        c2, c3 = st.columns(2)
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            etiqueta_commodity = commodity + (" (auto)" if commodity_auto else "")
            st.markdown(f"**Commodity**<br>{etiqueta_commodity}", unsafe_allow_html=True)
    with c2:
        st.markdown(f"**Pais proveedor**<br>{pais_proveedor or 'No especificado'}", unsafe_allow_html=True)
    with c3:
        st.markdown(f"**Moneda cotizacion**<br>{moneda_cotizacion or 'No especificada'}", unsafe_allow_html=True)

    if not pais_proveedor:
        st.caption(
            "Completa 'País Proveedor', 'Commodity Relacionado' y 'Moneda Cotización' en el "
            "Google Sheet para un analisis mas preciso de este proyecto."
        )

    info_pais = COUNTRY_INFO.get(pais_proveedor)

    # Estas 3 variables alimentan el "Riesgo global (automatico)" del final de
    # este modulo: se van llenando con datos reales conforme se calculan las
    # secciones de abajo (tipo de cambio / inflacion / commodity).
    riesgo_cambiario_calc = clasificar_riesgo_cambiario(bool(pais_proveedor) and pais_proveedor != "México")
    riesgo_inflacion_calc = "Medio"
    riesgo_commodity_calc = "Medio"

    # --- Tipo de cambio -----------------------------------------------------
    st.markdown("**Tipo de cambio**")
    if pais_proveedor == "México":
        st.caption("Proveedor nacional (Mexico) — sin riesgo cambiario directo en la compra.")
    elif info_pais:
        moneda_prov = info_pais["moneda"]
        if moneda_prov == "USD":
            # Proveedor ya cotiza en USD: el unico tramo relevante hacia el
            # presupuesto (asumido en MXN) es USD/MXN, no hace falta (ni
            # tiene sentido) mostrar USD/USD.
            fx_usd_mxn = av_fx_rate("USD", "MXN")
            if fx_usd_mxn:
                st.metric("USD/MXN", f"{fx_usd_mxn['rate']:.4f}")
            else:
                st.caption("No se pudo obtener USD/MXN (limite de API o dato no disponible).")
        else:
            fx_prov_usd = av_fx_rate(moneda_prov, "USD")
            fx_usd_mxn = av_fx_rate("USD", "MXN")
            fcol1, fcol2 = st.columns(2)
            with fcol1:
                if fx_prov_usd:
                    st.metric(f"{moneda_prov}/USD", f"{fx_prov_usd['rate']:.4f}")
                else:
                    st.caption(f"No se pudo obtener {moneda_prov}/USD (limite de API o dato no disponible).")
            with fcol2:
                if fx_usd_mxn:
                    st.metric("USD/MXN", f"{fx_usd_mxn['rate']:.4f}")
                else:
                    st.caption("No se pudo obtener USD/MXN (limite de API o dato no disponible).")
    else:
        st.caption("Especifica el pais del proveedor para calcular el tipo de cambio relevante.")

    # --- Inflacion ------------------------------------------------------------
    st.markdown("**Inflacion**")
    if pais_proveedor == "México":
        serie_inpc = banxico_inpc_series()
        if serie_inpc and len(serie_inpc) >= 13:
            inflacion_yoy = (serie_inpc[-1][1] / serie_inpc[0][1] - 1) * 100
            st.metric("Inflacion Mexico (INPC, interanual)", f"{inflacion_yoy:.1f}%")
            st.caption("Fuente: Banxico SIE.")
            riesgo_inflacion_calc = clasificar_riesgo_inflacion(inflacion_yoy)
        else:
            wb = world_bank_inflation("MEX")
            if wb:
                st.metric(f"Inflacion Mexico ({wb['anio']})", f"{wb['valor']:.1f}%")
                st.caption(
                    "Fuente: Banco Mundial (agrega tu token de Banxico en Secrets como "
                    "BANXICO_TOKEN para el dato interanual mas reciente)."
                )
                riesgo_inflacion_calc = clasificar_riesgo_inflacion(wb["valor"])
            else:
                st.caption("No se pudo obtener la inflacion de Mexico en este momento.")
    elif info_pais:
        wb = world_bank_inflation(info_pais["wb_code"])
        if wb:
            st.metric(f"Inflacion {pais_proveedor} ({wb['anio']})", f"{wb['valor']:.1f}%")
            st.caption("Fuente: Banco Mundial.")
            riesgo_inflacion_calc = clasificar_riesgo_inflacion(wb["valor"])
        else:
            st.caption(f"No se pudo obtener la inflacion de {pais_proveedor} en este momento.")
    else:
        st.caption("Especifica el pais del proveedor para ver su inflacion.")

    # --- Commodity: historico, proyeccion y recomendacion --------------------
    # Se muestra el detalle (grafica + regresion) del commodity de mayor
    # relevancia que SI tenga indice directo en Alpha Vantage. Los demas
    # commodities detectados (ej. Acero, sin fuente gratuita directa) se
    # listan como referencia, sin inventarles un precio.
    st.markdown("**Commodity — historico, proyeccion y recomendacion**")

    con_dato = [c for c, _r in commodities if c in COMMODITY_AV_FUNCTION]
    sin_dato = [c for c, _r in commodities if c not in COMMODITY_AV_FUNCTION]

    if sin_dato:
        st.caption(
            f"Sin indice de materia prima directo y gratuito para: {', '.join(sin_dato)}. "
            "Se muestra como driver relevante pero sin precio en vivo."
        )

    analisis_principal = None
    for commodity_actual in con_dato[:2]:  # maximo 2 para cuidar el limite diario de la API
        serie_commodity = av_commodity_series(commodity_actual)
        analisis = regresion_lineal_commodity(serie_commodity) if serie_commodity else None
        if commodity_actual == commodity:
            analisis_principal = analisis

        if len(con_dato) > 1:
            st.markdown(f"_{commodity_actual}_")

        if analisis:
            chart_df = pd.DataFrame(
                {"Precio": analisis["valores"]},
                index=pd.to_datetime(analisis["fechas"]),
            )
            st.line_chart(chart_df, height=160)

            mcol1, mcol2, mcol3 = st.columns(3)
            mcol1.metric("Precio actual", f"{analisis['actual']:.2f}")
            mcol2.metric("Promedio 12m", f"{analisis['promedio_12m']:.2f}")
            mcol3.metric(
                "Proyeccion 3m (regresion lineal)",
                f"{analisis['proyeccion_3m']:.2f}",
                f"{analisis['tendencia_pct']:+.1f}%",
            )

            veredicto, motivo = recomendacion_compra(analisis)
            color_map = {
                "Comprar ahora": ("#eaf3de", "#27500a"),
                "Esperar": ("#faeeda", "#854f0b"),
                "Buscar alternativas / negociar": ("#fcebeb", "#791f1f"),
                "Proceder segun cronograma": ("#f1efe8", "#5f5e5a"),
            }
            bg, txt = color_map.get(veredicto, ("#f1efe8", "#5f5e5a"))
            st.markdown(
                f"<div style='background:{bg};color:{txt};border-radius:8px;padding:10px 14px;"
                f"margin:8px 0;font-size:13px;'><strong>{veredicto}</strong><br>{motivo}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption(
                f"No se pudo obtener el historico de {commodity_actual} en este momento (limite "
                "diario de la API gratuita o dato no disponible)."
            )

    if not con_dato:
        st.caption(
            "Ninguno de los commodities detectados tiene un indice directo gratuito disponible."
        )

    if analisis_principal:
        riesgo_commodity_calc = clasificar_riesgo_commodity(analisis_principal)

    # --- Mano de obra ----------------------------------------------------------
    st.markdown("**Referencia de mano de obra (proveedor)**")
    ref_mano_obra = LABOR_COST_REF.get(pais_proveedor)
    if ref_mano_obra:
        st.caption(f"{pais_proveedor}: {ref_mano_obra} (referencia orientativa, no en tiempo real).")
    else:
        st.caption("Sin referencia de mano de obra para este pais (indicador orientativo, no en tiempo real).")

    # --- Riesgo global (automatico) + guardar el check solo ------------------
    # Todo lo de aqui es 100% calculado por la app (nada de juicio humano), asi
    # que el check "E4 Riesgo global calculado" se puede marcar solo con un
    # clic en vez de tener que ir a marcarlo a mano en el Sheet.
    riesgo_total_calc = combinar_riesgo([riesgo_commodity_calc, riesgo_inflacion_calc, riesgo_cambiario_calc])
    st.markdown("**Riesgo global (automático)**")
    st.markdown(badge_riesgo_html(riesgo_total_calc), unsafe_allow_html=True)

    id_proyecto_actual = str(row.get("ID Proyecto", "")).strip()
    if not APPS_SCRIPT_URL:
        st.caption(
            "Para que este check se marque solo en el Sheet, configura APPS_SCRIPT_URL y "
            "APPS_SCRIPT_TOKEN en Secrets (ver apps_script_capex.gs)."
        )
    elif id_proyecto_actual:
        if st.button(
            "Marcar 'Riesgo global calculado' y guardar en el Sheet",
            key=f"guardar_riesgo_{id_proyecto_actual}",
        ):
            # El dropdown de "Riesgo" en el Sheet solo acepta Alto/Medio/Bajo;
            # Medio-Alto se sube a Alto para no romper esa validacion.
            riesgo_dropdown = "Alto" if riesgo_total_calc in ("Alto", "Medio-Alto") else riesgo_total_calc
            ok_check, msg_check = marcar_check_sheet(id_proyecto_actual, "E4 Riesgo global calculado", True)
            if ok_check:
                actualizar_campo_sheet(id_proyecto_actual, "Riesgo", riesgo_dropdown)
                st.success(
                    "Guardado: el check 'Riesgo global calculado' ya quedó marcado en el Sheet "
                    f"(riesgo {riesgo_dropdown.lower()})."
                )
                st.cache_data.clear()
            else:
                st.error(f"No se pudo guardar en el Sheet: {msg_check}")

    st.markdown("</div>", unsafe_allow_html=True)


def resolver_pais_info(pais_texto: str):
    """Empareja un pais escrito en texto libre (ej. 'Alemania') contra
    COUNTRY_INFO sin importar mayusculas/acentos. Regresa (nombre_normalizado,
    info_o_None)."""
    if not pais_texto:
        return "", None
    pais_norm = _normaliza_busqueda(pais_texto)
    for nombre, info in COUNTRY_INFO.items():
        if _normaliza_busqueda(nombre) in pais_norm or pais_norm in _normaliza_busqueda(nombre):
            return nombre, info
    return pais_texto, None


def _campo_html(label: str, valor: str) -> str:
    return (
        "<div style='margin-bottom:8px;'>"
        f"<div style='font-size:11px;color:#9a988f;text-transform:uppercase;letter-spacing:.02em;'>{label}</div>"
        f"<div style='font-size:13.5px;color:#1a1a17;'>{valor or 'No especificado'}</div>"
        "</div>"
    )


def render_reporte_nueva_solicitud(titulo: str, descripcion: str) -> None:
    """Version 'app' del reporte de riesgo de mercado que antes se le pedia a
    un agente de Copilot: mismo formato (Identificacion / Drivers / Commodity
    / Inflacion / Tipo de cambio / Riesgo economico / Impacto / Insight /
    Recomendaciones / Resumen ejecutivo / Decision sugerida), pero con datos
    reales de Alpha Vantage, Banxico y Banco Mundial en vez de que un modelo
    de lenguaje adivine cifras que no puede verificar. Todo lo que no se
    encuentra en el texto se marca como 'No especificado', nunca se inventa."""

    texto_completo = f"{titulo}\n{descripcion}"
    datos = parsear_descripcion_libre(descripcion)
    commodities, es_generico = detectar_commodities(texto_completo)
    commodity_principal = commodities[0][0]

    pais_texto = datos["pais"]
    pais_norm, info_pais = resolver_pais_info(pais_texto)
    moneda_cot = datos["moneda_cotizacion"] or datos["moneda_monto"]
    moneda_presup = datos["moneda_presupuesto"]
    monto = datos["monto"]
    moneda_monto = datos["moneda_monto"] or moneda_cot

    # --- Identificacion -----------------------------------------------------
    st.markdown("#### Identificación")
    ic1, ic2, ic3, ic4 = st.columns(4)
    with ic1:
        st.markdown(_campo_html("Proyecto", titulo), unsafe_allow_html=True)
        st.markdown(_campo_html("Proveedor", datos["proveedor"]), unsafe_allow_html=True)
    with ic2:
        st.markdown(_campo_html("País", pais_texto), unsafe_allow_html=True)
        st.markdown(
            _campo_html("Monto", f"{monto:,.0f} {moneda_monto}" if monto else ""),
            unsafe_allow_html=True,
        )
    with ic3:
        st.markdown(_campo_html("Moneda cotización", moneda_cot), unsafe_allow_html=True)
        st.markdown(_campo_html("Moneda presupuesto", moneda_presup), unsafe_allow_html=True)
    with ic4:
        st.markdown(_campo_html("Compra estimada", datos["fecha_compra"]), unsafe_allow_html=True)
        st.markdown(_campo_html("Entrega requerida", datos["fecha_entrega"]), unsafe_allow_html=True)

    # --- Drivers / commodities -----------------------------------------------
    st.markdown("#### Drivers de costo")
    filas_drivers = ""
    for c, relevancia in commodities:
        tiene_dato = "con dato en vivo" if c in COMMODITY_AV_FUNCTION else "sin indice directo gratuito"
        filas_drivers += (
            "<tr>"
            f"<td style='padding:4px 10px;font-size:13px;'>{c}</td>"
            f"<td style='padding:4px 10px;'>{badge_riesgo_html('Alto' if relevancia == 'Alta' else ('Medio' if relevancia == 'Media' else 'Bajo'))}</td>"
            f"<td style='padding:4px 10px;font-size:12.5px;color:#5f5e5a;'>Detectado en la descripción ({tiene_dato}).</td>"
            "</tr>"
        )
    st.markdown(
        "<table style='width:100%;border-collapse:collapse;'>"
        "<tr style='color:#9a988f;font-size:11px;text-transform:uppercase;'>"
        "<td style='padding:4px 10px;'>Commodity</td><td style='padding:4px 10px;'>Relevancia</td>"
        "<td style='padding:4px 10px;'>Justificación</td></tr>" + filas_drivers + "</table>",
        unsafe_allow_html=True,
    )
    if es_generico:
        st.caption("No se detectaron palabras clave especificas; se uso Cobre como referencia generica.")

    # --- Commodity: historico + regresion -------------------------------------
    st.markdown("#### Commodity")
    con_dato = [c for c, _r in commodities if c in COMMODITY_AV_FUNCTION]
    analisis_principal = None
    riesgo_commodity = "Medio"
    for c in con_dato[:2]:
        serie = av_commodity_series(c)
        analisis = regresion_lineal_commodity(serie) if serie else None
        if c == commodity_principal:
            analisis_principal = analisis
            riesgo_commodity = clasificar_riesgo_commodity(analisis) if analisis else "Medio"
        if len(con_dato) > 1:
            st.markdown(f"_{c}_")
        if analisis:
            chart_df = pd.DataFrame({"Precio": analisis["valores"]}, index=pd.to_datetime(analisis["fechas"]))
            st.line_chart(chart_df, height=150)
            mcol1, mcol2, mcol3 = st.columns(3)
            mcol1.metric("Precio actual", f"{analisis['actual']:.2f}")
            mcol2.metric("Promedio 12m", f"{analisis['promedio_12m']:.2f}")
            mcol3.metric("Proyección 3m", f"{analisis['proyeccion_3m']:.2f}", f"{analisis['tendencia_pct']:+.1f}%")
        else:
            st.caption(f"No se pudo obtener el histórico de {c} en este momento.")
    if not con_dato:
        st.caption("Ninguno de los commodities detectados tiene índice directo gratuito disponible.")
    st.markdown(f"Riesgo commodity: {badge_riesgo_html(riesgo_commodity)}", unsafe_allow_html=True)

    # --- Inflacion --------------------------------------------------------------
    st.markdown("#### Inflación")
    wb_mexico = world_bank_inflation("MEX")
    icol1, icol2 = st.columns(2)
    with icol1:
        if wb_mexico:
            st.metric(f"México ({wb_mexico['anio']})", f"{wb_mexico['valor']:.2f}%")
        else:
            st.caption("Inflación México no disponible en este momento.")
    riesgo_inflacion = clasificar_riesgo_inflacion(wb_mexico["valor"] if wb_mexico else None)
    if pais_norm and pais_norm != "México" and info_pais:
        wb_pais = world_bank_inflation(info_pais["wb_code"])
        with icol2:
            if wb_pais:
                st.metric(f"{pais_norm} ({wb_pais['anio']})", f"{wb_pais['valor']:.2f}%")
            else:
                st.caption(f"Inflación {pais_norm} no disponible en este momento.")
        if wb_pais:
            riesgo_inflacion = combinar_riesgo([riesgo_inflacion, clasificar_riesgo_inflacion(wb_pais["valor"])])
    elif pais_texto:
        with icol2:
            st.caption(f"'{pais_texto}' no esta en el catalogo de paises configurado; agregalo a COUNTRY_INFO para inflacion automatica.")
    st.markdown(f"Riesgo inflación: {badge_riesgo_html(riesgo_inflacion)}", unsafe_allow_html=True)

    # --- Tipo de cambio -----------------------------------------------------
    st.markdown("#### Tipo de cambio")
    hay_exposicion = bool(moneda_cot and moneda_presup and moneda_cot != moneda_presup)
    fx = av_fx_rate(moneda_cot, moneda_presup) if hay_exposicion else None
    if not moneda_cot or not moneda_presup:
        st.caption("Falta moneda de cotización o moneda de presupuesto en la descripción para calcular exposición.")
        riesgo_cambiario = "Medio"
    elif not hay_exposicion:
        st.caption(f"Cotización y presupuesto en la misma moneda ({moneda_cot}) — sin riesgo cambiario directo.")
        riesgo_cambiario = "Bajo"
    else:
        riesgo_cambiario = clasificar_riesgo_cambiario(True, datos["con_cobertura"])
        fcol1, fcol2 = st.columns(2)
        with fcol1:
            if fx:
                st.metric(f"{moneda_cot}/{moneda_presup}", f"{fx['rate']:.4f}")
            else:
                st.caption("No se pudo obtener el tipo de cambio en este momento.")
        with fcol2:
            if fx and monto:
                st.metric(f"Valor de referencia ({moneda_presup})", f"{monto * fx['rate']:,.0f}")
        if datos["pagos"]:
            cal = " · ".join(f"{p['pct']}% {p['momento']}" for p in datos["pagos"])
            st.caption(f"Calendario de exposición: {cal}.")
        st.caption(
            "Con cobertura cambiaria mencionada en la descripción." if datos["con_cobertura"]
            else "Sin cobertura cambiaria — la exposición queda abierta hasta cada pago."
        )
    st.markdown(f"Riesgo cambiario: {badge_riesgo_html(riesgo_cambiario)}", unsafe_allow_html=True)

    # --- Riesgo economico -----------------------------------------------------
    st.markdown("#### Riesgo económico")
    riesgo_mercado = combinar_riesgo([riesgo_commodity, riesgo_inflacion, riesgo_cambiario])
    riesgo_real = riesgo_mercado
    if datos["con_cobertura"] and RIESGO_NIVEL_RANK.get(riesgo_real, 2) > 1:
        niveles_orden = ["Bajo", "Medio", "Medio-Alto", "Alto"]
        riesgo_real = niveles_orden[niveles_orden.index(riesgo_real) - 1]
    riesgo_total = combinar_riesgo([riesgo_mercado, riesgo_real])
    rcol1, rcol2, rcol3 = st.columns(3)
    rcol1.markdown(f"Riesgo de mercado<br>{badge_riesgo_html(riesgo_mercado)}", unsafe_allow_html=True)
    rcol2.markdown(f"Riesgo real<br>{badge_riesgo_html(riesgo_real)}", unsafe_allow_html=True)
    rcol3.markdown(f"Riesgo total<br>{badge_riesgo_html(riesgo_total)}", unsafe_allow_html=True)

    # --- Impacto --------------------------------------------------------------
    st.markdown("#### Impacto potencial")
    if fx and monto:
        st.caption(
            f"Valor de referencia hoy: {monto * fx['rate']:,.0f} {moneda_presup}. El monto final "
            "depende de la variacion del tipo de cambio y del commodity antes de cada pago; no se "
            "calcula un impacto exacto sin una formula de ajuste o cobertura definida en el contrato."
        )
    else:
        st.caption("Pendiente de calcular: faltan datos de monto y/o tipo de cambio verificables.")

    # --- Insight ----------------------------------------------------------------
    st.markdown("#### Insight")
    riesgos_dict = {"Commodity": riesgo_commodity, "Inflación": riesgo_inflacion, "Tipo de cambio": riesgo_cambiario}
    factor_principal = max(riesgos_dict, key=lambda k: RIESGO_NIVEL_RANK.get(riesgos_dict[k], 2))
    st.markdown(
        f"El factor de mayor riesgo para esta compra es **{factor_principal.lower()}** "
        f"({badge_riesgo_html(riesgos_dict[factor_principal])}). Commodity principal: {commodity_principal}. "
        + ("No hay cobertura cambiaria mencionada, así que el presupuesto queda expuesto hasta el último pago. "
           if hay_exposicion and not datos["con_cobertura"] else "")
        + "Compras debe vigilar esta variable antes de emitir la orden.",
        unsafe_allow_html=True,
    )

    # --- Recomendaciones ----------------------------------------------------
    st.markdown("#### Recomendaciones")
    recs = []
    if riesgo_cambiario in ("Alto", "Medio-Alto") and not datos["con_cobertura"]:
        recs.append("Evaluar cobertura cambiaria antes de emitir la orden de compra.")
    if riesgo_commodity in ("Alto", "Medio-Alto"):
        recs.append(f"Negociar precio fijo o tope máximo de ajuste por {commodity_principal.lower()} y otras materias primas.")
    if datos["vigencia"] and datos["fecha_compra"]:
        recs.append("Confirmar que la vigencia de la cotización cubra la fecha de compra estimada; si no, negociar extensión.")
    if datos["pagos"]:
        recs.append("Dar seguimiento mensual al tipo de cambio hasta el último pago programado.")
    if not recs:
        recs.append("Sin señales de riesgo relevante; proceder según cronograma normal.")
    st.markdown("<br>".join(f"• {r}" for r in recs), unsafe_allow_html=True)

    # --- Decision sugerida ------------------------------------------------------
    st.markdown("#### Decisión sugerida")
    if not pais_texto and not moneda_cot:
        decision = "Requiere más información"
    elif riesgo_cambiario in ("Alto",) and not datos["con_cobertura"]:
        decision = "Solicitar cobertura"
    elif riesgo_total in ("Alto", "Medio-Alto"):
        decision = "Negociar y monitorear"
    elif analisis_principal and analisis_principal["tendencia_pct"] > 5:
        decision = "Comprar ahora"
    elif analisis_principal and analisis_principal["tendencia_pct"] < -5:
        decision = "Esperar"
    else:
        decision = "Negociar y monitorear"
    st.markdown(
        f"<div style='background:#f1efe8;border-radius:8px;padding:10px 14px;font-size:13.5px;'>"
        f"<strong>{decision}</strong></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Fuentes: Alpha Vantage (commodities/tipo de cambio, vía IMF/FRED), Banco Mundial "
        "(inflación), Banxico SIE (inflación México si hay token configurado)."
    )
    st.markdown(
        f"<a href='{COMMODITY_AGENT_URL}' target='_blank' "
        "style='font-size:13px;text-decoration:none;'>Abrir Agente CAPEX Market &amp; Risk Intelligence &#8599;</a>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# CARGA DE DATOS
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def load_data():
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
        if df.empty or "ID Proyecto" not in df.columns:
            raise ValueError("Sheet vacio o con columnas inesperadas")
        fuente = "sheet"
    except Exception:
        df = pd.read_csv("sample_expediente.csv")
        fuente = "demo"
    df = df.fillna("")
    # El Sheet tiene filas extra en blanco (reservadas para los desplegables
    # de Pais Proveedor / Commodity / Moneda); se descartan aqui para que no
    # cuenten como proyectos fantasma en el dashboard.
    df["ID Proyecto"] = df["ID Proyecto"].astype(str).str.strip()
    df = df[df["ID Proyecto"] != ""].reset_index(drop=True)
    return df, fuente, datetime.now()


def formatea_hace(momento: datetime) -> str:
    segundos = max(0, int((datetime.now() - momento).total_seconds()))
    if segundos < 5:
        return "hace instantes"
    if segundos < 60:
        return f"hace {segundos} s"
    minutos = segundos // 60
    if minutos < 60:
        return f"hace {minutos} min"
    horas = minutos // 60
    return f"hace {horas} h"


def parse_bool(v) -> bool:
    """Interpreta el valor de una casilla del Sheet (TRUE/FALSE, VERDADERO/FALSO,
    booleano real, etc.) como True/False."""
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in ("TRUE", "VERDADERO", "1", "SI", "SÍ", "YES")


def check_label(col_name: str, n: int) -> str:
    prefix = f"E{n} "
    return col_name[len(prefix):] if col_name.startswith(prefix) else col_name


def etapa_checks(row, n: int):
    """Lista de (etiqueta, marcado) para los 3 checks de una etapa."""
    return [(check_label(c, n), parse_bool(row.get(c, ""))) for c in ETAPA_CHECKS[n]]


def etapa_status(row, n: int) -> str:
    marcados = sum(1 for _, ok in etapa_checks(row, n) if ok)
    if marcados == len(ETAPA_CHECKS[n]):
        return "Completo"
    if marcados == 0:
        return "Pendiente"
    return "En proceso"


def etapas_completas(row) -> int:
    return sum(1 for n in range(1, 7) if etapa_status(row, n) == "Completo")


def avance_pct(row) -> float:
    """Porcentaje de los 18 checks totales que estan marcados (0.0 a 1.0)."""
    total = sum(1 for n in range(1, 7) for _ in ETAPA_CHECKS[n])
    marcados = sum(1 for n in range(1, 7) for _, ok in etapa_checks(row, n) if ok)
    return marcados / total if total else 0


def etapa_actual(row) -> str:
    """Nombre de la primera etapa que no esta Completo (o 'Cerrado' si todas lo estan)."""
    for n in range(1, 7):
        if etapa_status(row, n) != "Completo":
            return f"{n}. {ETAPA_NOMBRES[n]}"
    return "Cerrado"


def dias_sin_actualizar(row):
    """Dias desde 'Ultima Actualizacion'. None si el campo esta vacio o no se puede leer."""
    val = str(row.get("Última Actualización", "")).strip()
    if not val:
        return None
    try:
        fecha = datetime.strptime(val[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (date.today() - fecha).days


def sin_movimiento(row) -> bool:
    if etapa_actual(row) == "Cerrado":
        return False
    dias = dias_sin_actualizar(row)
    return dias is not None and dias > DIAS_SIN_MOVIMIENTO_ALERTA


def riesgo_display(riesgo: str) -> str:
    if not riesgo:
        return ""
    return f"{RIESGO_EMOJI.get(riesgo, '')} {riesgo}".strip()



# ---------------------------------------------------------------------------
# IMPORTACION DE REQUISICIONES / OR
# ---------------------------------------------------------------------------

REQ_COLUMN_MAP = {
    "NO_REQ": "ID Proyecto",
    "Responsable": "Responsable",
    "Comentarios": "Próxima Acción",
    "Proveedor": "Proveedor inicial",
    "Fecha": "Última Actualización",
    "Dias Sin Convertir": "Dias sin convertir",
    "USUARIO_REQ": "Solicitante",
    "Unidad de Negocio": "Unidad de Negocio",
    "TIPO_REQ": "Tipo requisición",
}

def normaliza_texto(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip()

def construir_nombre_proyecto(req_row) -> str:
    p1 = normaliza_texto(req_row.get("PDDSC1", ""))
    p2 = normaliza_texto(req_row.get("PDDSC2", ""))
    if p1 and p2:
        return f"{p1} - {p2}"
    return p1 or p2 or f"Requisición {normaliza_texto(req_row.get('NO_REQ', ''))}"

def crear_expediente_desde_req(req_row) -> dict:
    expediente = {}

    expediente["ID Proyecto"] = normaliza_texto(req_row.get("NO_REQ", ""))
    expediente["Nombre del Proyecto"] = construir_nombre_proyecto(req_row)
    expediente["Responsable"] = normaliza_texto(req_row.get("Responsable", ""))
    expediente["Riesgo"] = ""
    expediente["Ahorro Estimado"] = ""
    expediente["Próxima Acción"] = normaliza_texto(req_row.get("Comentarios", ""))

    fecha = normaliza_texto(req_row.get("Fecha", ""))
    if fecha:
        try:
            fecha = pd.to_datetime(fecha).strftime("%Y-%m-%d")
        except Exception:
            pass
    expediente["Última Actualización"] = fecha or date.today().strftime("%Y-%m-%d")

    # Campos extra útiles del Excel de requisiciones.
    expediente["Solicitante"] = normaliza_texto(req_row.get("USUARIO_REQ", ""))
    expediente["Proveedor inicial"] = normaliza_texto(req_row.get("Proveedor", ""))
    expediente["Dias sin convertir"] = normaliza_texto(req_row.get("Dias Sin Convertir", ""))
    expediente["Unidad de Negocio"] = normaliza_texto(req_row.get("Unidad de Negocio", ""))
    expediente["Tipo requisición"] = normaliza_texto(req_row.get("TIPO_REQ", ""))

    # Todas las etapas inician pendientes.
    for n in range(1, 7):
        for col in ETAPA_CHECKS[n]:
            expediente[col] = False
        expediente[ETAPA_NOTA_COL[n]] = ""

    return expediente

def render_importador_requisiciones(df_actual: pd.DataFrame) -> pd.DataFrame:
    st.subheader("Importar requisiciones / OR")
    st.caption(
        "Carga el Excel de seguimiento. La app solo lo lee; no modifica el archivo de tus jefes."
    )

    archivo_req = st.file_uploader(
        "Subir archivo de requisiciones",
        type=["xlsx", "xls"],
        key="archivo_requisiciones",
    )

    if archivo_req is None:
        return df_actual

    try:
        req_df = pd.read_excel(archivo_req, sheet_name="Export")
    except Exception as e:
        st.error(f"No se pudo leer la hoja 'Export': {e}")
        return df_actual

    if "NO_REQ" not in req_df.columns:
        st.error("No se encontró la columna NO_REQ en la hoja Export.")
        return df_actual

    req_df = req_df.fillna("")
    req_df["_OR"] = req_df["NO_REQ"].astype(str).str.strip()
    req_df["_Descripcion"] = req_df.apply(construir_nombre_proyecto, axis=1)

    existentes = set()
    if "ID Proyecto" in df_actual.columns:
        existentes = set(df_actual["ID Proyecto"].astype(str).str.strip())

    req_df["_Estado"] = req_df["_OR"].apply(
        lambda x: "Ya existe" if x in existentes and x else "Nueva"
    )

    # Posibles duplicados por descripción similar exacta, aunque cambie la OR.
    nombres_existentes = set()
    if "Nombre del Proyecto" in df_actual.columns:
        nombres_existentes = set(df_actual["Nombre del Proyecto"].astype(str).str.strip().str.lower())

    req_df.loc[
        (req_df["_Estado"] == "Nueva")
        & (req_df["_Descripcion"].astype(str).str.strip().str.lower().isin(nombres_existentes)),
        "_Estado",
    ] = "Posible duplicado"

    total = len(req_df)
    nuevas = int((req_df["_Estado"] == "Nueva").sum())
    ya_existen = int((req_df["_Estado"] == "Ya existe").sum())
    posibles = int((req_df["_Estado"] == "Posible duplicado").sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("OR encontradas", total)
    m2.metric("Nuevas", nuevas)
    m3.metric("Ya existen", ya_existen)
    m4.metric("Posibles duplicados", posibles)

    st.markdown("### Selección")

    filtro = st.radio(
        "Mostrar",
        ["Todas", "Solo nuevas", "Ya existen", "Posibles duplicados"],
        horizontal=True,
        key="filtro_importacion",
    )

    vista = req_df.copy()
    if filtro == "Solo nuevas":
        vista = vista[vista["_Estado"] == "Nueva"]
    elif filtro == "Ya existen":
        vista = vista[vista["_Estado"] == "Ya existe"]
    elif filtro == "Posibles duplicados":
        vista = vista[vista["_Estado"] == "Posible duplicado"]

    tabla = vista[["_OR", "_Descripcion", "Responsable", "Proveedor", "_Estado"]].copy()
    tabla.columns = ["OR", "Descripción", "Responsable", "Proveedor", "Estado"]

    evento = st.dataframe(
        tabla,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="multi-row",
        key="tabla_importacion_or",
    )

    seleccionadas = []
    try:
        seleccionadas = evento.selection.rows
    except Exception:
        seleccionadas = []

    st.caption(
        "Puedes seleccionar varias filas con clic. Para importar todas las nuevas, usa el botón de abajo."
    )

    incluir_repetidas = st.checkbox(
        "Permitir importar OR que ya existen o posibles duplicados",
        value=False,
        key="confirmar_duplicados",
        help="Actívalo solo si revisaste esas OR y realmente quieres volver a crearlas.",
    )

    seleccion_df = pd.DataFrame()
    if seleccionadas:
        seleccion_df = vista.iloc[seleccionadas].copy()

    col1, col2 = st.columns(2)

    with col1:
        importar_nuevas = st.button(
            "Preparar todas las nuevas",
            type="primary",
            use_container_width=True,
            key="preparar_todas_nuevas",
        )

    with col2:
        importar_seleccion = st.button(
            "Preparar seleccionadas",
            use_container_width=True,
            key="preparar_seleccionadas",
        )

    elegidas = None

    if importar_nuevas:
        elegidas = req_df[req_df["_Estado"] == "Nueva"].copy()

    elif importar_seleccion:
        if seleccion_df.empty:
            st.warning("Selecciona al menos una requisición.")
            return df_actual

        bloqueadas = seleccion_df[seleccion_df["_Estado"].isin(["Ya existe", "Posible duplicado"])]
        if not bloqueadas.empty and not incluir_repetidas:
            st.warning(
                "Tu selección incluye OR repetidas o posibles duplicados. "
                "Revísalas y activa la casilla de confirmación para incluirlas."
            )
            return df_actual

        elegidas = seleccion_df.copy()

    if elegidas is not None:
        expedientes = [crear_expediente_desde_req(r) for _, r in elegidas.iterrows()]

        # Guardamos varios expedientes temporalmente.
        st.session_state["expedientes_importados"] = expedientes

        # Exportar SOLO columnas que ya existen en el Google Sheet actual.
        cols_sheet = list(df_actual.columns)
        salida = pd.DataFrame(expedientes).reindex(columns=cols_sheet).fillna("")

        st.success(f"{len(expedientes)} expediente(s) preparado(s).")

        if APPS_SCRIPT_URL:
            icol1, icol2 = st.columns(2)
            with icol1:
                guardar_lote_directo = st.button(
                    f"Guardar {len(expedientes)} directo en el Sheet",
                    type="primary",
                    use_container_width=True,
                    key="guardar_lote_directo",
                )
            with icol2:
                st.download_button(
                    "Descargar CSV (respaldo)",
                    data=salida.to_csv(index=False).encode("utf-8-sig"),
                    file_name="expedientes_capex_importar.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="descargar_lote_importacion",
                )
            if guardar_lote_directo:
                exitos, fallos = 0, []
                for exp in expedientes:
                    ok, msg = agregar_fila_sheet(exp)
                    if ok:
                        exitos += 1
                    else:
                        fallos.append(f"{exp.get('ID Proyecto', '?')}: {msg}")
                if exitos:
                    st.success(f"{exitos} de {len(expedientes)} expediente(s) guardados directo en el Sheet.")
                    st.cache_data.clear()
                if fallos:
                    st.error("No se pudieron guardar: " + "; ".join(fallos))
        else:
            st.download_button(
                "Descargar CSV listo para pegar al Google Sheet",
                data=salida.to_csv(index=False).encode("utf-8-sig"),
                file_name="expedientes_capex_importar.csv",
                mime="text/csv",
                use_container_width=True,
                key="descargar_lote_importacion",
            )
            st.caption(
                "Este archivo ya sale con las mismas columnas y en el mismo orden que tu Google Sheet actual. "
                "Configura APPS_SCRIPT_URL en Secrets para guardar con un clic, sin CSV."
            )

    return df_actual


def render_nueva_solicitud(df_actual: pd.DataFrame) -> None:
    st.subheader("Nueva solicitud")
    st.caption(
        "Pega el título y la descripción de la solicitud (proveedor, país, monedas, monto, "
        "fechas, condiciones de pago si los tienes). La app detecta sola los commodities "
        "relevantes y arma el análisis de mercado con datos reales — no hace falta llenar "
        "país/moneda/commodity a mano ni pasarlo por un agente aparte."
    )

    col_id, col_tit = st.columns([1, 3])
    with col_id:
        id_proyecto = st.text_input("ID Proyecto", placeholder="CX-2026-...", key="nueva_sol_id")
    with col_tit:
        titulo = st.text_input("Título", placeholder="Compra de generador eléctrico industrial...", key="nueva_sol_titulo")

    descripcion = st.text_area(
        "Descripción",
        height=180,
        placeholder=(
            "Proveedor: ...\nPaís de fabricación: ...\nMoneda de cotización: ...\n"
            "Moneda presupuestal: ...\nMonto cotizado: ...\nFecha de cotización: ...\n"
            "Compra estimada: ...\nEntrega requerida: ...\nCondiciones de pago: ..."
        ),
        key="nueva_sol_descripcion",
    )

    if st.button("Analizar", type="primary", key="nueva_sol_analizar"):
        st.session_state["nueva_sol_analizada"] = True

    if not st.session_state.get("nueva_sol_analizada") or not (titulo or descripcion):
        return

    st.markdown("---")
    render_reporte_nueva_solicitud(titulo, descripcion)

    st.markdown("---")
    st.markdown("##### Guardar como expediente")
    st.caption(
        "Genera el renglón con país/moneda/commodity ya detectados, listo para pegar al Google "
        "Sheet (mismo mecanismo que 'Importar requisición') — así queda guardado como memoria "
        "del proyecto sin volver a capturarlo a mano."
    )

    datos = parsear_descripcion_libre(descripcion)
    commodities, _ = detectar_commodities(f"{titulo}\n{descripcion}")
    pais_norm, _ = resolver_pais_info(datos["pais"])

    expediente = {
        "ID Proyecto": id_proyecto or "",
        "Nombre del Proyecto": titulo,
        "Responsable": "",
        "Riesgo": "",
        "Ahorro Estimado": "",
        "Próxima Acción": "Confirmar viabilidad y alternativas (paso 1).",
        "Última Actualización": date.today().strftime("%Y-%m-%d"),
        "Descripción": descripcion,
        "País Proveedor": pais_norm or datos["pais"],
        "Commodity Relacionado": commodities[0][0] if commodities else "",
        "Moneda Cotización": datos["moneda_cotizacion"] or datos["moneda_monto"],
    }
    for n in range(1, 7):
        for col in ETAPA_CHECKS[n]:
            expediente[col] = False
        expediente[ETAPA_NOTA_COL[n]] = ""

    cols_sheet = list(dict.fromkeys(list(df_actual.columns) + list(expediente.keys())))
    salida = pd.DataFrame([expediente]).reindex(columns=cols_sheet).fillna("")

    if APPS_SCRIPT_URL:
        gcol1, gcol2 = st.columns(2)
        with gcol1:
            guardar_directo = st.button(
                "Guardar directo en el Sheet",
                type="primary",
                use_container_width=True,
                key="guardar_directo_nueva_solicitud",
                disabled=not id_proyecto,
                help=None if id_proyecto else "Captura un ID Proyecto para poder guardar.",
            )
        with gcol2:
            st.download_button(
                "Descargar CSV (respaldo)",
                data=salida.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"expediente_{id_proyecto or 'nuevo'}.csv",
                mime="text/csv",
                use_container_width=True,
                key="descargar_nueva_solicitud",
            )
        if guardar_directo:
            ok, msg = agregar_fila_sheet(expediente)
            if ok:
                st.success(
                    f"Guardado: '{id_proyecto}' ya quedó agregado al Sheet como fila nueva. "
                    "Aparecerá en Roadmap en cuanto refresques los datos."
                )
                st.cache_data.clear()
            else:
                st.error(f"No se pudo guardar directo en el Sheet: {msg}. Usa el CSV de respaldo mientras tanto.")
    else:
        st.download_button(
            "Descargar renglón para pegar al Google Sheet",
            data=salida.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"expediente_{id_proyecto or 'nuevo'}.csv",
            mime="text/csv",
            use_container_width=True,
            key="descargar_nueva_solicitud",
        )
        st.caption(
            "Para guardar con un clic (sin CSV), configura APPS_SCRIPT_URL y APPS_SCRIPT_TOKEN "
            "en Secrets (ver apps_script_capex.gs)."
        )
    if "Descripción" not in df_actual.columns:
        st.caption(
            "Nota: agrega la columna 'Descripción' al Google Sheet para que quede guardado el "
            "texto completo (hoy se pierde al pegar si esa columna no existe todavia)."
        )


def aplica_expediente_temporal(df_actual: pd.DataFrame) -> pd.DataFrame:
    expedientes = st.session_state.get("expedientes_importados")

    # Compatibilidad con la versión anterior de un solo expediente.
    if not expedientes:
        uno = st.session_state.get("expediente_importado")
        expedientes = [uno] if uno else []

    if not expedientes:
        return df_actual

    existentes = set()
    if "ID Proyecto" in df_actual.columns:
        existentes = set(df_actual["ID Proyecto"].astype(str).str.strip())

    nuevos = []
    for expediente in expedientes:
        if not expediente:
            continue
        idp = str(expediente.get("ID Proyecto", "")).strip()
        if idp and idp in existentes:
            continue
        nuevos.append(expediente)

    if not nuevos:
        return df_actual

    cols = list(dict.fromkeys(list(df_actual.columns) + [k for e in nuevos for k in e.keys()]))
    base = df_actual.reindex(columns=cols)
    nuevas = pd.DataFrame(nuevos).reindex(columns=cols).fillna("")
    return pd.concat([base, nuevas], ignore_index=True)

# ---------------------------------------------------------------------------
# UI HELPERS
# ---------------------------------------------------------------------------

BADGE_ICONS = {"check": "&#10003;", "clock": "&#9679;", "circle": ""}


def render_jotform_picker() -> str:
    cards = ""
    for f in JOTFORM_FORMS:
        cards += f"""
        <a href="{f['url']}" target="_blank" style="text-decoration:none;">
        <div style="border:1px solid #e4e2d8;border-radius:10px;padding:10px 12px;
            margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">
          <div>
            <p style="margin:0;font-size:13px;font-weight:600;color:#1a1a17;">{f['tipo']}</p>
            <p style="margin:0;font-size:12px;color:#5f5e5a;">{f['descripcion']}</p>
          </div>
          <span style="font-size:12px;color:#0a6650;white-space:nowrap;margin-left:12px;">Abrir &#8599;</span>
        </div>
        </a>
        """
    return cards


def render_checklist(checks) -> str:
    items = ""
    for label, ok in checks:
        if ok:
            mark = '<span style="color:#0a8a5f;font-weight:700;">&#10003;</span>'
            color = "#1a1a17"
        else:
            mark = '<span style="color:#c9c7bc;">&#9675;</span>'
            color = "#9a988f"
        items += (
            '<div style="display:flex;align-items:center;gap:7px;margin:3px 0;">'
            f'<span style="font-size:12px;width:14px;text-align:center;">{mark}</span>'
            f'<span style="font-size:12.5px;color:{color};">{label}</span>'
            "</div>"
        )
    return items


def render_step(row, n: int, is_last: bool) -> str:
    estatus = etapa_status(row, n)
    checks = etapa_checks(row, n)
    nota = row.get(ETAPA_NOTA_COL[n], "")

    colors = STATUS_COLORS.get(estatus, STATUS_COLORS["Pendiente"])
    nombre = ETAPA_NOMBRES[n]
    descripcion = ETAPA_DESCRIPCIONES.get(n, "")
    tool = TOOL_LINKS.get(n, {})
    dim = "color:#9a988f;" if estatus == "Pendiente" else ""

    icon_html = BADGE_ICONS.get(colors["icon"], "")
    circle = (
        f'<div style="width:28px;height:28px;border-radius:50%;'
        f'background:{colors["bg"]};display:flex;align-items:center;'
        f'justify-content:center;flex-shrink:0;color:{colors["text"]};'
        f'font-size:13px;font-weight:600;">{icon_html}</div>'
        if estatus != "Pendiente"
        else '<div style="width:28px;height:28px;border-radius:50%;'
        'border:1.5px solid #b4b2a9;flex-shrink:0;"></div>'
    )

    line = (
        '<div style="width:2px;flex:1;background:#d3d1c7;margin-top:4px;"></div>'
        if not is_last
        else ""
    )

    link_html = ""
    if n != 3 and tool.get("url") and estatus != "Pendiente":
        link_html = (
            f'<a href="{tool["url"]}" target="_blank" '
            f'style="font-size:13px;text-decoration:none;">{tool["label"]} &#8599;</a>'
        )
    elif n != 3 and tool.get("url"):
        link_html = (
            f'<a href="{tool["url"]}" target="_blank" '
            f'style="font-size:13px;text-decoration:none;color:#9a988f;">{tool["label"]} &#8599;</a>'
        )

    nota_html = (
        f'<p style="font-size:12.5px;color:#5f5e5a;margin:6px 0 2px;line-height:1.5;">{nota}</p>'
        if nota
        else ""
    )

    return (
        '<div style="display:flex;gap:14px;">'
        f'<div style="display:flex;flex-direction:column;align-items:center;width:28px;flex-shrink:0;">{circle}{line}</div>'
        '<div style="flex:1;padding-bottom:1.5rem;">'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:2px;">'
        f'<p style="font-weight:600;font-size:14px;margin:0;{dim}">{n}. {nombre}</p>'
        f'<span style="font-size:12px;color:{colors["text"]};">{estatus}</span>'
        '</div>'
        f'<p style="font-size:11.5px;color:#9a988f;margin:0 0 8px;line-height:1.4;">{descripcion}</p>'
        f'<div style="background:#fbfaf7;border:1px solid #eeece3;border-radius:8px;padding:8px 12px;margin-bottom:8px;">{render_checklist(checks)}{nota_html}</div>'
        f'{link_html}'
        '</div>'
        '</div>'
    )


def render_roadmap(row) -> None:
    riesgo = row.get("Riesgo", "")
    rbg, rtext = RIESGO_COLORS.get(riesgo, ("#f1efe8", "#5f5e5a"))
    ahorro = row.get("Ahorro Estimado", "")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(
            f"<p style='font-size:12px;color:#9a988f;margin:0;'>{row['ID Proyecto']}</p>"
            f"<p style='font-size:16px;font-weight:600;margin:0;'>{row['Nombre del Proyecto']}</p>",
            unsafe_allow_html=True,
        )
    with col2:
        badges = ""
        if riesgo:
            badges += (
                f"<span style='background:{rbg};color:{rtext};font-size:12px;font-weight:600;"
                f"padding:4px 12px;border-radius:8px;'>Riesgo {riesgo.lower()}</span>"
            )
        st.markdown(f"<div style='text-align:right;'>{badges}</div>", unsafe_allow_html=True)

    if sin_movimiento(row):
        dias = dias_sin_actualizar(row)
        st.markdown(
            f"<div style='background:#fcebeb;color:#791f1f;border-radius:8px;padding:8px 14px;"
            f"margin:8px 0;font-size:13px;'>&#9888; Sin movimiento hace {dias} dias — "
            f"conviene dar seguimiento.</div>",
            unsafe_allow_html=True,
        )

    pct = avance_pct(row)
    bcol1, bcol2 = st.columns([5, 1])
    with bcol1:
        st.progress(pct)
    with bcol2:
        st.markdown(
            f"<p style='font-size:13px;color:#5f5e5a;margin:0;text-align:right;'>"
            f"{etapas_completas(row)}/6 etapas &middot; {int(pct * 100)}%</p>",
            unsafe_allow_html=True,
        )

    proxima = row.get("Próxima Acción", "") or row.get("Proxima Accion", "")
    info_bits = []
    if proxima:
        info_bits.append(f"<span style='color:#5f5e5a;'>Proxima accion &mdash;</span> {proxima}")
    if ahorro:
        info_bits.append(f"<span style='color:#5f5e5a;'>Ahorro estimado &mdash;</span> {ahorro}")
    if info_bits:
        st.markdown(
            "<div style='background:#f1efe8;border-radius:12px;padding:14px 20px;"
            "margin:16px 0 24px;font-size:14px;'>" + "<br>".join(info_bits) + "</div>",
            unsafe_allow_html=True,
        )

    for n in range(1, 7):
        st.markdown(render_step(row, n, is_last=(n == 6)), unsafe_allow_html=True)
        if n == 3:
            with st.expander("Ver los 3 formularios de precalificacion", expanded=False):
                st.markdown(render_jotform_picker(), unsafe_allow_html=True)
        if n == 4:
            render_riesgo_mercado(row)


def render_resumen(df: pd.DataFrame) -> None:
    resumen = df.copy()
    resumen["% Avance"] = resumen.apply(avance_pct, axis=1)
    resumen["Etapa actual"] = resumen.apply(etapa_actual, axis=1)
    resumen["Etapas completas"] = resumen.apply(lambda r: f"{etapas_completas(r)}/6", axis=1)
    resumen["Sin movimiento"] = resumen.apply(sin_movimiento, axis=1)

    total = len(resumen)
    avance_prom = resumen["% Avance"].mean() if total else 0
    necesitan_atencion = int(sum(
        1 for _, r in resumen.iterrows()
        if r.get("Riesgo", "") == "Alto" or sin_movimiento(r)
    ))
    en_proceso = int(sum(
        1 for _, r in resumen.iterrows()
        if any(etapa_status(r, n) == "En proceso" for n in range(1, 7))
    ))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Proyectos", total)
    m2.metric("Avance promedio", f"{avance_prom * 100:.0f}%")
    m3.metric("En proceso activo", en_proceso)
    m4.metric("Necesitan atencion", necesitan_atencion, help="Riesgo alto o sin movimiento en mas de 5 dias")

    st.markdown("")

    fcol1, fcol2 = st.columns([2, 1])
    with fcol1:
        buscar = st.text_input(
            "Buscar", placeholder="Buscar por nombre, ID o responsable...",
            label_visibility="collapsed",
        )
    with fcol2:
        riesgos_disp = ["Todos"] + sorted(
            [r for r in resumen.get("Riesgo", pd.Series(dtype=str)).unique() if r]
        )
        riesgo_filtro = st.selectbox("Riesgo", riesgos_disp, label_visibility="collapsed")

    filtrado = resumen
    if buscar:
        mask = (
            filtrado["Nombre del Proyecto"].str.contains(buscar, case=False, na=False)
            | filtrado["ID Proyecto"].str.contains(buscar, case=False, na=False)
            | filtrado.get("Responsable", pd.Series(dtype=str)).str.contains(buscar, case=False, na=False)
        )
        filtrado = filtrado[mask]
    if riesgo_filtro != "Todos":
        filtrado = filtrado[filtrado.get("Riesgo", "") == riesgo_filtro]

    columnas = [
        "ID Proyecto", "Nombre del Proyecto", "Etapa actual", "Etapas completas", "% Avance",
        "Riesgo", "Ahorro Estimado", "Responsable", "Próxima Acción", "Última Actualización",
    ]
    columnas = [c for c in columnas if c in filtrado.columns]

    display_df = filtrado[columnas].copy()
    if "Riesgo" in display_df.columns:
        display_df["Riesgo"] = display_df["Riesgo"].apply(riesgo_display)
    if "Sin movimiento" in filtrado.columns:
        display_df.insert(3, "Alerta", filtrado["Sin movimiento"].apply(lambda s: "⚠ Sin mover" if s else "✅ Al dia"))

    evento = st.dataframe(
        display_df,
        column_config={
            "% Avance": st.column_config.ProgressColumn(
                "% Avance", min_value=0, max_value=1, format="%.0f%%",
            ),
        },
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="tabla_resumen",
    )

    filas_sel = []
    try:
        filas_sel = evento.selection.rows
    except Exception:
        filas_sel = []

    if filas_sel:
        idx_original = filtrado.index[filas_sel[0]]
        proyecto_sel = df.loc[idx_original]
        st.markdown("---")
        st.markdown(
            f"<p style='font-size:12px;color:#9a988f;margin:0 0 8px;'>DETALLE DEL PROYECTO SELECCIONADO</p>",
            unsafe_allow_html=True,
        )
        render_roadmap(proyecto_sel)
    else:
        st.caption("Haz clic en una fila de la tabla para ver el detalle completo del proyecto aqui mismo.")

    st.download_button(
        "Descargar como CSV",
        data=filtrado[columnas].to_csv(index=False).encode("utf-8"),
        file_name="expediente_capex_resumen.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Expediente Digital CAPEX", page_icon="\U0001F4C1", layout="centered")

hcol1, hcol2 = st.columns([4, 1])
with hcol1:
    st.markdown(
        "<h2 style='font-size:20px;font-weight:600;margin-bottom:0;'>Expediente digital CAPEX</h2>"
        "<p style='color:#5f5e5a;font-size:14px;margin-top:2px;'>Ragasa &mdash; Compras CAPEX</p>",
        unsafe_allow_html=True,
    )
with hcol2:
    if st.button("Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

df, fuente, cargado_en = load_data()
df = aplica_expediente_temporal(df)

if fuente == "sheet":
    st.markdown(
        f"<p style='font-size:12px;color:#5f5e5a;'>&#128260; Datos en vivo desde Google Sheets "
        f"(actualizados {formatea_hace(cargado_en)}) &mdash; "
        f"<a href='{GOOGLE_SHEET_EDIT_URL}' target='_blank'>ver/marcar checks en el expediente completo &#8599;</a></p>",
        unsafe_allow_html=True,
    )
else:
    st.warning(
        f"No se pudo leer el Google Sheet (revisa que siga compartido como 'Cualquiera con el "
        f"enlace'). Mostrando datos de ejemplo mientras tanto. "
        f"[Ver/editar el expediente]({GOOGLE_SHEET_EDIT_URL})"
    )

if df.empty:
    st.warning("No hay proyectos cargados todavia.")
    st.stop()

tab_resumen, tab_roadmap, tab_nueva, tab_importar = st.tabs(
    ["Resumen general", "Roadmap por proyecto", "Nueva solicitud", "Importar requisición"]
)

with tab_resumen:
    render_resumen(df)

with tab_roadmap:
    proyectos = df["ID Proyecto"] + " — " + df["Nombre del Proyecto"]
    seleccion = st.selectbox("Proyecto", proyectos, label_visibility="collapsed")
    idx = proyectos[proyectos == seleccion].index[0]
    row = df.loc[idx]
    render_roadmap(row)

with tab_nueva:
    render_nueva_solicitud(df)

with tab_importar:
    render_importador_requisiciones(df)

st.divider()
st.caption(
    "Cada etapa tiene 3 checks concretos; el estatus, el % de avance y las alertas de proyectos "
    "sin movimiento (mas de 5 dias sin actualizar) se calculan solos. Los datos vienen de la hoja "
    "'Expediente CAPEX - Ragasa (v2 checklist)' en Google Sheets y se refrescan cada minuto "
    "(o al instante con 'Actualizar datos'). Para actualizar un proyecto, marca/desmarca los "
    "checks directamente en esa hoja — en el Resumen general puedes hacer clic en cualquier fila "
    "para ver el detalle sin cambiar de pestaña. El bloque de riesgos de mercado (antes del paso "
    "5) usa Alpha Vantage para tipo de cambio y commodities, y Banxico/Banco Mundial para "
    "inflacion; son fuentes gratuitas con limites de uso, por lo que los datos se cachean por "
    "horas."
)
