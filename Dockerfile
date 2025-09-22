# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for markitdown and other tools
RUN apt-get update && apt-get install -y \
    # PDF processing dependencies
    poppler-utils \
    # Image processing dependencies
    libmagic1 \
    # Network tools
    curl \
    # Audio/video processing tools for pydub
    ffmpeg \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies
RUN uv pip install --system -e .

# Copy application code
COPY main.py ./

# Copy all project files (excluding what's in .dockerignore)
COPY . ./

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV OLLAMA_HOST=http://host.docker.internal:11434

# Expose port (if needed for future HTTP interface)
EXPOSE 8080

# Default command
CMD ["python", "main.py"]