FROM php:8.2-cli

RUN apt-get update && \
    apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages -U yt-dlp

WORKDIR /app

COPY . /app

RUN mkdir -p /app/downloads

EXPOSE 10000

CMD ["php", "-S", "0.0.0.0:10000", "-t", "/app"]