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
    MCP_HTTP_HOST=0.0.0.0

# Expose HTTP transport port
EXPOSE 8085

# Startup script
COPY <<-EOT /app/start.sh
#!/bin/bash
exec uv run main.py
EOT
RUN chmod +x /app/start.sh

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

CMD ["/app/start.sh"]
