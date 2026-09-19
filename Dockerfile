FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy application files
COPY backend /app/backend
COPY public /app/public

WORKDIR /app/backend

# Initialize SQLite database schema
RUN python -c "from moneytrace.db.database import init_db; init_db(force_reseed=False)"

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn moneytrace.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
