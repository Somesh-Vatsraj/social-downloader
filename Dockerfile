FROM php:8.2-cli-alpine

# System deps + Python + ffmpeg
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    curl \
    bash \
    ca-certificates \
    procps \
    && rm -rf /var/cache/apk/*

# yt-dlp install
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp \
    && chmod +x /usr/local/bin/yt-dlp \
    && yt-dlp --version

# PHP extensions
RUN docker-php-ext-install -j$(nproc) \
    pcntl \
    posix

WORKDIR /app

COPY . /app

EXPOSE 8080

CMD php -S 0.0.0.0:${PORT:-8080} router.php
