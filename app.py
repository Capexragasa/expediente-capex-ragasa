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

Como correrlo:
    pip install -r requirements.txt
    streamlit run app.py
"""

from datetime import date, datetime

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

RIESGO_EMOJI = {"Alto": "\U0001F534", "Medio": "\U0001F7E1", "Bajo": "\U0001F7E2"}

# Si un proyecto abierto (no Cerrado) no se ha tocado en mas de este numero de
# dias, se marca automaticamente como "sin movimiento" en el roadmap y en el
# resumen, sin que nadie tenga que revisarlo a mano.
DIAS_SIN_MOVIMIENTO_ALERTA = 5

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

        st.download_button(
            "Descargar CSV listo para pegar al Google Sheet",
            data=salida.to_csv(index=False).encode("utf-8-sig"),
            file_name="expedientes_capex_importar.csv",
            mime="text/csv",
            use_container_width=True,
            key="descargar_lote_importacion",
        )

        st.caption(
            "Este archivo ya sale con las mismas columnas y en el mismo orden que tu Google Sheet actual."
        )

    return df_actual


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

tab_resumen, tab_roadmap, tab_importar = st.tabs(
    ["Resumen general", "Roadmap por proyecto", "Importar requisición"]
)

with tab_resumen:
    render_resumen(df)

with tab_roadmap:
    proyectos = df["ID Proyecto"] + " — " + df["Nombre del Proyecto"]
    seleccion = st.selectbox("Proyecto", proyectos, label_visibility="collapsed")
    idx = proyectos[proyectos == seleccion].index[0]
    row = df.loc[idx]
    render_roadmap(row)

with tab_importar:
    render_importador_requisiciones(df)

st.divider()
st.caption(
    "Cada etapa tiene 3 checks concretos; el estatus, el % de avance y las alertas de proyectos "
    "sin movimiento (mas de 5 dias sin actualizar) se calculan solos. Los datos vienen de la hoja "
    "'Expediente CAPEX - Ragasa (v2 checklist)' en Google Sheets y se refrescan cada minuto "
    "(o al instante con 'Actualizar datos'). Para actualizar un proyecto, marca/desmarca los "
    "checks directamente en esa hoja — en el Resumen general puedes hacer clic en cualquier fila "
    "para ver el detalle sin cambiar de pestaña."
)
