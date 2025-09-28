# MCP-MarkItDown

An MCP server that uses Microsoft's MarkItDown package to fetch documents from the internet (PDF, DOCX, PPTX, XLSX, etc.) and convert them to markdown format.

## Features

- Converts various file types to Markdown:
  - PDF documents
  - Word documents (docx)
  - PowerPoint presentations (pptx)
  - Excel spreadsheets (xlsx)
  - HTML pages
  - YouTube video transcripts with enhanced reliability
  - Image files with AI-powered captioning (when Ollama is available)

- Preserves document structure for better LLM processing
- Advanced YouTube transcript extraction with SABR protection bypass
- Automatic deduplication of transcript content
- Pagination support for large YouTube transcripts
- Robust fallback mechanisms (youtube-transcript-api → yt-dlp)
- Provides proper error handling and content-type detection
- Exposes functionality through the Model Context Protocol (MCP) with HTTP or stdio transport

## Setup and Installation

1. Ensure you have Python 3.11 or higher installed
2. Install uv package manager if not already installed: `pip install uv`
3. Install dependencies: `uv pip install -e .`

### External Dependencies

When running locally (without Docker):

- For AI image captioning, install Ollama: [Download Ollama](https://ollama.ai/)
  - After installing Ollama, run one of these commands to pull a supported model:
    ```bash
    ollama pull gemma3:4b
    # OR
    ollama pull qwen2.5vl:7b
    ```

- For enhanced YouTube transcript extraction, optionally run the bgutil-ytdlp-pot-provider container:
  ```bash
  # Run the bgutil-provider container separately:
  docker run --name bgutil-provider -d -p 4416:4416 --init brainicism/bgutil-ytdlp-pot-provider
  ```

## Usage

### Running as an MCP Server

You can run the MCP server in one of these ways:

#### Option 1: Using Docker Compose (Recommended)

```bash
# Start both the MCP server and bgutil-provider
docker-compose up -d
```

#### Option 2: Manual Setup

1. (Optional) For enhanced YouTube transcript extraction, run the bgutil-provider container:

```bash
docker run --name bgutil-provider -d -p 4416:4416 --init brainicism/bgutil-ytdlp-pot-provider
```

2. Run the MCP server:

```bash
# Default transport is now HTTP (port 8085)
uv run main.py

# For stdio transport
MCP_TRANSPORT=stdio uv run main.py
```

3. When running locally (without Docker Compose), set the bgutil provider URL so yt-dlp can use SABR tokens for YouTube:

```bash
# macOS/Linux
export YTDLP_BGUTIL_POT_PROVIDER_URL=http://127.0.0.1:4416

# Windows (PowerShell)
$env:YTDLP_BGUTIL_POT_PROVIDER_URL = "http://127.0.0.1:4416"
```

Note: The application now auto-detects a running provider at `bgutil-provider:4416` (Docker) or `127.0.0.1:4416` (local). Setting the variable explicitly ensures consistent behavior.

3. Use the `markitdown_fetch` tool with a URL parameter pointing to the document you want to convert

#### Example

Request:
```
markitdown_fetch(url="https://example.com/document.pdf")
```

Response:
```json
{
  "markdown": "# Document Title\n\nDocument content converted to markdown..."
}
```

### Testing Specific URLs

You can test document conversion without starting the MCP server by using the `--test` flag:

```bash
uv run main.py --test "https://example.com/document.pdf"
```

This will download the document, convert it to markdown, and display a preview of the conversion result.

## YouTube Transcript Features

The server includes enhanced YouTube transcript extraction capabilities:

### Advanced Extraction Methods
1. **Primary:** youtube-transcript-api for fast, efficient extraction
2. **Fallback:** yt-dlp with subtitle parsing for blocked videos
3. **Enhanced:** bgutil-ytdlp-pot-provider integration to bypass SABR protections

### Key Features
- **Automatic deduplication** removes duplicate transcript lines
- **Rich metadata** includes video title, creator, upload date, duration, description
- **Pagination support** handles large transcripts with `response_limit` parameter
- **Multiple formats** supports all YouTube URL variations (youtube.com, youtu.be, embed, etc.)
- **Robust fallback** gracefully handles rate limiting and access restrictions

### Example Response Format
```json
{
  "markdown": "# Video Title\n\n**Creator:** Channel Name\n**Duration:** 15 minutes\n\n## Transcript\n\nTranscript content here...",
  "next_cursor": "1250",
  "has_more": true
}
```

## Supported URL Types

- PDF documents: `https://example.com/document.pdf`
- Word documents: `https://example.com/document.docx`
- PowerPoint presentations: `https://example.com/presentation.pptx`
- Excel spreadsheets: `https://example.com/spreadsheet.xlsx`
- HTML pages: `https://example.com/page.html`
- YouTube videos: `https://youtube.com/watch?v=...` or `https://youtu.be/...`
- Images: `https://example.com/image.jpg`

## How It Works

1. The server accepts a URL pointing to a document
2. **For YouTube URLs:**
   - Attempts transcript extraction using youtube-transcript-api
   - Falls back to yt-dlp with subtitle extraction if API fails
   - Uses bgutil-ytdlp-pot-provider to bypass YouTube's SABR protections (if available)
   - Automatically deduplicates transcript lines
   - Includes video metadata (title, uploader, duration, description)
   - Supports pagination for large transcripts
3. **For images:** If Ollama is available with a supported model (gemma3:4b or qwen2.5vl:7b), it generates a descriptive caption
4. **For other documents:** Downloads to a temporary location and uses Microsoft's markitdown package for conversion
5. The document is converted to markdown format, preserving structure
6. The temporary files are cleaned up
7. The markdown content is returned as a response

## Dependencies

### Python Packages
- markitdown[all]: Microsoft's MarkItDown package for document conversion
- fastmcp: For building MCP servers
- requests: For fetching documents from URLs
- beautifulsoup4: For HTML parsing and transcript processing
- yt-dlp[curl-cffi]: Enhanced YouTube downloader with advanced capabilities
- youtube-transcript-api: Primary YouTube transcript extraction library
- humanize: For formatting video duration and dates
- ollama: For interacting with local Ollama instance for image captioning
- pillow: For image processing and manipulation
- pydub: For audio processing (used by some markitdown components)

### Optional Enhancements
- bgutil-ytdlp-pot-provider: Bypasses YouTube's SABR protections for better reliability

### System Dependencies
When running the Docker container, these are automatically installed:
- ffmpeg: For audio/video processing and format conversion
- poppler-utils: For PDF processing
- libmagic1: For file type detection

## Docker Support

> **Note:** The default transport mode is now HTTP on port 8085. This works well with Docker and allows easier integration with other services. You can still use stdio transport by setting the environment variable `MCP_TRANSPORT=stdio` when running the application.

### Building and Running with Docker

The project includes Docker support for easy deployment and isolation from host dependencies.

#### Prerequisites

- Docker installed on your system
- Ollama running on the host machine (not in the container)

#### Quick Start with Docker Compose

The docker-compose configuration now includes both the main application and the bgutil-provider service for enhanced YouTube transcript extraction. The application uses HTTP transport mode by default (port 8085), which makes it easier to use with Docker.

1. Clone the repository and navigate to the project directory
2. Build and run using Docker Compose:

```bash
# For Windows/Mac (uses host.docker.internal)
docker-compose up --build

# For Linux, edit docker-compose.yml to uncomment the Linux configuration
# or use the alternative command:
OLLAMA_HOST=http://172.17.0.1:11434 docker-compose up --build
```

This will start both services:
- `mcp-markitdown`: The main application (HTTP server on port 8085)
- `bgutil-provider`: PO token provider for YouTube SABR bypass (port 4416)

The MCP server will be accessible at http://localhost:8085/ for HTTP clients.

#### Transport Mode Configuration

You can configure the transport mode using environment variables:

```bash
# In docker-compose.yml under environment:
- MCP_TRANSPORT=http  # or "stdio"
- MCP_HTTP_PORT=8085  # only used when MCP_TRANSPORT=http
```

#### Running Only the bgutil Provider

If you want to run just the bgutil provider alongside a local development setup:

```bash
# Start only the bgutil provider
docker-compose up bgutil-provider

# Or run it standalone (recommended when using stdio transport)
docker run --name bgutil-provider -d -p 4416:4416 --init brainicism/bgutil-ytdlp-pot-provider
```

#### Manual Docker Build

```bash
# Build the image
docker build -t mcp-markitdown .

# Run the container (Windows/Mac)
docker run -e OLLAMA_HOST=http://host.docker.internal:11434 mcp-markitdown

# Run the container (Linux)
docker run -e OLLAMA_HOST=http://172.17.0.1:11434 mcp-markitdown

# Test with a specific URL
docker run -e OLLAMA_HOST=http://host.docker.internal:11434 mcp-markitdown python main.py --test "https://example.com/document.pdf"
```

#### Environment Variables

- `OLLAMA_HOST`: URL of the Ollama service (default: http://localhost:11434)
  - Windows/Mac: `http://host.docker.internal:11434`
  - Linux: `http://172.17.0.1:11434` or use `--network=host`

#### Network Configuration

**Windows/Mac:**
Uses `host.docker.internal` to connect to services on the host machine.

**Linux:**
Requires special configuration:
- Use `--network=host` to share the host network
- Or use `172.17.0.1:11434` (Docker bridge gateway IP)
- Or add `--add-host=host.docker.internal:host-gateway`

#### Troubleshooting Docker

1. **Connection refused errors**: Ensure Ollama is running on the host and accessible
2. **Linux networking**: Try different approaches:
   ```bash
   # Option 1: Host networking
   docker run --network=host mcp-markitdown

   # Option 2: Bridge with gateway
   docker run -e OLLAMA_HOST=http://172.17.0.1:11434 mcp-markitdown

   # Option 3: Custom host mapping
   docker run --add-host=host.docker.internal:host-gateway mcp-markitdown
   ```

## License

This project uses the markitdown package from Microsoft, which is under MIT license.
