FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

ENV PYTHONUNBUFFERED=1 PORT=10000
EXPOSE 10000

CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT} \
    --worker-class gthread \
    --workers 2 \
    --threads 4 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile -
