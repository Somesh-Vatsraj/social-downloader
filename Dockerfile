FROM python:3.11-slim

# Install FFmpeg (for audio/format handling) + unzip (required by Deno installer) + curl
RUN apt-get update && apt-get install -y ffmpeg curl unzip && rm -rf /var/lib/apt/lists/*

# Install Deno as JS runtime for yt-dlp's n-challenge solver
ENV DENO_INSTALL=/usr/local
RUN curl -fsSL https://deno.land/install.sh | sh

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use JSON array form for CMD (fixes the JSONArgsRecommended warning)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
