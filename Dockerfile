FROM python:3.11-slim

# Evita que o Python gere arquivos .pyc e forca flush imediato nos logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Configuracoes de producao do Streamlit para Cloud Run e Firebase Hosting
ENV STREAMLIT_SERVER_PORT=8080
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ENABLE_CORS=false
ENV STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Instala dependencias de sistema necessarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia requisitos e instala dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o codigo da aplicacao
COPY . .

# Expõe a porta usada pelo Cloud Run
EXPOSE 8080

# Executa o Streamlit respeitando dinamicamente a variavel $PORT do Cloud Run
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0"]
