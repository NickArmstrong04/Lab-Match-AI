# Use an optimized, official Python lightweight image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code into a subfolder to treat it as a package
COPY . ./backend

# Expose port
EXPOSE 8080

# Run uvicorn on port 8080 referencing the package
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
