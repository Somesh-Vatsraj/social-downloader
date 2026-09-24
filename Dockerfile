FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ----------------------------------------
# System packages
# ----------------------------------------

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------------------
# Install Deno
# ----------------------------------------

RUN curl -fsSL https://deno.land/install.sh | sh

ENV PATH="/root/.deno/bin:${PATH}"

# ----------------------------------------
# Python dependencies
# ----------------------------------------

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# ----------------------------------------
# Application
# ----------------------------------------

COPY main.py .

# ----------------------------------------
# Non-root user
# ----------------------------------------

RUN useradd -m appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /root/.deno

USER appuser

# ----------------------------------------
# Port
# ----------------------------------------

EXPOSE 8080

# ----------------------------------------
# Start FastAPI
# ----------------------------------------

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
