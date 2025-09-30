# Minimal image: MarkItDown MCP server only (no embedded bgutil)
# Use this when running bgutil provider as a separate container

FROM python:3.11-slim

WORKDIR /app

# System dependencies for markitdown and helpers
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libmagic1 \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Faster Python deps with uv
RUN pip install uv

# Copy dependency metadata and install
COPY pyproject.toml ./
RUN uv sync

# Copy application code
COPY . ./

# Environment
ENV PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=http://host.docker.internal:11434 \
    MCP_TRANSPORT=stdio \
    MCP_HTTP_PORT=8085 \
    MCP_HTTP_HOST=0.0.0.0 \
    UV_CACHE_DIR=/app/.cache/uv

# Expose HTTP transport port
EXPOSE 8085

# Prep cache directory for uv
RUN mkdir -p /app/.cache/uv

# Create a startup script
RUN echo '#!/bin/bash\nexec uv run main.py' > /app/start.sh
RUN chmod +x /app/start.sh

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

CMD ["/app/start.sh"]
