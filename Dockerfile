# ---------- Этап 1: Сборка React ----------
FROM node:18 AS frontend-builder
WORKDIR /app

# Копируем package.json и устанавливаем зависимости
COPY frontend/package.json frontend/package-lock.json* /app/frontend/
WORKDIR /app/frontend
RUN npm install

# Копируем весь фронтенд и собираем его
COPY frontend/ /app/frontend/
RUN npm run build

# ---------- Этап 2: Бэкенд ----------
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && rm -rf /var/lib/apt/lists/*

# Копируем requirements.txt из корня проекта (не из backend)
COPY requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Копируем весь код бэкенда
COPY backend/ /app/backend/

# Копируем собранный фронтенд (папка static) из первого этапа
COPY --from=frontend-builder /app/backend/static /app/backend/static

EXPOSE 5000

CMD ["gunicorn", "--worker-class", "sync", "-w", "1", "--bind", "0.0.0.0:5000", "backend.app:app"]
