FROM python:3.14-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create data directory
RUN mkdir -p /app/data

# Set environment variables
ENV SNIPPEN_DOORMAN_DATABASE_PATH=/app/data/doorman.db

# Run the service
CMD ["python", "-m", "snippen_doorman.main"]
