FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GOODGAME_STATIC_DIR=/app/static \
    GOODGAME_ENV=production

WORKDIR /app

COPY requirements-serving.txt .
RUN pip install --no-cache-dir -r requirements-serving.txt

RUN mkdir -p /app/goodgame
COPY goodgame/__init__.py ./goodgame/__init__.py
COPY goodgame/web.py ./goodgame/web.py
COPY goodgame/serving ./goodgame/serving
COPY demo_data ./demo_data
COPY static ./static

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["sh", "-c", "uvicorn goodgame.web:app --host 0.0.0.0 --port ${PORT:-8080}"]
