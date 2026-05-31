# Этап 1: сборка React
FROM node:18 AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* /app/frontend/
WORKDIR /app/frontend
RUN npm install
COPY frontend/ /app/frontend/
RUN npm run build

# Этап 2: бэкенд
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/

# Копируем собранный фронтенд из /app/frontend/build в backend/static
COPY --from=frontend-builder /app/frontend/build/. /app/backend/static/

EXPOSE 5000
CMD gunicorn --worker-class sync -w 1 --bind 0.0.0.0:${PORT:-10000} backend.app:app
