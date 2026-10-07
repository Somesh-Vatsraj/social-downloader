FROM python:3.12-slim

# System deps: ffmpeg + curl + deno ke liye unzip
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno install (yt-dlp JS runtime)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && ln -sf /usr/local/bin/deno /usr/bin/deno \
    && deno --version

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# yt-dlp ko nightly pe update (stable 403 deta hai)
RUN pip install --no-cache-dir -U --pre "yt-dlp[default]"

# App code
COPY app.py .

ENV PYTHONUNBUFFERED=1 \
    PORT=10000 \
    DENO_DIR=/tmp/deno

EXPOSE 10000

# Gunicorn: streaming ke liye gthread + long timeout
CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT} \
    --worker-class gthread \
    --workers 2 \
    --threads 4 \
    --timeout 600 \
    --graceful-timeout 120 \
    --keep-alive 65 \
    --access-logfile - \
    --error-logfile -
