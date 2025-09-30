# Use Python 3.11 slim image as base
FROM python:3.11-slim AS python-base

# Stage to pull bgutil provider assets
FROM brainicism/bgutil-ytdlp-pot-provider AS bgutil-provider

# Final image
FROM python-base

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
    # Node.js runtime for embedded bgutil provider
    nodejs \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies
RUN uv sync

# Copy application code
COPY main.py ./

# Copy all project files (excluding what's in .dockerignore)
COPY . ./

# Copy bgutil provider app from the provider image
COPY --from=bgutil-provider /app /opt/bgutil

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=http://host.docker.internal:11434 \
    UV_CACHE_DIR=/app/.cache/uv

# Expose ports
EXPOSE 8085

# Prep cache directory for uv
RUN mkdir -p /app/.cache/uv

# Create a startup script
RUN echo '#!/bin/bash\n# Start the embedded bgutil provider in background on :4416\nnode /opt/bgutil/build/main.js &\n# Start the main application\nexec uv run main.py' > /app/start.sh

# Make the startup script executable
RUN chmod +x /app/start.sh

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

# Switch to appuser for the remaining operations
USER appuser

# Default command
CMD ["/app/start.sh"]
