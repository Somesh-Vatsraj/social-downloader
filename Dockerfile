# Use an official PHP runtime as a parent image
FROM php:8.4-apache

# Set the working directory
WORKDIR /var/www/html

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    libpng-dev \
    libonig-dev \
    libxml2-dev \
    zip \
    unzip \
    python3 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install PHP extensions
RUN docker-php-ext-install pdo_mysql mbstring exif pcntl bcmath gd

# Install yt-dlp
RUN pip3 install --upgrade yt-dlp

# Enable Apache mod_rewrite
RUN a2enmod rewrite

# Copy the application code
COPY . /var/www/html

# Set permissions for Apache
RUN chown -R www-data:www-data /var/www/html

# Expose port 80 (Render will map its dynamic PORT to this)
EXPOSE 80

# Start Apache in the foreground
CMD ["apache2-foreground"]
