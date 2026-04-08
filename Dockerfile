FROM python:3.11-slim

# Instalar dependencias del sistema y Google Chrome directamente
RUN apt-get update && apt-get install -y wget gnupg unzip \
    && wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Agregamos un timeout largo (900s = 15 min) para el scraping profundo
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app", "--timeout", "900"]