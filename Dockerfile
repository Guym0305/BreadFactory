# Use minimal official Python runtime
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    FORWARDED_ALLOW_IPS=*

WORKDIR /app

# Install system dependencies needed for compilation / SQLite
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port 8080 (Google Cloud Run default)
EXPOSE 8080

# Execute Gunicorn with Uvicorn workers
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 --forwarded-allow-ips="*" -k uvicorn.workers.UvicornWorker app.main:app
