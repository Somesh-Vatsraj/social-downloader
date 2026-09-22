FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Deno
RUN curl -fsSL https://deno.land/install.sh | sh

ENV DENO_INSTALL=/root/.deno
ENV PATH="/root/.deno/bin:$PATH"

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -U "yt-dlp[default]"

COPY app.py .

ENV PYTHONUNBUFFERED=1

CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
