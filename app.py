"""
Expediente Digital CAPEX - Ragasa
Tablero tipo "caminito": un roadmap por proyecto con las 6 etapas del proceso
de Compras CAPEX, su estatus real, y un enlace directo a la herramienta que
corresponde a cada etapa.

Como correrlo:
    pip install -r requirements.txt
    streamlit run app.py

Como conectarlo a tu Google Sheet real (en vez de los datos de ejemplo):
    Ver README.md - en resumen, agrega una hoja "Expediente" a tu Google
    Sheet de "Historicos internos", publicala como CSV, y pega esa URL en
    GOOGLE_SHEET_CSV_URL abajo.
"""

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# CONFIGURACION - edita esto con tus datos reales
# ---------------------------------------------------------------------------

# Pega aqui la URL de "Publicar en la web" (formato CSV) de la hoja
# "Expediente" de tu Google Sheet. Mientras esta vacio, la app usa el
# archivo sample_expediente.csv (datos de ejemplo) para que puedas probarla.
GOOGLE_SHEET_CSV_URL = ""

# Liga fija a cada herramienta, segun la etapa. Ajusta las que falten
# (Power BI, y si tienes mas de un formulario Jotform, el que corresponda).
TOOL_LINKS = {
    1: {"label": "Abrir chat Copilot", "url": "https://m365.cloud.microsoft/chat"},
    2: {"label": "Abrir chat Copilot", "url": "https://m365.cloud.microsoft/chat"},
    3: {"label": "Abrir formulario Jotform", "url": "https://www.jotform.com/myforms/"},
    4: {"label": "Abrir chat Copilot", "url": "https://m365.cloud.microsoft/chat"},
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

STATUS_COLORS = {
    "Completo": {"bg": "#e1f5ee", "text": "#085041", "icon": "check"},
    "En proceso": {"bg": "#faeeda", "text": "#854f0b", "icon": "clock"},
    "Pendiente": {"bg": "#f1efe8", "text": "#5f5e5a", "icon": "circle"},
}

# ---------------------------------------------------------------------------
# CARGA DE DATOS
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    if GOOGLE_SHEET_CSV_URL.strip():
        df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
    else:
        df = pd.read_csv("sample_expediente.csv")
    df = df.fillna("")
    return df


# ---------------------------------------------------------------------------
# UI HELPERS
# ---------------------------------------------------------------------------

BADGE_ICONS = {"check": "&#10003;", "clock": "&#9679;", "circle": ""}


def render_step(n: int, estatus: str, nota: str, is_last: bool) -> str:
    colors = STATUS_COLORS.get(estatus, STATUS_COLORS["Pendiente"])
    nombre = ETAPA_NOMBRES[n]
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
    if tool.get("url") and estatus != "Pendiente":
        link_html = (
            f'<a href="{tool["url"]}" target="_blank" '
            f'style="font-size:13px;text-decoration:none;">{tool["label"]} &#8599;</a>'
        )
    elif tool.get("url"):
        link_html = (
            f'<a href="{tool["url"]}" target="_blank" '
            f'style="font-size:13px;text-decoration:none;color:#9a988f;">{tool["label"]} &#8599;</a>'
        )

    return f"""
    <div style="display:flex;gap:14px;">
      <div style="display:flex;flex-direction:column;align-items:center;width:28px;flex-shrink:0;">
        {circle}
        {line}
      </div>
      <div style="flex:1;padding-bottom:1.5rem;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
          <p style="font-weight:600;font-size:14px;margin:0;{dim}">{n}. {nombre}</p>
          <span style="font-size:12px;color:{colors['text']};">{estatus or 'Pendiente'}</span>
        </div>
        <p style="font-size:13px;color:#5f5e5a;margin:0 0 8px;line-height:1.5;{dim}">{nota or '-'}</p>
        {link_html}
      </div>
    </div>
    """


# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Expediente Digital CAPEX", page_icon="\U0001F4C1", layout="centered")

st.markdown(
    "<h2 style='font-size:20px;font-weight:600;margin-bottom:0;'>Expediente digital CAPEX</h2>"
    "<p style='color:#5f5e5a;font-size:14px;margin-top:2px;'>Ragasa &mdash; Compras CAPEX</p>",
    unsafe_allow_html=True,
)

df = load_data()

if df.empty:
    st.warning("No hay proyectos cargados todavia.")
    st.stop()

proyectos = df["ID Proyecto"] + " — " + df["Nombre del Proyecto"]
seleccion = st.selectbox("Proyecto", proyectos, label_visibility="collapsed")
idx = proyectos[proyectos == seleccion].index[0]
row = df.loc[idx]

riesgo = row.get("Riesgo", "")
riesgo_colors = {"Alto": ("#fcebeb", "#791f1f"), "Medio": ("#faeeda", "#854f0b"), "Bajo": ("#eaf3de", "#27500a")}
rbg, rtext = riesgo_colors.get(riesgo, ("#f1efe8", "#5f5e5a"))

col1, col2 = st.columns([3, 1])
with col1:
    st.markdown(
        f"<p style='font-size:12px;color:#9a988f;margin:0;'>{row['ID Proyecto']}</p>"
        f"<p style='font-size:16px;font-weight:600;margin:0;'>{row['Nombre del Proyecto']}</p>",
        unsafe_allow_html=True,
    )
with col2:
    if riesgo:
        st.markdown(
            f"<div style='text-align:right;'><span style='background:{rbg};color:{rtext};"
            f"font-size:12px;font-weight:600;padding:4px 12px;border-radius:8px;'>"
            f"Riesgo {riesgo.lower()}</span></div>",
            unsafe_allow_html=True,
        )

proxima = row.get("Próxima Acción", "") or row.get("Proxima Accion", "")
if proxima:
    st.markdown(
        f"<div style='background:#f1efe8;border-radius:12px;padding:14px 20px;"
        f"margin:16px 0 24px;'><span style='color:#5f5e5a;font-size:14px;'>"
        f"Proxima accion &mdash; </span><span style='font-size:14px;'>{proxima}</span></div>",
        unsafe_allow_html=True,
    )

steps_html = ""
for n in range(1, 7):
    estatus = row.get(f"Etapa {n} Estatus", "Pendiente")
    nota = row.get(f"Etapa {n} Link", "")
    steps_html += render_step(n, estatus, nota, is_last=(n == 6))

st.markdown(steps_html, unsafe_allow_html=True)

st.divider()
st.caption(
    "Los datos vienen de la hoja 'Expediente' en Google Sheets. "
    "Se refrescan cada 5 minutos."
)
