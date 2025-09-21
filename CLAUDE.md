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
  - beautifulsoup4 - For HTML parsing
  - yt-dlp[curl-cffi] - For handling YouTube video transcripts
  - ollama - For interacting with local Ollama instance
  - pillow - For image processing

- External dependencies:
  - Ollama - Local AI service for image captioning (https://ollama.ai/)
  - At least one of these models installed in Ollama:
    - gemma3:4b
    - qwen2.5vl:7b

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
# Run the MCP server using stdio transport (default)
uv run main.py

# Test the converter with a specific URL without starting the full server
uv run main.py --test "https://example.com/document.pdf"
```

## Project Structure

- `main.py` - Entry point for the application and all functionality including:
  - MCP server setup
  - File downloading and handling
  - YouTube transcript extraction
  - Image captioning with Ollama
  - Document conversion logic
  - Testing utilities
- `pyproject.toml` - Project metadata and dependencies

## Supported Document Types

The markitdown_fetch tool can process these document types:
- PDF documents
- Word documents (docx)
- PowerPoint presentations (pptx)
- Excel spreadsheets (xlsx)
- HTML pages
- YouTube video transcripts
- Image files (with AI-powered captions when Ollama is available)

## MCP Integration

The project implements a `markitdown_fetch` tool using the FastMCP framework with this structure:
- Input: URL pointing to the document
- Output: JSON object with a "markdown" property containing the converted content
- Transport: stdio (default)