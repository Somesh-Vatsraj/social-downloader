FROM php:8.2-cli-alpine

RUN apk add --no-cache \
    python3 \
    py3-pip \
    ffmpeg \
    curl \
    ca-certificates \
    bash

# Deno
RUN curl -fsSL https://deno.land/install.sh | sh

ENV PATH="/root/.deno/bin:${PATH}"

# yt-dlp + EJS
RUN pip3 install --break-system-packages -U "yt-dlp[default]"

WORKDIR /app

COPY . /app

RUN mkdir -p /app/downloads

EXPOSE 10000

CMD ["php", "-S", "0.0.0.0:10000", "-t", "/app"]