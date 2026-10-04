# ---------- Base image ----------
FROM python:3.11-slim

# ---------- System dependencies ----------
# ffmpeg  → audio extract + merge
# git     → kuch pip packages ke liye
# curl    → health checks / debugging
# ca-certificates → HTTPS API calls
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------- Working directory ----------
WORKDIR /app

# ---------- Python deps (layer caching ke liye pehle) ----------
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---------- App code ----------
COPY app.py .

# ---------- Whisper model pre-download (optional but recommended) ----------
# Yeh build ke waqt model download kar dega, taaki pehli request fast ho.
# WHISPER_MODEL=tiny default hai (Render free 512MB ke liye safe).
ENV WHISPER_MODEL=tiny
RUN python -c "from faster_whisper import WhisperModel; \
    WhisperModel('tiny', device='cpu', compute_type='int8')"

# ---------- Runtime env ----------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000 \
    HINDI_VOICE=hi-IN-SwaraNeural

# ---------- Temp dir for jobs ----------
RUN mkdir -p /tmp/kuaishou_dub

# ---------- Non-root user (security) ----------
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app /tmp/kuaishou_dub
USER appuser

# ---------- Expose port ----------
EXPOSE 10000

# ---------- Health check ----------
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:10000/health || exit 1

# ---------- Run ----------
CMD ["python", "app.py"]
