FROM selenium/standalone-chrome:latest

USER root

# Instalar Python y pip
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Crear entorno virtual para evitar conflictos con paquetes del sistema
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV PORT=8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "3600", "--workers", "1", "app:app"]