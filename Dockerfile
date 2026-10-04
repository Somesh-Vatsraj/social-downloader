FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV WHISPER_MODEL=tiny
RUN python -c "from faster_whisper import WhisperModel; \
    WhisperModel('tiny', device='cpu', compute_type='int8')"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000 \
    HINDI_VOICE=hi-IN-SwaraNeural

RUN mkdir -p /tmp/kuaishou_dub

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /tmp/kuaishou_dub
USER appuser

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:10000/health || exit 1

CMD ["python", "app.py"]
