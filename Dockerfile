FROM php:8.2-cli

RUN apt-get update && \
    apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno - JavaScript runtime required by current yt-dlp YouTube extraction
RUN curl -fsSL https://deno.land/install.sh | sh

ENV PATH="/root/.deno/bin:${PATH}"

# yt-dlp + EJS support
RUN pip3 install --break-system-packages -U "yt-dlp[default]"

WORKDIR /app

COPY . /app

RUN mkdir -p /app/downloads

EXPOSE 10000

CMD ["php", "-S", "0.0.0.0:10000", "-t", "/app"]