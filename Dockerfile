FROM python:3.12-slim

# System packages
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Application
COPY app.py .

# Render provides PORT
ENV PYTHONUNBUFFERED=1

# Start FastAPI
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
