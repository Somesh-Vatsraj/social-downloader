FROM php:8.2-cli-alpine

# System deps + Python (yt-dlp ke liye)
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    curl \
    bash \
    ca-certificates \
    && rm -rf /var/cache/apk/*

# yt-dlp install
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp \
    && chmod +x /usr/local/bin/yt-dlp

# PHP extensions
RUN docker-php-ext-install -j$(nproc) \
    && apk add --no-cache --virtual .build-deps $PHPIZE_DEPS \
    && apk del .build-deps

# Workdir
WORKDIR /app

# Copy files
COPY . /app

# Render PORT env use karega
EXPOSE 8080

# PHP built-in server (production ke liye theek hai chhoti API ke liye)
CMD php -S 0.0.0.0:${PORT:-8080} router.php
