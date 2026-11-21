# MoneyTrace API — Cloud Run image (also runs locally: docker run -p 8000:8080 -e PORT=8080 ...)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY public /app/public
WORKDIR /app/backend

# No database is baked into the image: Cloud Run is stateless. Schema migrations run at start-up
# against DATABASE_URL (Neon / Cloud SQL Postgres); agent sessions live in Firestore.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

ENV PORT=8080 AGENT_ENGINE=adk SESSION_BACKEND=auto OTEL_EXPORTER=gcp
EXPOSE 8080
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn moneytrace.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers"]
