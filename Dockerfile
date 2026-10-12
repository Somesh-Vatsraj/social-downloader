
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN useradd --create-home appuser \
    && mkdir -p /tmp/instasave \
    && chown -R appuser:appuser /app /tmp/instasave

USER appuser

EXPOSE 10000

CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120"]
