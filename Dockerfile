FROM python:3.12-slim

# System packages
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh

ENV DENO_INSTALL=/root/.deno
ENV PATH="/root/.deno/bin:$PATH"

# App directory
WORKDIR /app

# Dependencies
COPY requirements.txt .

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    yt-dlp \
    yt-dlp-ejs \
    python-multipart

# Application
COPY app.py .

ENV PYTHONUNBUFFERED=1

# Render PORT
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
