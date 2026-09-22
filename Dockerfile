FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# =====================================================
# System packages
# =====================================================

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    git \
    nodejs \
    npm \
    unzip \
    && rm -rf /var/lib/apt/lists/*


# =====================================================
# Install Deno directly
# =====================================================

RUN curl -fsSL https://dl.deno.land/release/v2.5.6/deno-x86_64-unknown-linux-gnu.zip \
    -o /tmp/deno.zip \
    && unzip /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip

RUN deno --version


# =====================================================
# Python dependencies
# =====================================================

COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt


# =====================================================
# BgUtils PO Token Provider
# =====================================================

RUN git clone --depth 1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil


# =====================================================
# Build BgUtils server
# =====================================================

WORKDIR /opt/bgutil/server

RUN npm ci \
    && npx tsc


# =====================================================
# Application
# =====================================================

WORKDIR /app

COPY app.py .


# =====================================================
# Environment
# =====================================================

ENV YTDL_POT_PROVIDER_URL=http://127.0.0.1:4416


# =====================================================
# Start BgUtils + FastAPI
# =====================================================

CMD ["sh", "-c", "node /opt/bgutil/server/build/main.js --host 127.0.0.1 --port 4416 & sleep 5 && python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
