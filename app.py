import streamlit as st
import pandas as pd
import json
import requests
import datetime
import calendar

# --- Google Cloud Imports ---
try:
    from google.cloud import bigquery
    from google.oauth2 import service_account
except ImportError as e:
    st.error(f"Error: No se pudieron importar las librerías de Google Cloud (bigquery, google.oauth2). "
             f"Por favor, asegúrate de que estén instaladas: `pip install google-cloud-bigquery google-auth`. "
             f"Detalle: {e}")
    bigquery = None
    service_account = None

# --- BigQuery Connection ---
@st.cache_resource
def get_bigquery_client():
    if bigquery is None:
        return None
    try:
        client = bigquery.Client()
        return client
    except Exception as e:
        st.error(f"Error al inicializar el cliente de BigQuery. Asegúrate de estar autenticado y tener los permisos correctos: {e}")
        return None

bigquery_client = get_bigquery_client()

# --- BigQuery Query ---
def query_bigquery(sku_val: int, cp_val: int) -> pd.DataFrame:
    if bigquery_client is None:
        st.error("El cliente de BigQuery no está inicializado. No se puede realizar la consulta.")
        return pd.DataFrame()

    project_id = 'liv-dev-dig-chatbot'
    dataset_id = 'Fecha_Estimada_Entrega'
    source_table_id = 'TB_FEE_RESULTADO_FINAL__tmp'

    source_table = f"`{project_id}.{dataset_id}.{source_table_id}`"

    query = f"""
    SELECT * FROM {source_table}
    WHERE 1=1
    AND SKU_CVE = {sku_val}
    AND CP = {cp_val}
    AND NOT (MET_ENTREGA = 'FLOTA LIVERPOOL' AND ZONA_ROJA = 1)
    AND NOT (MET_ENTREGA = 'MENSAJERIA EXTERNA' AND EXCL_PROD != 0)
    AND INVENTARIO_OH > 0
    """
    st.info(f"Ejecutando consulta a BigQuery...")
    st.code(query, language="sql")

    try:
        query_job = bigquery_client.query(query)
        results = query_job.to_dataframe()
        return results
    except Exception as e:
        st.error(f"Error al ejecutar la consulta en BigQuery: {e}")
        return pd.DataFrame()

# --- Route API Call ---
def call_route_api(sku: str, cp: str, qty: int, weights: dict, recalculo: bool = False, data_recalculo: dict = None) -> dict:
    api_url = 'https://cloudrun-service-fee-316812040520.us-east4.run.app/fecha-estimada-entrega'
    headers = {'Content-Type': 'application/json'}
    payload = {
        "sku": sku,
        "cp": cp,
        "qty": qty,
        "weights": weights
    }

    if recalculo:
        payload["recalculo"] = True
        payload["dataRecalculo"] = data_recalculo
    else:
        payload["recalculo"] = False

    st.info(f"Llamando a la API de rutas en: {api_url} con payload: {payload}...")

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        
        json_response = response.json()
        
        if "error" in json_response:
            return {"api_error_message": json_response['error']} 
        elif "error:" in json_response:
            return {"api_error_message": json_response['error:']}
        
        return json_response
    except requests.exceptions.RequestException as e:
        return {"api_error_message": f"Error de conexión o HTTP: {e}"}
    except json.JSONDecodeError as e:
        return {"api_error_message": f"Error al decodificar la respuesta JSON de la API: {e}. Respuesta: {response.text}"}

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="Consulta de Rutas y BigQuery",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("Consulta de Rutas y Fecha Estimada de Entrega")
st.markdown("Esta aplicación te permite consultar información de Rutas y calcular las mejores Rutas de entrega a través de una API.")

# --- Inputs Section ---
st.sidebar.header("Parámetros de Consulta")

sku_input = st.sidebar.text_input("SKU", value="1139002876", help="Product identification number.")
cp_input = st.sidebar.text_input("Código Postal (CP)", value="52715", help="Postal code for the query.")
qty_input = st.sidebar.number_input("Cantidad (QTY)", value=2, min_value=1, help="Quantity of product units.")

st.sidebar.markdown("---")
st.sidebar.header("Opciones de Recálculo")

if 'recalculo_enabled' not in st.session_state:
    st.session_state.recalculo_enabled = False

if st.sidebar.button("Activar Recálculo" if not st.session_state.recalculo_enabled else "Desactivar Recálculo"):
    st.session_state.recalculo_enabled = not st.session_state.recalculo_enabled
    st.rerun()

if st.session_state.recalculo_enabled:
    st.sidebar.markdown("<p style='color: #FFD700; font-weight: bold;'>Recálculo Activado</p>", unsafe_allow_html=True)
    
    # Fecha Compra Original - Fixed and Read-Only
    fecha_compra_original_date = datetime.date(2025, 6, 2)
    st.sidebar.text_input("Fecha Compra Original (AAAA-MM-DD)", value=fecha_compra_original_date.strftime("%Y-%m-%d"), disabled=True, help="Fecha original de compra para el recálculo (no editable).")
    
    # Fecha Entrega Original - Calendar Input
    if 'fecha_entrega_original' not in st.session_state:
        st.session_state.fecha_entrega_original = datetime.date(2025, 6, 11) # Default date for calendar

    fecha_entrega_original_date = st.sidebar.date_input("Fecha Entrega Original (AAAA-MM-DD)", value=st.session_state.fecha_entrega_original, help="Fecha original de entrega para el recálculo.")
    st.session_state.fecha_entrega_original = fecha_entrega_original_date # Update session state on selection

    tienda_rechazo = st.sidebar.number_input("Tienda de Rechazo", value=108, min_value=0, help="ID de la tienda que rechazó el envío.")
else:
    st.sidebar.info("Recálculo Desactivado. Haz clic en el botón para activar más opciones.")
    fecha_compra_original_date = datetime.date(2025, 6, 1) # Keep default for API payload even if not displayed
    fecha_entrega_original_date = None
    tienda_rechazo = None


st.sidebar.markdown("---")
st.sidebar.header("Pesos de Optimización (Weights)")

DEFAULT_WEIGHTS_BAJA = {
    "inventario": 0.5, "tiempo": 1.0, "costo": 2.0, "nodo": 0.5, "ruta": 0.5, "diferencia": 0.0
}
DEFAULT_WEIGHTS_ALTA = {
    "inventario": 0.4, "tiempo": 2.0, "costo": 0.1, "nodo": 0.5, "ruta": 0.5, "diferencia": 2.0
}

def reset_weights_baja_callback():
    for key, value in DEFAULT_WEIGHTS_BAJA.items():
        st.session_state[key] = value
    st.session_state.show_reset_message = True
    st.session_state.reset_message_text = "Pesos ajustados a Temporada Baja."
    st.session_state.current_preset = 'baja'
    st.rerun()

def set_weights_alta_callback():
    for key, value in DEFAULT_WEIGHTS_ALTA.items():
        st.session_state[key] = value
    st.session_state.show_reset_message = True
    st.session_state.reset_message_text = "Pesos ajustados a Temporada Alta."
    st.session_state.current_preset = 'alta'
    st.rerun()

for key, value in DEFAULT_WEIGHTS_BAJA.items():
    if key not in st.session_state:
        st.session_state[key] = value

if 'show_reset_message' not in st.session_state:
    st.session_state.show_reset_message = False
if 'reset_message_text' not in st.session_state:
    st.session_state.reset_message_text = ""
if 'current_preset' not in st.session_state:
    st.session_state.current_preset = 'baja'

inventario_weight = st.sidebar.slider("Inventario", min_value=0.0, max_value=2.0, value=st.session_state.inventario, step=0.1, key='inventario', help="Peso para la optimización por inventario.")
tiempo_weight = st.sidebar.slider("Tiempo", min_value=0.0, max_value=2.0, value=st.session_state.tiempo, step=0.1, key='tiempo', help="Peso para la optimización por tiempo.")
costo_weight = st.sidebar.slider("Costo", min_value=0.0, max_value=2.0, value=st.session_state.costo, step=0.1, key='costo', help="Peso para la optimización por costo.")
nodo_weight = st.sidebar.slider("Nodo", min_value=0.0, max_value=2.0, value=st.session_state.nodo, step=0.1, key='nodo', help="Peso para la optimización por nodo.")
ruta_weight = st.sidebar.slider("Ruta", min_value=0.0, max_value=2.0, value=st.session_state.ruta, step=0.1, key='ruta', help="Peso para la optimización por ruta.")
diferencia_weight = st.sidebar.slider("Diferencia (Nueva)", min_value=0.0, max_value=2.0, value=st.session_state.diferencia, step=0.1, key='diferencia', help="Peso para la optimización por diferencia.")

current_slider_values = {
    "inventario": inventario_weight, "tiempo": tiempo_weight, "costo": costo_weight,
    "nodo": nodo_weight, "ruta": ruta_weight, "diferencia": diferencia_weight
}

tolerance = 1e-9
is_baja = all(abs(current_slider_values[k] - DEFAULT_WEIGHTS_BAJA[k]) < tolerance for k in DEFAULT_WEIGHTS_BAJA)
is_alta = all(abs(current_slider_values[k] - DEFAULT_WEIGHTS_ALTA[k]) < tolerance for k in DEFAULT_WEIGHTS_ALTA)

if is_baja:
    st.session_state.current_preset = 'baja'
elif is_alta:
    st.session_state.current_preset = 'alta'
else:
    st.session_state.current_preset = 'custom'

if st.session_state.current_preset == 'baja':
    st.sidebar.markdown("<p style='color: #87CEEB; font-weight: bold;'>Preset activo: Temporada Baja</p>", unsafe_allow_html=True)
elif st.session_state.current_preset == 'alta':
    st.sidebar.markdown("<p style='color: #FFD700; font-weight: bold;'>Preset activo: Temporada Alta</p>", unsafe_allow_html=True)
else:
    st.sidebar.warning("Pesos: **Custom** (no coinciden con presets)")

st.sidebar.button("Temporada Baja", on_click=reset_weights_baja_callback)
st.sidebar.button("Temporada Alta", on_click=set_weights_alta_callback)

if st.session_state.show_reset_message:
    st.sidebar.success(st.session_state.reset_message_text)
    st.session_state.show_reset_message = False

if 'bigquery_df' not in st.session_state:
    st.session_state.bigquery_df = pd.DataFrame()
if 'api_rutas_response' not in st.session_state:
    st.session_state.api_rutas_response = {}
if 'bigquery_query_attempted' not in st.session_state:
    st.session_state.bigquery_query_attempted = False
if 'scroll_to_bigquery_table' not in st.session_state:
    st.session_state.scroll_to_bigquery_table = False
if 'selected_route_id_to_scroll' not in st.session_state:
    st.session_state.selected_route_id_to_scroll = None

# --- BigQuery Query Section ---
st.header("1. Resultados de Rutas")

def highlight_bigquery_results_by_trace_id(row, selected_trace_ids):
    if 'ID_TRAZO' in row and row['ID_TRAZO'] in selected_trace_ids:
        return ['background-color: #FFD700; color: #000000'] * len(row)
    else:
        return [''] * len(row)

if st.button("Consultar Rutas"):
    if sku_input and cp_input:
        try:
            sku_int = int(sku_input)
            cp_int = int(cp_input)
            st.session_state.bigquery_df = query_bigquery(sku_int, cp_int)
            st.session_state.bigquery_query_attempted = True
            st.session_state.api_rutas_response = {}
            st.session_state.selected_route_id_to_scroll = None
        except ValueError:
            st.error("Error: SKU y/o Código Postal deben ser valores numéricos enteros para la consulta a BigQuery.")
            st.session_state.bigquery_query_attempted = False
    else:
        st.error("Por favor, introduce un SKU y un Código Postal para consultar BigQuery.")
        st.session_state.bigquery_query_attempted = False

if not st.session_state.bigquery_df.empty:
    st.subheader("Datos de Inventario y Ubicación")
    st.write(f"Número de registros: **{len(st.session_state.bigquery_df)}**")
    
    selected_trace_ids = set()
    if st.session_state.api_rutas_response and st.session_state.api_rutas_response.get("rutas"):
        selected_trace_ids = {ruta['id_trazo'] for ruta in st.session_state.api_rutas_response["rutas"]}
        if st.session_state.api_rutas_response["rutas"]:
            st.session_state.selected_route_id_to_scroll = st.session_state.api_rutas_response["rutas"][0]['id_trazo']

    st.dataframe(
        st.session_state.bigquery_df.style.apply(
            highlight_bigquery_results_by_trace_id,
            axis=1,
            selected_trace_ids=selected_trace_ids
        ),
        use_container_width=True,
        hide_index=True
    )
    st.markdown(
        "<p style='color: green; font-weight: bold;'>Las filas mostradas arriba son los resultados de la consulta a BigQuery.</p>",
        unsafe_allow_html=True
    )
else:
    st.info("Haz clic en 'Consultar Rutas' para cargar los datos de inventario y ubicación.")
    if st.session_state.bigquery_query_attempted:
        st.warning("No existen registros con los parámetros proporcionados en BigQuery.")
    st.session_state.bigquery_query_attempted = False

st.markdown("---")

# --- Route API Query Section ---
st.header("2. Cálculo de la Mejor Ruta")

api_button_col, _ = st.columns([0.2, 0.8])
with api_button_col:
    calculate_route_button = st.button("Calcular Ruta")

if st.session_state.api_rutas_response and "api_error_message" in st.session_state.api_rutas_response:
    st.error(st.session_state.api_rutas_response["api_error_message"])

if calculate_route_button:
    if sku_input and cp_input and qty_input:
        try:
            int(sku_input)
            int(cp_input)
            
            weights_payload = {
                "inventario": inventario_weight,
                "tiempo": tiempo_weight,
                "costo": costo_weight,
                "nodo": nodo_weight,
                "ruta": ruta_weight,
                "diferencia": diferencia_weight
            }

            data_recalculo_payload = None
            if st.session_state.recalculo_enabled:
                if fecha_entrega_original_date is None or tienda_rechazo is None:
                    st.error("Por favor, completa todos los campos de recálculo (Fecha Entrega Original, Tienda de Rechazo) si el recálculo está activado.")
                    st.stop()
                
                data_recalculo_payload = {
                    "fechaCompraOriginal": fecha_compra_original_date.strftime("%Y-%m-%d"),
                    "fechaEntregaOriginal": fecha_entrega_original_date.strftime("%Y-%m-%d"),
                    "tiendaRechazo": tienda_rechazo
                }
            
            st.session_state.api_rutas_response = call_route_api(
                sku_input, cp_input, qty_input, weights_payload,
                recalculo=st.session_state.recalculo_enabled,
                data_recalculo=data_recalculo_payload
            )
            
            if st.session_state.api_rutas_response.get("rutas"):
                st.session_state.scroll_to_bigquery_table = True
                st.session_state.selected_route_id_to_scroll = st.session_state.api_rutas_response["rutas"][0]['id_trazo']
            else:
                st.session_state.scroll_to_bigquery_table = False
                st.session_state.selected_route_id_to_scroll = None
            
            st.rerun()
        except ValueError:
            st.error("Error: SKU y/o Código Postal deben ser valores numéricos enteros para calcular la ruta.")
    else:
        st.error("Por favor, asegúrate de que SKU, CP y Cantidad estén completos para calcular la ruta.")

if st.session_state.get('scroll_to_bigquery_table', False) and st.session_state.selected_route_id_to_scroll:
    scroll_script = f"""
    <script>
        setTimeout(function() {{
            const targetId = "{st.session_state.selected_route_id_to_scroll}";
            const dataframes = document.querySelectorAll('.stDataFrame');
            let foundRow = false;

            dataframes.forEach(df => {{
                const rows = df.querySelectorAll('tbody tr');
                rows.forEach(row => {{
                    const firstCellText = row.querySelector('td:first-child')?.textContent;
                    if (firstCellText && firstCellText.includes(targetId)) {{
                        row.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                        foundRow = true;
                        return;
                    }}
                }});
                if (foundRow) return;
            }});
            
            if (!foundRow) {{
                var tableAnchor = document.getElementById('bigquery_table_anchor');
                if (tableAnchor) {{
                    tableAnchor.scrollIntoView({{behavior: 'smooth', block: 'start'}});
                }}
            }}
        }}, 100);
    </script>
    """
    st.markdown(scroll_script, unsafe_allow_html=True)
    st.session_state.scroll_to_bigquery_table = False
    st.session_state.selected_route_id_to_scroll = None

# --- Calendar Section ---
if st.session_state.api_rutas_response and "api_error_message" not in st.session_state.api_rutas_response:
    st.subheader("Visualización de Fechas Clave")

    fecha_compra = datetime.date(2025, 6, 1) # Fixed purchase date for calendar display
    if st.session_state.recalculo_enabled: # If recalculation is enabled, use its value for calendar display
        fecha_compra = datetime.date(2025, 6, 1) # This is now fixed in the UI, so it always comes from there.
    
    fecha_entrega = None
    
    if st.session_state.api_rutas_response.get("resumen"):
        resumen_data = st.session_state.api_rutas_response["resumen"]
        if "fecha_de_entrega" in resumen_data: 
            try:
                fecha_entrega = datetime.datetime.strptime(str(resumen_data["fecha_de_entrega"]), "%Y-%m-%d").date()
            except ValueError:
                st.warning("Formato de fecha de entrega (fecha_de_entrega) inválido en la respuesta de la API. Se esperaba 'YYYY-MM-DD'.")
        elif "tiempo_maximo_dias" in resumen_data:
            delivery_days = resumen_data["tiempo_maximo_dias"]
            fecha_entrega = fecha_compra + datetime.timedelta(days=delivery_days)
            st.info(f"Fecha de entrega aproximada calculada a partir de tiempo_maximo_dias: {fecha_entrega.strftime('%d-%B-%Y')}")

    cal = calendar.Calendar(firstweekday=6)
    
    display_year = fecha_compra.year
    display_month = fecha_compra.month
    if fecha_entrega and (fecha_entrega.year != fecha_compra.year or fecha_entrega.month != fecha_compra.month):
        display_year = fecha_entrega.year
        display_month = fecha_entrega.month

    month_cal = cal.monthdayscalendar(display_year, display_month)

    calendar_html = f"""
    <style>
        .calendar-container {{
            font-family: Arial, sans-serif; background-color: #262730; color: #ffffff;
            border-radius: 10px; padding: 20px; box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            max-width: 500px; margin: auto;
        }}
        .calendar-header {{
            display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;
        }}
        .calendar-header h3 {{
            margin: 0; font-size: 1.5em; color: #ffffff;
        }}
        .calendar-weekdays {{
            display: grid; grid-template-columns: repeat(7, 1fr); text-align: center;
            font-weight: bold; margin-bottom: 10px; color: #bbbbbb;
        }}
        .calendar-day-grid {{
            display: grid; grid-template-columns: repeat(7, 1fr); gap: 5px; text-align: center;
        }}
        .calendar-day {{
            padding: 10px 5px; border-radius: 5px; background-color: #33343d;
            color: #ffffff; font-size: 0.9em; display: flex; flex-direction: column;
            justify-content: center; align-items: center; min-height: 50px;
            position: relative; overflow: hidden;
        }}
        .calendar-day.empty {{
            background-color: transparent; color: #555555;
        }}
        .calendar-day.highlight-purchase {{
            background-color: #8B0000; color: #ffffff; font-weight: bold;
            box-shadow: 0 0 8px rgba(255, 0, 0, 0.5);
        }}
        .calendar-day.highlight-delivery {{
            background-color: #006400; color: #ffffff; font-weight: bold;
            box-shadow: 0 0 8px rgba(0, 255, 0, 0.5);
        }}
        .calendar-day.highlight-both {{
            background: linear-gradient(to right, #8B0000 50%, #006400 50%);
            color: #ffffff; font-weight: bold;
            box-shadow: 0 0 8px rgba(0, 100, 0, 0.5), 0 0 8px rgba(139, 0, 0, 0.5);
        }}
        .calendar-day .label-container {{
            display: flex; width: 100%; justify-content: center; font-size: 0.65em;
            line-height: 1; margin-top: 5px;
        }}
        .calendar-day .label-combined {{
            color: #ffffff; font-weight: bold; text-align: center;
        }}
        @media (max-width: 600px) {{
            .calendar-day {{
                min-height: 40px; font-size: 0.8em;
            }}
            .calendar-header h3 {{
                font-size: 1.2em;
            }}
        }}
    </style>
    <div class="calendar-container">
        <div class="calendar-header">
            <h3>{calendar.month_name[display_month]} {display_year}</h3>
        </div>
        <div class="calendar-weekdays">
            <span>Dom</span><span>Lun</span><span>Mar</span><span>Mié</span><span>Jue</span><span>Vie</span><span>Sáb</span>
        </div>
        <div class="calendar-day-grid">
    """

    for week in month_cal:
        for day in week:
            day_classes = "calendar-day"
            day_number_content = str(day) if day != 0 else ""
            label_content = ""

            current_date = None
            if day != 0:
                current_date = datetime.date(display_year, display_month, day)

            if current_date == fecha_compra and current_date == fecha_entrega:
                day_classes += " highlight-both"
                label_content = f"""
                <div class="label-container">
                    <span class="label-combined">Mismo Día</span>
                </div>
                """
            elif current_date == fecha_compra:
                day_classes += " highlight-purchase"
                label_content = "<small>Compra</small>"
            elif fecha_entrega and current_date == fecha_entrega:
                day_classes += " highlight-delivery"
                label_content = "<small>Entrega</small>"
            elif day == 0:
                day_classes += " empty"
                day_number_content = ""
            
            final_day_content = f"{day_number_content}{label_content}" if day != 0 else ""
            
            calendar_html += f'<div class="{day_classes}">{final_day_content}</div>'

    calendar_html += """
        </div>
    </div>
    """
    st.markdown(calendar_html, unsafe_allow_html=True)

    st.markdown(f"**Fecha de Compra:** {fecha_compra.strftime('%d-%B-%Y')}")
    if fecha_entrega:
        st.markdown(f"**Fecha de Entrega:** {fecha_entrega.strftime('%d-%B-%Y')}")
    else:
        st.markdown("**Fecha de Entrega:** No disponible o formato inválido en la API.")

    st.markdown("---")
    
    st.subheader("Inputs de la Consulta a la API")
    inputs_data = st.session_state.api_rutas_response.get("inputs", {})
    if inputs_data:
        all_input_rows = []
        for key, value in inputs_data.items():
            if key == "weights" and isinstance(value, dict):
                for weight_key, weight_value in value.items():
                    all_input_rows.append([f"weights.{weight_key}", weight_value])
            elif key == "dataRecalculo" and isinstance(value, dict):
                for data_key, data_value in value.items():
                    all_input_rows.append([f"dataRecalculo.{data_key}", data_value])
            else:
                all_input_rows.append([key, value])
        
        inputs_df = pd.DataFrame(all_input_rows, columns=['Variable', 'Valor'])
        
        st.dataframe(
            inputs_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Variable": st.column_config.Column("Variable", width="fit_content"),
                "Valor": st.column_config.Column("Valor", width="auto")
            }
        )
    else:
        st.info("No se encontraron inputs para la consulta a la API.")

    st.subheader("Rutas Obtenidas por la API")
    if st.session_state.api_rutas_response.get("rutas"):
        rutas_df = pd.DataFrame(st.session_state.api_rutas_response["rutas"])
        st.dataframe(
            rutas_df,
            use_container_width=True,
            hide_index=True
        )
        st.markdown(
            "<p style='color: green; font-weight: bold;'>Las rutas mostradas arriba son las rutas de la API.</p>",
            unsafe_allow_html=True
        )
    else:
        st.info("La API no devolvió rutas para los inputs proporcionados.")

    st.subheader("Resumen de la Consulta")
    resumen_data = st.session_state.api_rutas_response.get("resumen", {})
    if resumen_data:
        resumen_df = pd.DataFrame(resumen_data.items(), columns=['Métrica', 'Valor'])
        st.dataframe(
            resumen_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Métrica": st.column_config.Column("Métrica", width="fit_content"),
                "Valor": st.column_config.Column("Valor", width="auto")
            }
        )
    else:
        st.warning("No se pudo obtener el resumen de la consulta de la API.")