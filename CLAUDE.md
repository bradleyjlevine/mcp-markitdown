# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

mcp-markitdown is a Python project that uses Microsoft's markitdown package to convert various input formats to Markdown. The project implements an MCP (Model Context Protocol) server that exposes a tool for fetching documents from URLs and converting them to markdown format, preserving document structure for use with Large Language Models (LLMs) and text analysis pipelines.

## Environment Setup

- Python 3.11 or higher is required
- The project uses uv for environment and package management
- Dependencies include:
  - markitdown[all] - Microsoft's package for converting various formats to Markdown
  - fastmcp - For MCP server implementation
  - requests - For HTTP requests and document fetching
  - beautifulsoup4 - For HTML parsing and transcript processing
  - yt-dlp[curl-cffi] - Enhanced YouTube downloader with subtitle extraction
  - youtube-transcript-api - Primary YouTube transcript extraction library
  - humanize - For formatting video metadata (duration, dates)
  - ollama - For interacting with local Ollama instance
  - pillow - For image processing

- External dependencies:
  - Ollama - Local AI service for image captioning (https://ollama.ai/)
  - At least one of these models installed in Ollama:
    - gemma3:4b
    - qwen2.5vl:7b

- Optional enhancements:
  - bgutil-ytdlp-pot-provider - Bypasses YouTube's SABR protections for more reliable transcript extraction
  - Docker container: `brainicism/bgutil-ytdlp-pot-provider` (port 4416)

## Development Commands

### Setup Environment

```bash
# Install uv if not already installed
pip install uv

# Install dependencies
uv pip install -e .
```

### Running the Application

```bash
# Run the MCP server using HTTP transport (default)
uv run main.py

# Run the MCP server with stdio transport
MCP_TRANSPORT=stdio uv run main.py

# Test the converter with a specific URL without starting the full server
uv run main.py --test "https://example.com/document.pdf"

# Test YouTube transcript extraction
uv run main.py --test "https://youtu.be/VIDEO_ID"

# Optionally start bgutil provider for enhanced YouTube support
docker run --name bgutil-provider -d -p 4416:4416 --init brainicism/bgutil-ytdlp-pot-provider

# Or use Docker Compose to start both the MCP server and bgutil provider
docker-compose up -d
```

## Project Structure

- `main.py` - Entry point for the application and all functionality including:
  - MCP server setup
  - File downloading and handling
  - YouTube transcript extraction with enhanced reliability
  - Image captioning with Ollama
  - Document conversion logic
  - Testing utilities
- `youtube_transcript.py` - Enhanced YouTube transcript extraction module with:
  - YouTubeTranscriptFetcher class with instance-based approach
  - Automatic fallback from youtube-transcript-api to yt-dlp
  - bgutil-ytdlp-pot-provider integration for SABR bypass
  - VTT/SRT subtitle parsing with deduplication
  - Pagination support for large transcripts
  - Video metadata extraction (title, uploader, duration, description)
- `pyproject.toml` - Project metadata and dependencies

## Supported Document Types

The markitdown_fetch tool can process these document types:
- PDF documents
- Word documents (docx)
- PowerPoint presentations (pptx)
- Excel spreadsheets (xlsx)
- HTML pages
- YouTube video transcripts (with enhanced extraction capabilities):
  - Primary extraction via youtube-transcript-api
  - Fallback extraction via yt-dlp with subtitle parsing
  - SABR protection bypass using bgutil-ytdlp-pot-provider
  - Automatic deduplication of transcript content
  - Rich video metadata inclusion
  - Pagination support for large transcripts
- Image files (with AI-powered captions when Ollama is available)

## MCP Integration

The project implements a `markitdown_fetch` tool using the FastMCP framework with this structure:
- Input: URL pointing to the document, optional `next_cursor` for pagination, optional `response_limit` for controlling output size
- Output: JSON object with:
  - `markdown` property containing the converted content
  - `next_cursor` for pagination (YouTube transcripts)
  - `has_more` boolean indicating if more content is available
- Transport: HTTP (default, port 8085) or stdio (configurable via environment variable)

## YouTube Transcript Implementation Details

The YouTube transcript functionality has been significantly enhanced based on analysis of the mcp-youtube-transcript project:

### Key Improvements Made:
1. **Instance-based YouTubeTranscriptApi** - Uses `YouTubeTranscriptApi(http_client=session, proxy_config=proxy_config)` pattern
2. **Simplified error handling** - Removed complex retry logic, aligned with mcp-youtube-transcript's approach
3. **Robust fallback system** - youtube-transcript-api → yt-dlp with VTT parsing
4. **SABR protection bypass** - Integrated bgutil-ytdlp-pot-provider for better YouTube access
5. **Content deduplication** - Removes duplicate lines common in YouTube VTT files
6. **Enhanced metadata** - Includes video title, creator, duration, upload date, description

### Implementation Architecture:
- `YouTubeTranscriptFetcher` class handles all transcript operations
- Dual extraction methods with automatic fallback
- VTT/SRT subtitle file parsing with intelligent filtering
- Pagination support for handling large transcript files
- Comprehensive error handling with user-friendly fallback responses