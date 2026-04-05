FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app/     ./app/
COPY frontend/ ./frontend/

# Create data dir
RUN mkdir -p /app/data

WORKDIR /app/app

# Environment
ENV PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["python", "main.py"]
