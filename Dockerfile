FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GOODGAME_STATIC_DIR=/app/static

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY goodgame ./goodgame
COPY demo_data ./demo_data
COPY static ./static

CMD ["sh", "-c", "uvicorn goodgame.web:app --host 0.0.0.0 --port ${PORT:-8080}"]
