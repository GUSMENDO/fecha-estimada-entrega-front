# Use the official lightweight Python image.
# https://hub.docker.com/_/python
FROM python:3.11-slim

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./
COPY requirements.txt ./

# Install production dependencies.
RUN pip install -r requirements.txt

# Expone el puerto en el que Streamlit se ejecutará
# Cloud Run requiere que tu aplicación escuche en el puerto especificado por la variable de entorno PORT
ENV PORT 8080
EXPOSE 8080

# Comando para ejecutar la aplicación Streamlit
# --server.port $PORT asegura que Streamlit escuche en el puerto correcto de Cloud Run
# --server.enableCORS false y --server.enableXsrfProtection false son necesarios para Streamlit en Cloud Run
CMD ["streamlit", "run", "app.py", "--server.port", "8080", "--server.enableCORS", "false", "--server.enableXsrfProtection", "false"]
