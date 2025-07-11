import streamlit as st
import pandas as pd
import json
import requests # Para hacer llamadas a la API
import datetime # Para trabajar con fechas
import calendar # Para generar el calendario

# --- Conexión a BigQuery ---
# Asegúrate de que tu entorno esté autenticado con Google Cloud.
# Por ejemplo, usando `gcloud auth application-default login` en tu terminal,
# o configurando la variable de entorno GOOGLE_APPLICATION_CREDENTIALS
# con la ruta a un archivo de credenciales de cuenta de servicio.

@st.cache_resource # Cacha el cliente de BigQuery para que se inicialice una sola vez
def get_bigquery_client():
    """
    Initializes and returns the BigQuery client.
    """
    try:
        client = bigquery.Client()
        return client
    except Exception as e:
        st.error(f"Error al inicializar el cliente de BigQuery. Asegúrate de estar autenticado y tener los permisos correctos: {e}")
        return None

bigquery_client = get_bigquery_client()


# --- Consulta a BigQuery ---
def query_bigquery(sku_val: int, cp_val: int) -> pd.DataFrame:
    """
    Performs a real BigQuery query.
    """
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
    st.code(query, language="sql") # Shows the SQL query for debugging

    try:
        query_job = bigquery_client.query(query)
        results = query_job.to_dataframe()
        return results
    except Exception as e:
        st.error(f"Error al ejecutar la consulta en BigQuery: {e}")
        return pd.DataFrame()

# --- Llamada a la API de Rutas ---
def call_route_api(sku: str, cp: str, qty: int, weights: dict) -> dict:
    """
    Performs a real call to the route API.
    """
    api_url = 'https://cloudrun-service-fee-316812040520.us-east4.run.app/fecha-estimada-entrega'
    headers = {'Content-Type': 'application/json'}
    payload = {
        "sku": sku,
        "cp": cp,
        "qty": qty,
        "weights": weights # Now sending the weights dictionary
    }

    st.info(f"Llamando a la API de rutas en: {api_url} con payload: {payload}...")

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status() # Raises an exception for HTTP errors (4xx or 5xx)
        
        json_response = response.json()
        
        # Check for the specific error formats from the API
        if "error" in json_response: # Handles {"error": "..."}
            return {"api_error_message": json_response['error']} 
        elif "error:" in json_response: # Handles {"error:": "..."}
            return {"api_error_message": json_response['error:']}
        
        return json_response
    except requests.exceptions.RequestException as e:
        # Catch network or HTTP errors
        return {"api_error_message": f"Error de conexión o HTTP: {e}"}
    except json.JSONDecodeError as e:
        # Catch JSON decoding errors
        return {"api_error_message": f"Error al decodificar la respuesta JSON de la API: {e}. Respuesta: {response.text}"}


# --- Configuración de la Página de Streamlit ---
st.set_page_config(
    page_title="Consulta de Rutas y BigQuery",
    layout="wide", # Uses wide layout for better table visualization
    initial_sidebar_state="expanded"
)

st.title("Consulta de Rutas y Fecha Estimada de Entrega")
st.markdown("Esta aplicación te permite consultar información de Rutas y calcular las mejores Rutas de entrega a través de una API.")

# --- Sección de Inputs ---
st.sidebar.header("Parámetros de Consulta")

# Inputs for SKU and CP
sku_input = st.sidebar.text_input("SKU", value="1139002876", help="Product identification number.")
cp_input = st.sidebar.text_input("Código Postal (CP)", value="52715", help="Postal code for the query.")

# Additional inputs for the route API
qty_input = st.sidebar.number_input("Cantidad (QTY)", value=2, min_value=1, help="Quantity of product units.")

st.sidebar.markdown("---")
st.sidebar.header("Pesos de Optimización (Weights)")

# Define default weights
DEFAULT_WEIGHTS = {
    "inventario": 0.5,
    "tiempo": 1.0,
    "costo": 2.0,
    "nodo": 0.5,
    "ruta": 0.5
}

# Callback function to reset weights
def reset_weights_callback():
    for key, value in DEFAULT_WEIGHTS.items():
        st.session_state[key] = value
    st.session_state.show_reset_message = True # Set flag to show success message

# Initialize session state for weights if not already present
for key, value in DEFAULT_WEIGHTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# Initialize session state for the reset message flag
if 'show_reset_message' not in st.session_state:
    st.session_state.show_reset_message = False

# Sliders for weights using session state
inventario_weight = st.sidebar.slider("Inventario", min_value=0.0, max_value=2.0, value=st.session_state.inventario, step=0.1, key='inventario', help="Peso para la optimización por inventario.")
tiempo_weight = st.sidebar.slider("Tiempo", min_value=0.0, max_value=2.0, value=st.session_state.tiempo, step=0.1, key='tiempo', help="Peso para la optimización por tiempo.")
costo_weight = st.sidebar.slider("Costo", min_value=0.0, max_value=2.0, value=st.session_state.costo, step=0.1, key='costo', help="Peso para la optimización por costo.")
nodo_weight = st.sidebar.slider("Nodo", min_value=0.0, max_value=2.0, value=st.session_state.nodo, step=0.1, key='nodo', help="Peso para la optimización por nodo.")
ruta_weight = st.sidebar.slider("Ruta", min_value=0.0, max_value=2.0, value=st.session_state.ruta, step=0.1, key='ruta', help="Peso para la optimización por ruta.")

# Reset weights button with callback
st.sidebar.button("Restablecer Pesos", on_click=reset_weights_callback)

# Display reset success message if flag is true
if st.session_state.show_reset_message:
    st.sidebar.success("Pesos ajustados a default.")
    # Reset the flag so the message disappears on the next rerun (e.g., user interaction)
    st.session_state.show_reset_message = False


# Initialize session state for BigQuery DataFrame and API response if not already present
if 'bigquery_df' not in st.session_state:
    st.session_state.bigquery_df = pd.DataFrame()
if 'api_rutas_response' not in st.session_state:
    st.session_state.api_rutas_response = {}
if 'bigquery_query_attempted' not in st.session_state: # Initialize the flag
    st.session_state.bigquery_query_attempted = False

# --- Sección de Consulta a BigQuery ---
st.header("1. Resultados de Rutas")

# Function to highlight rows in the BigQuery table based on API trace IDs
def highlight_bigquery_results_by_trace_id(row, selected_trace_ids):
    # Check if 'ID_TRAZO' column exists in the row before trying to access it
    if 'ID_TRAZO' in row and row['ID_TRAZO'] in selected_trace_ids:
        # Use a distinct, bright color for highlighting selected routes (e.g., Gold)
        # and ensure text color is visible (e.g., black)
        return ['background-color: #FFD700; color: #000000'] * len(row)
    else:
        return [''] * len(row) # No special styling

if st.button("Consultar Rutas"):
    if sku_input and cp_input:
        try:
            sku_int = int(sku_input)
            cp_int = int(cp_input)
            st.session_state.bigquery_df = query_bigquery(sku_int, cp_int)
            st.session_state.bigquery_query_attempted = True # Set flag when query is attempted
            # Reset API response when BigQuery is queried again, so previous highlights are removed
            st.session_state.api_rutas_response = {} # Clear API response on new BQ query
        except ValueError:
            st.error("Error: SKU y/o Código Postal deben ser valores numéricos enteros para la consulta a BigQuery.")
            st.session_state.bigquery_query_attempted = False # Reset if input validation fails
    else:
        st.error("Por favor, introduce un SKU y un Código Postal para consultar BigQuery.")
        st.session_state.bigquery_query_attempted = False # Reset if inputs are missing

# Always display the BigQuery table if data exists in session state
if not st.session_state.bigquery_df.empty:
    st.subheader("Datos de Inventario y Ubicación")
    st.write(f"Número de registros: **{len(st.session_state.bigquery_df)}**") # Add count here
    # Determine which trace IDs to highlight from the API response stored in session state
    selected_trace_ids = set()
    if st.session_state.api_rutas_response and st.session_state.api_rutas_response.get("rutas"):
        selected_trace_ids = {ruta['id_trazo'] for ruta in st.session_state.api_rutas_response["rutas"]}

    st.dataframe(
        st.session_state.bigquery_df.style.apply(
            highlight_bigquery_results_by_trace_id,
            axis=1,
            selected_trace_ids=selected_trace_ids
        ),
        use_container_width=True,
        hide_index=True # Hide index for this table
    )
    st.markdown(
        "<p style='color: green; font-weight: bold;'>Las filas mostradas arriba son los resultados de la consulta a BigQuery.</p>",
        unsafe_allow_html=True
    )
else:
    st.info("Haz clic en 'Consultar Rutas' para cargar los datos de inventario y ubicación.")
    # Specific message when no records are found after a BigQuery query
    if st.session_state.bigquery_query_attempted: # Check the flag here
        st.warning("No existen registros con los parámetros proporcionados en BigQuery.")
    st.session_state.bigquery_query_attempted = False # Reset flag after displaying/not displaying warning

st.markdown("---") # Separador visual

# --- Sección de Consulta a la API de Rutas ---
st.header("2. Cálculo de la Mejor Ruta")

# Placeholder for the API button to control its position
api_button_col, _ = st.columns([0.2, 0.8]) # Adjust column width as needed
with api_button_col:
    calculate_route_button = st.button("Calcular Ruta")

# Display API error message directly below the button if present
if st.session_state.api_rutas_response and "api_error_message" in st.session_state.api_rutas_response:
    st.error(st.session_state.api_rutas_response["api_error_message"])

if calculate_route_button:
    if sku_input and cp_input and qty_input:
        try:
            # Frontend validation for the API inputs
            int(sku_input)
            int(cp_input)
            
            # Construct the weights dictionary from slider values
            weights_payload = {
                "inventario": inventario_weight,
                "tiempo": tiempo_weight,
                "costo": costo_weight,
                "nodo": nodo_weight,
                "ruta": ruta_weight
            }

            st.session_state.api_rutas_response = call_route_api(
                sku_input, cp_input, qty_input, weights_payload
            )
            # Rerun the app to re-render the BigQuery table with new highlights
            st.rerun()
        except ValueError:
            st.error("Error: SKU y/o Código Postal deben ser valores numéricos enteros para calcular la ruta.")
    else:
        st.error("Por favor, asegúrate de que SKU, CP y Cantidad estén completos para calcular la ruta.")

# --- Nueva sección de Calendario ---
if st.session_state.api_rutas_response and "api_error_message" not in st.session_state.api_rutas_response:
    st.subheader("Visualización de Fechas Clave")

    fecha_compra = datetime.date(2025, 6, 1) # Fixed purchase date (June 1, 2025)
    fecha_entrega = None
    
    # Get fecha_de_entrega from resumen instead of EDD1 from rutas
    if st.session_state.api_rutas_response.get("resumen"):
        resumen_data = st.session_state.api_rutas_response["resumen"]
        if "fecha_de_entrega" in resumen_data: # Assuming this key exists in resumen
            try:
                # Convert 'YYYY-MM-DD' string to datetime.date object
                fecha_entrega = datetime.datetime.strptime(resumen_data["fecha_de_entrega"], "%Y-%m-%d").date()
            except ValueError:
                st.warning("Formato de fecha de entrega (fecha_de_entrega) inválido en la respuesta de la API. Se esperaba 'YYYY-MM-DD'.")
        elif "tiempo_maximo_dias" in resumen_data: # Fallback if fecha_de_entrega is not direct
            # If fecha_de_entrega is not directly available, but tiempo_maximo_dias is,
            # we can approximate the delivery date from purchase date + days.
            # This is an assumption based on typical API responses.
            delivery_days = resumen_data["tiempo_maximo_dias"]
            fecha_entrega = fecha_compra + datetime.timedelta(days=delivery_days)
            st.info(f"Fecha de entrega aproximada calculada a partir de tiempo_maximo_dias: {fecha_entrega.strftime('%d-%B-%Y')}")


    # Generate calendar HTML
    cal = calendar.Calendar(firstweekday=6) # Sunday as first day of the week
    
    # Determine the year and month to display in the calendar
    display_year = fecha_compra.year
    display_month = fecha_compra.month
    if fecha_entrega and (fecha_entrega.year != fecha_compra.year or fecha_entrega.month != fecha_compra.month):
        # If delivery date is in a different month/year, display the month of delivery
        display_year = fecha_entrega.year
        display_month = fecha_entrega.month

    month_cal = cal.monthdayscalendar(display_year, display_month)

    calendar_html = f"""
    <style>
        .calendar-container {{
            font-family: Arial, sans-serif;
            background-color: #262730; /* Dark background */
            color: #ffffff; /* White text */
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            max-width: 500px; /* Adjust as needed */
            margin: auto;
        }}
        .calendar-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}
        .calendar-header h3 {{
            margin: 0;
            font-size: 1.5em;
            color: #ffffff;
        }}
        .calendar-weekdays {{
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            text-align: center;
            font-weight: bold;
            margin-bottom: 10px;
            color: #bbbbbb; /* Lighter grey for weekdays */
        }}
        .calendar-day-grid {{
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 5px;
            text-align: center;
        }}
        .calendar-day {{
            padding: 10px 5px;
            border-radius: 5px;
            background-color: #33343d; /* Slightly lighter dark for day cells */
            color: #ffffff;
            font-size: 0.9em;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 50px; /* Ensure consistent height */
        }}
        .calendar-day.empty {{
            background-color: transparent;
            color: #555555; /* Dimmer for empty days */
        }}
        .calendar-day.highlight-purchase {{
            background-color: #8B0000; /* Dark Red for Purchase */
            color: #ffffff;
            font-weight: bold;
            box-shadow: 0 0 8px rgba(255, 0, 0, 0.5);
        }}
        .calendar-day.highlight-delivery {{
            background-color: #006400; /* Dark Green for Delivery */
            color: #ffffff;
            font-weight: bold;
            box-shadow: 0 0 8px rgba(0, 255, 0, 0.5);
        }}
        /* Responsive adjustments */
        @media (max-width: 600px) {{
            .calendar-day {{
                min-height: 40px;
                font-size: 0.8em;
            }}
            .calendar-header h3 {{
                font-size: 1.2em;
            }}
        }}
    </style>
    <div class="calendar-container">
        <div class="calendar-header">
            <h3>{calendar.month_name[display_month]} {display_year}</h3>
            <div>
                <!-- Add navigation buttons if desired, but for fixed month, not strictly needed -->
                <!-- <button>&lt;</button> <button>&gt;</button> -->
            </div>
        </div>
        <div class="calendar-weekdays">
            <span>Dom</span><span>Lun</span><span>Mar</span><span>Mié</span><span>Jue</span><span>Vie</span><span>Sáb</span>
        </div>
        <div class="calendar-day-grid">
    """

    # Populate days
    for week in month_cal:
        for day in week:
            day_classes = "calendar-day"
            day_content = str(day) if day != 0 else ""

            current_date = None
            if day != 0:
                current_date = datetime.date(display_year, display_month, day)

            if current_date == fecha_compra:
                day_classes += " highlight-purchase"
                day_content += "<br><small>Compra</small>"
            elif fecha_entrega and current_date == fecha_entrega:
                day_classes += " highlight-delivery"
                day_content += "<br><small>Entrega</small>"
            elif day == 0:
                day_classes += " empty"
                day_content = "" # No content for empty days

            calendar_html += f'<div class="{day_classes}">{day_content}</div>'

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

    st.markdown("---") # Separador visual antes de los resultados de la API
    
    # Display API results only if there's no specific API error message
    # Moved this block inside the calendar condition to ensure it only shows with valid API data
    # Presentar los Inputs de la Consulta a la API en una tabla más presentable
    st.subheader("Inputs de la Consulta a la API")
    inputs_data = st.session_state.api_rutas_response.get("inputs", {})
    if inputs_data:
        inputs_df = pd.DataFrame(inputs_data.items(), columns=['Variable', 'Valor'])
        st.dataframe(
            inputs_df,
            hide_index=True, # Hide index for this table
            use_container_width=True,
            column_config={
                "Variable": st.column_config.Column(
                    "Variable",
                    width="fit_content" # Adjust to content
                ),
                "Valor": st.column_config.Column(
                    "Valor",
                    width="auto" # Take remaining space
                )
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
            hide_index=True # Hide index for this table
        )
        st.markdown(
            "<p style='color: green; font-weight: bold;'>Las rutas mostradas arriba son las rutas de la API.</p>",
            unsafe_allow_html=True
        )
    else:
        st.info("La API no devolvió rutas para los inputs proporcionados.")

    # Presentar el Resumen de la Consulta en una tabla más presentable
    st.subheader("Resumen de la Consulta")
    resumen_data = st.session_state.api_rutas_response.get("resumen", {})
    if resumen_data:
        resumen_df = pd.DataFrame(resumen_data.items(), columns=['Métrica', 'Valor'])
        st.dataframe(
            resumen_df,
            hide_index=True, # Hide index for this table
            use_container_width=True,
            column_config={
                "Métrica": st.column_config.Column(
                    "Métrica",
                    width="fit_content" # Adjust to content
                ),
                "Valor": st.column_config.Column(
                    "Valor",
                    width="auto" # Take remaining space
                )
            }
        )
    else:
        st.warning("No se pudo obtener el resumen de la consulta de la API.")
