# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Install system dependencies: Node.js, npm, and ffmpeg
RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install the bgutil PO Token provider globally using npm
# This is the service that will run in the background to generate PO tokens.
RUN npm install -g bgutil-ytdlp-pot-provider

# Copy the requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Expose the port the app runs on
EXPOSE 10000

# Command to run the application
# We start the PO token provider server in the background, then start the Flask app.
CMD node /usr/local/lib/node_modules/bgutil-ytdlp-pot-provider/server/build/main.js & python app.py
