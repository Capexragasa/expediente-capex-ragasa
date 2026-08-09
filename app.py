"""
Expediente Digital CAPEX - Ragasa
Tablero tipo "caminito": un roadmap por proyecto con las 6 etapas del proceso
de Compras CAPEX. Cada etapa tiene 3 checks concretos (lo que realmente hay
que hacer) mas una nota corta opcional; el estatus (Pendiente / En proceso /
Completo) y el % de avance se calculan solos a partir de esos checks, no se
escriben a mano. Incluye una vista de resumen general con metricas, una tabla
filtrable de todos los proyectos, y lee los datos en vivo desde un Google
Sheet compartido (no hace falta tener la cuenta del dueno del Sheet).

Como correrlo:
    pip install -r requirements.txt
    streamlit run app.py
"""

import pandas as pd
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

# ---------------------------------------------------------------------------
# CARGA DE DATOS
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
        if df.empty or "ID Proyecto" not in df.columns:
            raise ValueError("Sheet vacio o con columnas inesperadas")
        fuente = "sheet"
    except Exception:
        df = pd.read_csv("sample_expediente.csv")
        fuente = "demo"
    df = df.fillna("")
    return df, fuente


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


def render_resumen(df: pd.DataFrame) -> None:
    resumen = df.copy()
    resumen["% Avance"] = resumen.apply(avance_pct, axis=1)
    resumen["Etapa actual"] = resumen.apply(etapa_actual, axis=1)
    resumen["Etapas completas"] = resumen.apply(lambda r: f"{etapas_completas(r)}/6", axis=1)

    total = len(resumen)
    avance_prom = resumen["% Avance"].mean() if total else 0
    riesgo_alto = int((resumen.get("Riesgo", "") == "Alto").sum())
    en_proceso = int(sum(
        1 for _, r in resumen.iterrows()
        if any(etapa_status(r, n) == "En proceso" for n in range(1, 7))
    ))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Proyectos", total)
    m2.metric("Avance promedio", f"{avance_prom * 100:.0f}%")
    m3.metric("En proceso activo", en_proceso)
    m4.metric("Riesgo alto", riesgo_alto)

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

    st.dataframe(
        filtrado[columnas],
        column_config={
            "% Avance": st.column_config.ProgressColumn(
                "% Avance", min_value=0, max_value=1, format="%.0f%%",
            ),
        },
        hide_index=True,
        use_container_width=True,
    )

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

df, fuente = load_data()

if fuente == "sheet":
    st.markdown(
        f"<p style='font-size:12px;color:#5f5e5a;'>&#128260; Datos en vivo desde Google Sheets &mdash; "
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

tab_roadmap, tab_resumen = st.tabs(["Roadmap por proyecto", "Resumen general"])

with tab_roadmap:
    proyectos = df["ID Proyecto"] + " — " + df["Nombre del Proyecto"]
    seleccion = st.selectbox("Proyecto", proyectos, label_visibility="collapsed")
    idx = proyectos[proyectos == seleccion].index[0]
    row = df.loc[idx]
    render_roadmap(row)

with tab_resumen:
    render_resumen(df)

st.divider()
st.caption(
    "Cada etapa tiene 3 checks concretos; el estatus (Pendiente / En proceso / Completo) y el "
    "% de avance se calculan solos segun cuantos esten marcados. Los datos vienen de la hoja "
    "'Expediente CAPEX - Ragasa (v2 checklist)' en Google Sheets y se refrescan cada minuto "
    "(o al instante con 'Actualizar datos'). Para actualizar un proyecto, marca/desmarca los "
    "checks directamente en esa hoja."
)
