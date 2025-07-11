import streamlit as st
import pandas as pd
import json
import requests # Para hacer llamadas a la API
from google.cloud import bigquery # Para interactuar con BigQuery
from google.oauth2 import service_account # Opcional: para autenticación con Service Account

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
def call_route_api(sku: str, cp: str, qty: int, flag_vn: bool) -> dict:
    """
    Performs a real call to the route API.
    """
    api_url = 'https://cloudrun-service-fee-316812040520.us-east4.run.app/fecha-estimada-entrega'
    headers = {'Content-Type': 'application/json'}
    payload = {
        "sku": sku,
        "cp": cp,
        "qty": qty,
        "flag_vn": flag_vn
    }

    st.info(f"Llamando a la API de rutas en: {api_url} con payload: {payload}...")

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status() # Raises an exception for HTTP errors (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error al conectar o recibir respuesta de la API de rutas: {e}")
        return {}
    except json.JSONDecodeError as e:
        st.error(f"Error al decodificar la respuesta JSON de la API: {e}. Respuesta: {response.text}")
        return {}


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
flag_vn_input = st.sidebar.checkbox("Flag VN", value=False, help="Indicates if it's a new sale (true) or not (false).")

# Initialize session state for BigQuery DataFrame and API response if not already present
if 'bigquery_df' not in st.session_state:
    st.session_state.bigquery_df = pd.DataFrame()
if 'api_rutas_response' not in st.session_state:
    st.session_state.api_rutas_response = {}

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
            # Reset API response when BigQuery is queried again, so previous highlights are removed
            st.session_state.api_rutas_response = {}
        except ValueError:
            st.error("Error: SKU y/o Código Postal deben ser valores numéricos enteros para la consulta a BigQuery.")
    else:
        st.error("Por favor, introduce un SKU y un Código Postal para consultar BigQuery.")

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

st.markdown("---") # Separador visual

# --- Sección de Consulta a la API de Rutas ---
st.header("2. Cálculo de la Mejor Ruta")

if st.button("Calcular Ruta"):
    if sku_input and cp_input and qty_input:
        try:
            # Frontend validation for the API inputs
            int(sku_input)
            int(cp_input)
            st.session_state.api_rutas_response = call_route_api(sku_input, cp_input, qty_input, flag_vn_input)
            # Rerun the app to re-render the BigQuery table with new highlights
            st.rerun()
        except ValueError:
            st.error("Error: SKU y/o Código Postal deben ser valores numéricos enteros para calcular la ruta.")
    else:
        st.error("Por favor, asegúrate de que SKU, CP y Cantidad estén completos para calcular la ruta.")

# Display API results if available in session state
if st.session_state.api_rutas_response:
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
