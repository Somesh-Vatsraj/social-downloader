FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Basic system packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       curl \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh

ENV PATH="/root/.deno/bin:${PATH}"

# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py .

# Create non-root user
RUN useradd -m appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /root/.deno

USER appuser

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
