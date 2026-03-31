FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repo root — requirements.txt lives in backend/
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

EXPOSE 8000
# Use $PORT injected by Railway; fall back to 8000 for local docker run
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --log-level info
