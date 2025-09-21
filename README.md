# MCP-MarkItDown

An MCP server that uses Microsoft's MarkItDown package to fetch documents from the internet (PDF, DOCX, PPTX, XLSX, YouTube transcripts, etc.) and convert them to markdown format.

## Features

- Converts various file types to Markdown:
  - PDF documents
  - Word documents (docx)
  - PowerPoint presentations (pptx)
  - Excel spreadsheets (xlsx)
  - HTML pages
  - YouTube video transcripts with automatic caption cleaning
  - Image files with AI-powered captioning (when Ollama is available)

- Preserves document structure for better LLM processing
- Handles YouTube transcript extraction with automatic formatting cleanup
- Provides proper error handling and content-type detection
- Exposes functionality through the Model Context Protocol (MCP)

## Setup and Installation

1. Ensure you have Python 3.11 or higher installed
2. Install uv package manager if not already installed: `pip install uv`
3. Install dependencies: `uv pip install -e .`

### External Dependencies

- For better audio/video processing, install FFmpeg: [Download FFmpeg](https://ffmpeg.org/download.html)
- For AI image captioning, install Ollama: [Download Ollama](https://ollama.ai/)
  - After installing Ollama, run one of these commands to pull a supported model:
    ```bash
    ollama pull gemma3:4b
    # OR
    ollama pull qwen2.5vl:7b
    ```

## Usage

### Running as an MCP Server

1. Run the MCP server:

```bash
uv run main.py
```

2. Use the `markitdown_fetch` tool with a URL parameter pointing to the document you want to convert

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

## Supported URL Types

- PDF documents: `https://example.com/document.pdf`
- Word documents: `https://example.com/document.docx`
- PowerPoint presentations: `https://example.com/presentation.pptx`
- Excel spreadsheets: `https://example.com/spreadsheet.xlsx`
- HTML pages: `https://example.com/page.html`
- YouTube videos (for transcript extraction): `https://www.youtube.com/watch?v=videoID`
- Images: `https://example.com/image.jpg`

## How It Works

1. The server accepts a URL pointing to a document
2. It downloads the document to a temporary location
3. For YouTube videos, it extracts and cleans up the transcript
4. For images, if Ollama is available with a supported model (gemma3:4b or qwen2.5vl:7b), it generates a descriptive caption
5. For other documents, it uses Microsoft's markitdown package for conversion
6. The document is converted to markdown format, preserving structure
7. The temporary files are cleaned up
8. The markdown content is returned as a response

## Dependencies

- markitdown[all]: Microsoft's MarkItDown package for document conversion
- fastmcp: For building MCP servers
- requests: For fetching documents from URLs
- beautifulsoup4: For HTML parsing
- yt-dlp[curl-cffi]: For handling YouTube videos and transcripts with browser impersonation
- ollama: For interacting with local Ollama instance for image captioning
- pillow: For image processing and manipulation

## License

This project uses the markitdown package from Microsoft, which is under MIT license.