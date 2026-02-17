FROM python:3.12-slim

WORKDIR /app

# Installa dipendenze di sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements e installa
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice
COPY . .

# Espone la porta di Streamlit
EXPOSE 7860

# Comando di avvio
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
