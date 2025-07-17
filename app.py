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
    source_table_id = 'TB_FEE_RESULTADO_CON_TIEMPO3_UUID'

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

# --- Definiciones de Pesos y Callbacks ---
# Define default weights
DEFAULT_WEIGHTS_BAJA = {
    "inventario": 0.5, "tiempo": 1.0, "costo": 2.0, "nodo": 0.5, "ruta": 0.5, 
    "diferencia": 0.0 # Default for when recalculation is OFF
}
DEFAULT_WEIGHTS_ALTA = {
    "inventario": 0.4, "tiempo": 2.0, "costo": 0.1, "nodo": 0.5, "ruta": 0.5, 
    "diferencia": 4.0 # Default for when recalculation is ON, set to 4.0
}

# Callback functions to reset weights to presets
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

# --- Sección de Inputs ---
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
    # When toggling recalculation, adjust weights in session_state immediately
    if st.session_state.recalculo_enabled:
        # Set all weights to Temporada Alta values, and diferencia to 4.0
        st.session_state.inventario = DEFAULT_WEIGHTS_ALTA["inventario"]
        st.session_state.tiempo = DEFAULT_WEIGHTS_ALTA["tiempo"]
        st.session_state.costo = DEFAULT_WEIGHTS_ALTA["costo"]
        st.session_state.nodo = DEFAULT_WEIGHTS_ALTA["nodo"]
        st.session_state.ruta = DEFAULT_WEIGHTS_ALTA["ruta"]
        st.session_state.diferencia = 4.0 # Explicitly set to 4.0 for recalculo mode
        st.session_state.current_preset = 'recalc_active' # Custom preset state for recalculo
    else:
        # Revert to Temporada Baja defaults when recalculo is off
        for key, value in DEFAULT_WEIGHTS_BAJA.items():
            st.session_state[key] = value
        st.session_state.diferencia = 0.0 # Explicitly set to 0.0 when recalculo is off
        st.session_state.current_preset = 'baja' # Default back to Baja preset state

    st.rerun() # Rerun to update sidebar inputs and sliders

# Variables to hold recalculation input values
fecha_compra_original_date_fixed = datetime.date(2025, 6, 2)
fecha_entrega_original_date = None
tienda_rechazo = None

if st.session_state.recalculo_enabled:
    st.sidebar.markdown("<p style='color: #FFD700; font-weight: bold;'>Recálculo Activado</p>", unsafe_allow_html=True)
    
    # Fecha Compra Original - Fixed and Read-Only
    st.sidebar.text_input("Fecha Compra Original (AAAA-MM-DD)", value=fecha_compra_original_date_fixed.strftime("%Y-%m-%d"), disabled=True, help="Fecha original de compra para el recálculo (no editable).")
    
    # Fecha Entrega Original - Calendar Input
    if 'fecha_entrega_original_recalculo' not in st.session_state:
        st.session_state.fecha_entrega_original_recalculo = datetime.date(2025, 6, 12) # Default date for calendar

    fecha_entrega_original_date = st.sidebar.date_input("Fecha Entrega Original (AAAA-MM-DD)", value=st.session_state.fecha_entrega_original_recalculo, help="Fecha original de entrega para el recálculo.")
    st.session_state.fecha_entrega_original_recalculo = fecha_entrega_original_date # Update session state on selection

    tienda_rechazo = st.sidebar.number_input("Tienda de Rechazo", value=108, min_value=0, help="ID de la tienda que rechazó el envío.")
else:
    st.sidebar.info("Recálculo Desactivado. Haz clic en el botón para activar más opciones.")


st.sidebar.markdown("---")
st.sidebar.header("Pesos de Optimización (Weights)")


# Initialize session state for weights if not already present
for key, value in DEFAULT_WEIGHTS_BAJA.items():
    if key not in st.session_state:
        st.session_state[key] = value

if 'show_reset_message' not in st.session_state:
    st.session_state.show_reset_message = False
if 'reset_message_text' not in st.session_state:
    st.session_state.reset_message_text = ""
if 'current_preset' not in st.session_state:
    st.session_state.current_preset = 'baja'


# Conditional display of sliders
if st.session_state.recalculo_enabled:
    # Only show Diferencia slider when recalculo is active
    diferencia_weight = st.sidebar.slider("Diferencia (Nueva)", min_value=0.0, max_value=4.0, value=st.session_state.diferencia, step=0.2, key='diferencia', help="Peso para la optimización por diferencia.")
    
    # Set other weights to Temporada Alta values (no sliders needed here, as they are fixed)
    inventario_weight = DEFAULT_WEIGHTS_ALTA["inventario"]
    tiempo_weight = DEFAULT_WEIGHTS_ALTA["tiempo"]
    costo_weight = DEFAULT_WEIGHTS_ALTA["costo"]
    nodo_weight = DEFAULT_WEIGHTS_ALTA["nodo"]
    ruta_weight = DEFAULT_WEIGHTS_ALTA["ruta"]
    
    st.sidebar.markdown("<p style='color: #FFD700; font-weight: bold;'>Pesos Fijos: Base Temporada Alta</p>", unsafe_allow_html=True)
    st.sidebar.markdown(f"Inventario: **{inventario_weight}**")
    st.sidebar.markdown(f"Tiempo: **{tiempo_weight}**")
    st.sidebar.markdown(f"Costo: **{costo_weight}**")
    st.sidebar.markdown(f"Nodo: **{nodo_weight}**")
    st.sidebar.markdown(f"Ruta: **{ruta_weight}**")

else:
    # Show all sliders as normal when recalculo is inactive
    inventario_weight = st.sidebar.slider("Inventario", min_value=0.0, max_value=2.0, value=st.session_state.inventario, step=0.1, key='inventario', help="Peso para la optimización por inventario.")
    tiempo_weight = st.sidebar.slider("Tiempo", min_value=0.0, max_value=2.0, value=st.session_state.tiempo, step=0.1, key='tiempo', help="Peso para la optimización por tiempo.")
    costo_weight = st.sidebar.slider("Costo", min_value=0.0, max_value=2.0, value=st.session_state.costo, step=0.1, key='costo', help="Peso para la optimización por costo.")
    nodo_weight = st.sidebar.slider("Nodo", min_value=0.0, max_value=2.0, value=st.session_state.nodo, step=0.1, key='nodo', help="Peso para la optimización por nodo.")
    ruta_weight = st.sidebar.slider("Ruta", min_value=0.0, max_value=2.0, value=st.session_state.ruta, step=0.1, key='ruta', help="Peso para la optimización por ruta.")
    diferencia_weight = 0.0 # When hidden, ensure its value is 0.0 for consistency if used elsewhere

    # Determine current preset status for display (when not in recalculo mode)
    tolerance = 1e-9
    current_slider_values = {
        "inventario": inventario_weight, "tiempo": tiempo_weight, "costo": costo_weight,
        "nodo": nodo_weight, "ruta": ruta_weight, "diferencia": diferencia_weight
    }

    is_baja = all(abs(current_slider_values[k] - DEFAULT_WEIGHTS_BAJA[k]) < tolerance for k in DEFAULT_WEIGHTS_BAJA)
    is_alta = (all(abs(current_slider_values[k] - DEFAULT_WEIGHTS_ALTA[k]) < tolerance for k in DEFAULT_WEIGHTS_ALTA if k != "diferencia") and
               abs(current_slider_values["diferencia"] - 0.0) < tolerance)


    if is_baja:
        st.session_state.current_preset = 'baja'
        st.sidebar.markdown("<p style='color: #87CEEB; font-weight: bold;'>Preset activo: Temporada Baja</p>", unsafe_allow_html=True)
    elif is_alta:
        st.session_state.current_preset = 'alta'
        st.sidebar.markdown("<p style='color: #FFD700; font-weight: bold;'>Preset activo: Temporada Alta</p>", unsafe_allow_html=True)
    else:
        st.session_state.current_preset = 'custom'
        st.sidebar.warning("Pesos: **Custom** (no coinciden con presets)")

    # Display preset buttons only when recalculation is OFF
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
if 'rejected_tda_cve' not in st.session_state:
    st.session_state.rejected_tda_cve = None


# --- BigQuery Query Section ---
st.header("1. Resultados de Rutas")

# Updated highlight function
def highlight_bigquery_results(row, selected_trace_ids, rejected_tda_cve_to_highlight, recalculo_active):
    styles = [''] * len(row)
    
    # Priority 1: Highlight selected API route in yellow
    if 'ID_TRAZO' in row and row['ID_TRAZO'] in selected_trace_ids:
        styles = ['background-color: #FFD700; color: #000000'] * len(row)
    # Priority 2: Highlight rejected TDA_CVE in red IF recalculation is active
    elif recalculo_active and rejected_tda_cve_to_highlight is not None and 'TDA_CVE' in row and row['TDA_CVE'] == rejected_tda_cve_to_highlight:
        styles = ['background-color: #FF0000; color: #FFFFFF'] * len(row) # Red background, white text
    
    return styles


if st.button("Consultar Rutas"):
    if sku_input and cp_input:
        try:
            sku_int = int(sku_input)
            cp_int = int(cp_input)
            st.session_state.bigquery_df = query_bigquery(sku_int, cp_int)
            st.session_state.bigquery_query_attempted = True
            st.session_state.api_rutas_response = {} # Clear API response on new BQ query
            st.session_state.selected_route_id_to_scroll = None
            st.session_state.rejected_tda_cve = None # Clear rejected TDA_CVE on new BQ query, it will be set by "Calcular Ruta"

        except ValueError:
            st.error("Error: SKU y/o Código Postal deben ser valores numéricos enteros para la consulta a BigQuery.")
            st.session_state.bigquery_query_attempted = False
    else:
        st.error("Por favor, introduce un SKU y un Código Postal para consultar BigQuery.")
        st.session_state.bigquery_query_attempted = False

if not st.session_state.bigquery_df.empty:
    st.subheader("Datos de Inventario y Ubicación")
    st.write(f"Número de registros: **{len(st.session_state.bigquery_df)}**")
    
    # MODIFIED: Logic for inventory total to exclude rejected store if recalculo is active
    if 'INVENTARIO_OH' in st.session_state.bigquery_df.columns and 'TDA_CVE' in st.session_state.bigquery_df.columns:
        df_for_inventory_calc = st.session_state.bigquery_df.drop_duplicates(subset=['TDA_CVE']).copy()
        
        # Check if recalculation is active AND a rejected_tda_cve has been set (i.e., after a 'Calcular Ruta' click)
        if st.session_state.recalculo_enabled and st.session_state.rejected_tda_cve is not None:
            # Filter out the rejected store for inventory calculation
            df_for_inventory_calc = df_for_inventory_calc[df_for_inventory_calc['TDA_CVE'] != st.session_state.rejected_tda_cve]
            st.write(f"Inventario total: **{int(df_for_inventory_calc['INVENTARIO_OH'].sum())}** (sin tienda rechazada)")
        else:
            st.write(f"Inventario total: **{int(df_for_inventory_calc['INVENTARIO_OH'].sum())}**")

    elif 'INVENTARIO_OH' in st.session_state.bigquery_df.columns:
        st.write(f"Inventario total: **{int(st.session_state.bigquery_df['INVENTARIO_OH'].sum())}** (No se puede deduplicar por TDA_CVE)")
    else:
        st.info("Columna 'INVENTARIO_OH' no encontrada para calcular inventario.")

    selected_trace_ids = set()
    if st.session_state.api_rutas_response and st.session_state.api_rutas_response.get("rutas"):
        selected_trace_ids = {ruta['id_trazo'] for ruta in st.session_state.api_rutas_response["rutas"]}
        if st.session_state.api_rutas_response["rutas"]:
            st.session_state.selected_route_id_to_scroll = st.session_state.api_rutas_response["rutas"][0]['id_trazo']
    
    st.dataframe(
        st.session_state.bigquery_df.style.apply(
            highlight_bigquery_results,
            axis=1,
            selected_trace_ids=selected_trace_ids,
            rejected_tda_cve_to_highlight=st.session_state.rejected_tda_cve, # Pass stored value
            recalculo_active=st.session_state.recalculo_enabled # Pass recalculation state
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

            # --- Validation for Fecha Entrega Original vs Fecha Compra Original ---
            if st.session_state.recalculo_enabled:
                if fecha_entrega_original_date < fecha_compra_original_date_fixed:
                    st.error("Error: La 'Fecha Entrega Original' no puede ser anterior a la 'Fecha Compra Original'. Por favor, ajusta la fecha de entrega.")
                    st.stop() # Stop execution if validation fails
            # --- End Validation ---

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
                    "fechaCompraOriginal": fecha_compra_original_date_fixed.strftime("%Y-%m-%d"),
                    "fechaEntregaOriginal": fecha_entrega_original_date.strftime("%Y-%m-%d"),
                    "tiendaRechazo": tienda_rechazo
                }
                # Store the tienda_rechazo for highlighting rejected routes after API call
                st.session_state.rejected_tda_cve = tienda_rechazo
            else:
                st.session_state.rejected_tda_cve = None # Clear rejected TDA_CVE if recalculation is off


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

    fecha_compra = fecha_compra_original_date_fixed
    
    # This will be the NEW delivery date from the API response
    new_fecha_entrega = None 
    
    if st.session_state.api_rutas_response.get("resumen"):
        resumen_data = st.session_state.api_rutas_response["resumen"]
        if "fecha_de_entrega" in resumen_data: 
            try:
                new_fecha_entrega = datetime.datetime.strptime(str(resumen_data["fecha_de_entrega"]), "%Y-%m-%d").date()
            except ValueError:
                st.warning("Formato de fecha de entrega (fecha_de_entrega) inválido en la respuesta de la API. Se esperaba 'YYYY-MM-DD'.")
        elif "tiempo_maximo_dias" in resumen_data:
            delivery_days = resumen_data["tiempo_maximo_dias"]
            new_fecha_entrega = fecha_compra + datetime.timedelta(days=delivery_days)
            st.info(f"Fecha de entrega aproximada calculada a partir de tiempo_maximo_dias: {new_fecha_entrega.strftime('%d-%B-%Y')}")

    cal = calendar.Calendar(firstweekday=6)
    
    # Determine the year and month to display in the calendar, prioritizing dates
    display_year = fecha_compra.year
    display_month = fecha_compra.month

    dates_to_consider = [fecha_compra]
    if new_fecha_entrega:
        dates_to_consider.append(new_fecha_entrega)
    if fecha_entrega_original_date and st.session_state.recalculo_enabled:
        dates_to_consider.append(fecha_entrega_original_date)
    
    # Find the earliest and latest month/year to span the calendar view
    if dates_to_consider:
        min_date = min(dates_to_consider)
        max_date = max(dates_to_consider)
        # Display month that spans all relevant dates or the first relevant month
        display_year = min_date.year
        display_month = min_date.month

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
        .calendar-day.highlight-delivery {{ /* Original green for non-recalc delivery */
            background-color: #006400; color: #ffffff; font-weight: bold;
            box-shadow: 0 0 8px rgba(0, 255, 0, 0.5);
        }}
        .calendar-day.highlight-original-delivery {{ /* New green for original delivery in recalc mode */
            background-color: #006400; color: #ffffff; font-weight: bold;
            box-shadow: 0 0 8px rgba(0, 255, 0, 0.5);
        }}
        .calendar-day.highlight-both {{ /* Original red+green for non-recalc same day */
            background: linear-gradient(to right, #8B0000 50%, #006400 50%);
            color: #ffffff; font-weight: bold;
            box-shadow: 0 0 8px rgba(0, 100, 0, 0.5), 0 0 8px rgba(139, 0, 0, 0.5);
        }}
        .calendar-day.highlight-recalc-new-delivery {{ /* New yellow for recalc new delivery */
            background-color: #FFD700; color: #000000; font-weight: bold;
            box-shadow: 0 0 8px rgba(255, 215, 0, 0.7);
        }}
        .calendar-day.highlight-recalc-same-date {{ /* Split yellow/green for recalc same original delivery */
            background: linear-gradient(to right, #FFD700 50%, #006400 50%);
            color: #000000; font-weight: bold;
            box-shadow: 0 0 8px rgba(255, 215, 0, 0.7), 0 0 8px rgba(0, 100, 0, 0.5);
        }}
        .calendar-day.highlight-recalc-new-delivery-and-purchase {{ /* New: Red/Yellow split for new delivery and purchase same day */
            background: linear-gradient(to right, #8B0000 50%, #FFD700 50%);
            color: #000000; font-weight: bold;
            box-shadow: 0 0 8px rgba(139, 0, 0, 0.5), 0 0 8px rgba(255, 215, 0, 0.7);
        }}
        .calendar-day .label-container {{
            display: flex; width: 100%; justify-content: center; font-size: 0.65em;
            line-height: 1; margin-top: 5px;
        }}
        .calendar-day .label-combined {{
            color: #ffffff; font-weight: bold; text-align: center;
        }}
        /* Ensure text is visible on split background */
        .calendar-day.highlight-recalc-same-date .label-text,
        .calendar-day.highlight-recalc-new-delivery-and-purchase .label-text {{
            color: #000000; /* Black text for better contrast on yellow side */
            text-shadow: 1px 1px 2px rgba(255,255,255,0.8); /* Optional: add shadow for readability */
        }}
        /* Color boxes for legend */
        .color-box {{
            width: 15px;
            height: 15px;
            border: 1px solid #ccc;
            display: inline-block;
            margin-right: 5px;
            vertical-align: middle;
        }}
        .color-box.red {{ background-color: #8B0000; }}
        .color-box.green {{ background-color: #006400; }}
        .color-box.yellow {{ background-color: #FFD700; }}

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

            if current_date == 0:
                day_classes += " empty"
                day_number_content = ""
            else:
                is_purchase_date = (current_date == fecha_compra)
                is_new_delivery_date = (new_fecha_entrega and current_date == new_fecha_entrega)
                is_original_delivery_date_input = (fecha_entrega_original_date and current_date == fecha_entrega_original_date)

                if st.session_state.recalculo_enabled:
                    if is_new_delivery_date and is_purchase_date: # NEW: Red/Yellow split for new delivery and purchase
                        day_classes += " highlight-recalc-new-delivery-and-purchase"
                        label_content = "<small class='label-text'>Compra / Nueva Entrega</small>"
                    elif is_new_delivery_date and is_original_delivery_date_input:
                        day_classes += " highlight-recalc-same-date"
                        label_content = "<small class='label-text'>Se mantiene fecha</small>"
                    elif is_new_delivery_date:
                        day_classes += " highlight-recalc-new-delivery"
                        label_content = "<small class='label-text'>Nueva Entrega</small>"
                    
                    # Highlight original delivery in green if it's not the new delivery date AND not purchase date
                    # to avoid over-highlighting if purchase date also on this day
                    if is_original_delivery_date_input and not is_new_delivery_date and not (is_new_delivery_date and is_purchase_date):
                        if "highlight-original-delivery" not in day_classes:
                            day_classes += " highlight-original-delivery"
                        if not label_content or ("Entrega Original" not in label_content and "Compra" not in label_content and "Nueva Entrega" not in label_content): # Ensure not to overwrite other labels
                            label_content = "<small>Entrega Original</small>"
                        elif "Entrega Original" not in label_content:
                            label_content += "<br><small>Entrega Original</small>"
                            
                    # Purchase date always gets highlighted if not already covered by higher priority
                    if is_purchase_date and not (is_new_delivery_date and is_purchase_date) and not is_new_delivery_date and not is_original_delivery_date_input:
                        if "highlight-purchase" not in day_classes: # Ensure it's not added twice
                            day_classes += " highlight-purchase"
                        if not label_content or ("Compra" not in label_content and "Entrega Original" not in label_content and "Nueva Entrega" not in label_content):
                            label_content = "<small>Compra</small>"
                        elif "Compra" not in label_content: # Append if another label is there
                             label_content += "<br><small>Compra</small>"


                else: # Recalculo is OFF (original logic)
                    if is_purchase_date and is_new_delivery_date:
                        day_classes += " highlight-both"
                        label_content = f"""
                        <div class="label-container">
                            <span class="label-combined">Mismo Día</span>
                        </div>
                        """
                    elif is_purchase_date:
                        day_classes += " highlight-purchase"
                        label_content = "<small>Compra</small>"
                    elif is_new_delivery_date:
                        day_classes += " highlight-delivery"
                        label_content = "<small>Entrega</small>"
            
            final_day_content = f"{day_number_content}{label_content}" if day != 0 else ""
            
            calendar_html += f'<div class="{day_classes}">{final_day_content}</div>'

    calendar_html += """
        </div>
    </div>
    """
    st.markdown(calendar_html, unsafe_allow_html=True)

    # Date Legend
    st.markdown("---")
    st.markdown("**Leyenda de Fechas:**")
    st.markdown(f'<div class="color-box red"></div> **Roja** Fecha de Compra: {fecha_compra.strftime("%d-%B-%Y")}', unsafe_allow_html=True)
    
    if st.session_state.recalculo_enabled:
        if fecha_entrega_original_date:
            st.markdown(f'<div class="color-box green"></div> **Verde** Fecha de Entrega Original: {fecha_entrega_original_date.strftime("%d-%B-%Y")}', unsafe_allow_html=True)
        else:
            st.markdown('<div class="color-box green"></div> **Verde** Fecha de Entrega Original: No disponible', unsafe_allow_html=True)
            
        if new_fecha_entrega:
            st.markdown(f'<div class="color-box yellow"></div> **Amarillo** NUEVA Fecha de Entrega: {new_fecha_entrega.strftime("%d-%B-%Y")}', unsafe_allow_html=True)
        else:
            st.markdown('<div class="color-box yellow"></div> **Amarillo** NUEVA Fecha de Entrega: No disponible', unsafe_allow_html=True)
    else: # Non-recalulo mode
        if new_fecha_entrega:
            st.markdown(f'<div class="color-box green"></div> **Verde** Fecha de Entrega: {new_fecha_entrega.strftime("%d-%B-%Y")}', unsafe_allow_html=True)
        else:
            st.markdown('<div class="color-box green"></div> **Verde** Fecha de Entrega: No disponible', unsafe_allow_html=True)


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
