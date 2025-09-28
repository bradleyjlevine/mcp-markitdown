#!/usr/bin/env python
"""
MCP-MarkItDown: A service for converting various document types to Markdown format.

This module implements an MCP (Model Context Protocol) server that exposes a tool
for fetching documents from URLs and converting them to Markdown format for use
with Large Language Models (LLMs).

Supported document types:
- PDF documents
- Word documents (docx)
- PowerPoint presentations (pptx)
- Excel spreadsheets (xlsx)
- HTML pages
- YouTube video transcripts (with enhanced extraction capabilities)
- Image files (with AI-powered captioning when Ollama is available)

Main features:
- MCP server implementation using stdio transport
- Document conversion using Microsoft's markitdown package
- Enhanced YouTube transcript extraction with fallback mechanisms
- Image captioning with Ollama integration (when available)
- Pagination support for large YouTube transcripts

Usage:
    # Run as MCP server (stdio transport)
    python main.py

    # Test with a specific URL
    python main.py --test "https://example.com/document.pdf"
"""

import os
import tempfile
import requests
import re
import yt_dlp
import urllib.parse
import subprocess
import json
import base64
import sys
import logging
import contextlib
import io
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from markitdown import MarkItDown
from fastmcp import FastMCP
from PIL import Image
import io

# Import custom YouTube transcript module
from youtube_transcript import get_youtube_transcript, extract_video_id, get_youtube_video_info

# Setup logging to file instead of stdout when running as MCP server
# This prevents print statements from interfering with stdio transport
# When in test mode, log to console; otherwise log only to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("markitdown.log"),
        logging.StreamHandler() if "--test" in sys.argv else logging.NullHandler()
    ]
)
logger = logging.getLogger("markitdown")

# Global variables for Ollama availability
OLLAMA_AVAILABLE = False
PREFERRED_MODEL = None

# Use this for output instead of print() to avoid interfering with MCP stdio transport
def log_info(message):
    if "--test" in sys.argv:
        print(message)  # Print to console in test mode
    else:
        logger.info(message)  # Log to file in MCP server mode

# ===== OLLAMA INTEGRATION ===== #

# Function to check if Ollama is available
def check_ollama_availability():
    """Check if Ollama is available on the system by trying to connect to it."""
    global OLLAMA_AVAILABLE, PREFERRED_MODEL

    try:
        # Try to import ollama
        import ollama

        # Get Ollama host from environment variable
        ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
        log_info(f"Attempting to connect to Ollama at: {ollama_host}")

        # Create Ollama client with custom host
        client = ollama.Client(host=ollama_host)

        # Check if Ollama service is running by listing models
        try:
            # Try to get the list of models
            models_response = client.list()

            # Handle different response formats
            if not models_response:
                log_info("Ollama responded with empty data")
                OLLAMA_AVAILABLE = False
                return False

            # The structure might be different based on Ollama version
            # Try to extract models from the response
            if 'models' in models_response:
                models = models_response.get('models', [])
            else:
                # Some versions just return a list directly
                models = models_response if isinstance(models_response, list) else []
                # If it's a dict but without 'models' key, try to extract any list we can find
                if isinstance(models_response, dict) and not models:
                    for key, value in models_response.items():
                        if isinstance(value, list) and value:
                            models = value
                            log_info(f"Found models under key: {key}")
                            break

            if models:
                log_info("Ollama is available with the following models:")
                model_names = []

                for model in models:
                    try:
                        # Handle different potential formats
                        model_name = None

                        if isinstance(model, dict):
                            # Dictionary format
                            if 'name' in model:
                                model_name = model['name']
                            elif 'NAME' in model:
                                model_name = model['NAME']
                            elif 'model' in model:
                                model_name = model['model']
                        elif isinstance(model, str):
                            # String format
                            model_name = model
                        elif hasattr(model, 'model'):
                            # Object with model attribute (like the Model class we're seeing)
                            model_name = model.model
                        elif hasattr(model, 'name'):
                            # Object with name attribute
                            model_name = model.name

                        # Print and save the model name if found
                        if model_name:
                            log_info(f"  - {model_name}")
                            model_names.append(model_name)
                        else:
                            # Fallback: print the whole model but don't use it
                            log_info(f"  - {model} (unable to extract name)")
                    except Exception as e:
                        log_info(f"  - Error extracting model name: {str(e)}")

                # Priority order of models
                preferred_models = ["gemma3:4b", "qwen2.5vl:7b"]

                for model in preferred_models:
                    if model in model_names:
                        PREFERRED_MODEL = model
                        log_info(f"Using {PREFERRED_MODEL} for image captioning")
                        OLLAMA_AVAILABLE = True
                        return True

                log_info("No preferred vision models available. Please install gemma3:4b or qwen2.5vl:7b")
                OLLAMA_AVAILABLE = False
            else:
                log_info("Ollama is installed but no models are available")
                OLLAMA_AVAILABLE = False
        except Exception as e:
            log_info(f"Error listing Ollama models: {str(e)}")
            OLLAMA_AVAILABLE = False
            PREFERRED_MODEL = None

    except ImportError:
        log_info("Ollama Python package is not available")
        OLLAMA_AVAILABLE = False
        PREFERRED_MODEL = None
    except Exception as e:
        log_info(f"Ollama is not available: {str(e)}")
        OLLAMA_AVAILABLE = False
        PREFERRED_MODEL = None

    return OLLAMA_AVAILABLE

# Function to generate image caption using Ollama
# This uses Ollama's multimodal models to describe images
def generate_image_caption(image_path):
    """Generate a caption for an image using Ollama."""
    if not OLLAMA_AVAILABLE or not PREFERRED_MODEL:
        return "Image caption not available (Ollama or required models not found)"

    try:
        import ollama

        # Get Ollama host from environment variable
        ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')

        # Create Ollama client with custom host
        client = ollama.Client(host=ollama_host)

        # Load and convert image to base64
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()

        # Create the prompt for the model
        response = client.chat(
            model=PREFERRED_MODEL,
            messages=[{
                'role': 'user',
                'content': 'Please describe this image in detail.',
                'images': [base64.b64encode(img_data).decode('utf-8')]
            }]
        )

        # Extract the caption from the response
        caption = response['message']['content']
        return caption

    except Exception as e:
        log_info(f"Error generating image caption: {str(e)}")
        return f"Failed to generate image caption: {str(e)}"

# Check Ollama availability at startup
log_info("Checking Ollama availability...")
check_ollama_availability()

# ===== MCP SERVER INITIALIZATION ===== #

# Initialize MCP server with FastMCP library
mcp = FastMCP("MarkItDown Fetch Server")

# Configure transport mode
# Options: "stdio" (default), "http"
DEFAULT_TRANSPORT = os.getenv('MCP_TRANSPORT', 'streamable-http')
HTTP_PORT = int(os.getenv('MCP_HTTP_PORT', '8085'))
HTTP_HOST = os.getenv('MCP_HTTP_HOST', '0.0.0.0')


# ===== FILE HANDLING FUNCTIONS ===== #

def download_file(url):
    """Download a file from a URL to a temporary location and return the local path.

    This function handles various edge cases including:
    - Extracting filename from Content-Disposition header
    - Fallback to URL path when no filename is provided
    - Content-type based extension determination
    - Creating appropriate temporary files with correct extensions

    Args:
        url: The URL to download from

    Returns:
        Path to the downloaded temporary file

    Raises:
        requests.RequestException: If the download fails
    """
    response = requests.get(url, stream=True)
    response.raise_for_status()

    # Try to get filename from Content-Disposition header
    content_disposition = response.headers.get('Content-Disposition')
    filename = None
    if content_disposition:
        matches = re.findall('filename="?([^";]+)"?', content_disposition)
        if matches:
            filename = matches[0]

    # If no filename in header, extract from URL
    if not filename:
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        # Decode URL encoded characters
        filename = urllib.parse.unquote(filename)

    # If still no valid filename, use generic name with extension from URL
    if not filename or filename == "":
        ext = os.path.splitext(parsed_url.path)[1]
        if not ext:
            # Try to determine extension from content-type
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' in content_type:
                ext = '.pdf'
            elif 'word' in content_type or 'docx' in content_type:
                ext = '.docx'
            elif 'powerpoint' in content_type or 'pptx' in content_type:
                ext = '.pptx'
            elif 'excel' in content_type or 'xlsx' in content_type:
                ext = '.xlsx'
            elif 'html' in content_type:
                ext = '.html'
            else:
                ext = '.bin'  # Generic binary extension
        filename = f"downloaded{ext}"

    # Create a temporary file with the correct extension
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1], delete=False) as temp_file:
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        return temp_file.name


# ===== YOUTUBE HANDLING FUNCTIONS ===== #

def is_youtube_url(url: str) -> bool:
    """Check if a URL is a YouTube URL.

    Supports multiple YouTube URL formats including:
    - youtube.com/watch?v=VIDEO_ID
    - youtu.be/VIDEO_ID
    - youtube.com/embed/VIDEO_ID
    - youtube.com/v/VIDEO_ID

    Args:
        url: URL to check

    Returns:
        True if the URL is a YouTube URL, False otherwise
    """
    parsed_url = urlparse(url)

    # Check for youtu.be domain
    if parsed_url.hostname == "youtu.be":
        return True

    # Check for youtube.com domains
    if parsed_url.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        # Standard watch URLs with v parameter
        if "v" in urllib.parse.parse_qs(parsed_url.query):
            return True

        # Embed URLs
        if parsed_url.path.startswith("/embed/"):
            return True

        # Direct video URLs
        if parsed_url.path.startswith("/v/"):
            return True

    return False


def process_youtube_url(url: str, response_limit: int = -1, next_cursor: Optional[str] = None) -> dict:
    """Process a YouTube URL and return markdown with the transcript and video information.

    This function handles YouTube transcript extraction with multiple fallback methods:
    1. Primary: Custom YouTube transcript fetcher with pagination support
    2. Fallback: Markitdown's built-in YouTube handling

    The function enriches the transcript with video metadata (title, creator, upload date,
    duration, description) and formats everything as structured markdown.

    Args:
        url: YouTube video URL
        response_limit: Maximum number of characters for paginated responses (-1 for no pagination)
        next_cursor: Cursor for pagination

    Returns:
        Dictionary with markdown content and pagination information:
        - markdown: Formatted markdown with transcript and video metadata
        - next_cursor: Pagination cursor for the next chunk (if any)
        - has_more: Boolean indicating if there's more content to retrieve
    """
    log_info(f"Processing YouTube URL: {url} with custom transcript fetcher")

    try:
        # Get video info to include richer metadata
        video_info = get_youtube_video_info(url)

        # Use our custom YouTube transcript fetcher with pagination support
        result = get_youtube_transcript(url, response_limit=response_limit, next_cursor=next_cursor)

        if result["success"] and result["transcript"]:
            # Format the transcript as markdown
            title = result["title"]
            transcript = result["transcript"]
            language = result["language"]
            method = result.get("method", "default")
            next_cursor = result.get("next_cursor")

            # Create a richer markdown with video metadata if available
            markdown = f"# {title}\n\n"

            # Add video info if available
            if video_info.get("success"):
                description = video_info.get("description", "").strip()
                uploader = video_info.get("uploader", "Unknown")
                upload_date_obj = video_info.get("upload_date")
                upload_date = upload_date_obj.strftime("%B %d, %Y") if upload_date_obj else "Unknown date"
                duration = video_info.get("duration", "Unknown duration")

                markdown += f"**Creator:** {uploader}\n\n"
                markdown += f"**Upload Date:** {upload_date}\n\n"
                markdown += f"**Duration:** {duration}\n\n"

                if description and len(description) > 0:
                    # Truncate very long descriptions
                    if len(description) > 500:
                        description = description[:500] + "..."
                    markdown += f"**Description:**\n\n{description}\n\n"

            # Add transcript with language information
            markdown += f"## Transcript ({language})\n\n{transcript}"

            # Add pagination information if available
            has_more = next_cursor is not None

            log_info(f"Successfully extracted transcript with custom fetcher (method: {method}), length: {len(transcript)}")
            return {
                "markdown": markdown,
                "next_cursor": next_cursor,
                "has_more": has_more
            }
        else:
            error = result.get("error", "Unknown error")
            log_info(f"Custom transcript fetcher failed: {error}")

            # Return a more user-friendly markdown instead of failing
            title = result.get("title", "YouTube Video")
            video_id = result.get("video_id", extract_video_id(url) if "youtube" in url else "unknown")

            # Try to get video info even if transcript failed
            video_metadata = ""
            if "title" in video_info and video_info["success"]:
                title = video_info["title"]  # Use the better title if available
                uploader = video_info.get("uploader", "Unknown")
                upload_date_obj = video_info.get("upload_date")
                upload_date = upload_date_obj.strftime("%B %d, %Y") if upload_date_obj else "Unknown date"
                duration = video_info.get("duration", "Unknown duration")

                video_metadata += f"**Creator:** {uploader}\n\n"
                video_metadata += f"**Upload Date:** {upload_date}\n\n"
                video_metadata += f"**Duration:** {duration}\n\n"

            # Create a markdown response with the error and a direct link
            markdown = f"# {title}\n\n"

            # Add video info if available
            if video_metadata:
                markdown += video_metadata

            markdown += f"## Transcript Unavailable\n\nUnable to retrieve transcript for this video due to YouTube rate limiting or transcript unavailability.\n\n"
            markdown += f"Please visit the video directly: [Watch on YouTube](https://www.youtube.com/watch?v={video_id})\n\n"
            markdown += f"Error details: {error}"

            # This isn't an exception - we're returning a useful markdown response instead
            return {"markdown": markdown, "next_cursor": None, "has_more": False}

    except Exception as e:
        log_info(f"Error in custom YouTube transcript processing: {str(e)}")

        try:
            # Try to at least get the title and video ID
            if "youtube" in url:
                video_id = extract_video_id(url)
                title = "YouTube Video"
            else:
                video_id = "unknown"
                title = "Unknown Video"

            # Create a markdown response with the error and a direct link
            markdown = f"# {title}\n\n## Transcript Unavailable\n\nUnable to retrieve transcript for this video due to an error.\n\n"
            markdown += f"Please visit the video directly: [Watch on YouTube](https://www.youtube.com/watch?v={video_id})\n\n"
            markdown += f"Error details: {str(e)}"

            return {"markdown": markdown, "next_cursor": None, "has_more": False}
        except:
            # Last resort fallback
            error_msg = f"Failed to process YouTube URL: {str(e)}"
            return {"markdown": error_msg, "next_cursor": None, "has_more": False}


# ===== MCP TOOL DEFINITION ===== #

@mcp.tool(
    name="markitdown_fetch",
    description="Fetch a document from a URL and convert it to markdown format. Supports PDF, DOCX, PPTX, XLSX, HTML, YouTube transcripts, and images.",
    output_schema={
        "type": "object",
        "properties": {
            "markdown": {
                "type": "string",
                "description": "Markdown representation of the fetched document"
            },
            "next_cursor": {
                "type": ["string", "null"],
                "description": "Optional cursor for paginated content, especially for long YouTube transcripts"
            },
            "has_more": {
                "type": "boolean",
                "description": "Indicates if there is more content available via pagination"
            }
        }
    }
)
def markitdown_fetch(
    url: str = None,  # URL pointing to the document to fetch and convert
    next_cursor: str = None,  # Cursor for pagination of long content
    response_limit: int = 50000  # Maximum characters to return per request
) -> dict:
    """Main MCP tool function for fetching and converting documents to markdown.

    This function is the core of the MCP service, handling various document types:
    - PDF documents
    - Word documents (docx)
    - PowerPoint presentations (pptx)
    - Excel spreadsheets (xlsx)
    - HTML pages
    - YouTube video transcripts
    - Image files (with AI captions)

    The function implements a multi-stage processing pipeline:
    1. URL detection and sanitization
    2. YouTube-specific handling for transcript extraction
    3. Direct URL conversion with markitdown
    4. Download and local file conversion as fallback
    5. Special handling for images with AI-powered captioning
    """
    """
    Fetch a document from the provided URL and convert it to markdown.

    Supports:
    - PDF documents
    - Word documents (docx)
    - PowerPoint presentations (pptx)
    - Excel spreadsheets (xlsx)
    - HTML pages
    - YouTube video transcripts (with pagination support for long transcripts)
    - Image files (with AI-powered captioning when Ollama is available)

    Args:
        url: The URL pointing to the document to fetch and convert
        next_cursor: Optional cursor for paginated content retrieval
        response_limit: Maximum characters to return per request (default: 50000)

    Returns:
        Dictionary containing:
        - markdown: Markdown representation of the document
        - next_cursor: Pagination cursor for subsequent requests (if applicable)
        - has_more: Boolean indicating if more content is available
    """
    try:
        log_info(f"Processing URL: {url}")

        # Clean up URL - remove quotes and brackets that might be accidentally included
        url = url.strip().rstrip('"\'[]')

        # First check if this is a YouTube URL
        if is_youtube_url(url):
            try:
                # Try our custom YouTube transcript handler with pagination support
                log_info(f"Detected YouTube URL, using custom transcript handler")
                result = process_youtube_url(url, response_limit, next_cursor)

                # Get the markdown content from the result
                content = result["markdown"]

                # Normalize line endings for consistency
                content = content.replace('\r\n', '\n')

                # Strip any problematic characters that might cause JSON issues
                content = ''.join(c for c in content if ord(c) >= 32 or c in '\n\r\t')

                # Return the result with pagination information
                return {
                    "markdown": content,
                    "next_cursor": result.get("next_cursor"),
                    "has_more": result.get("has_more", False)
                }
            except Exception as e:
                log_info(f"Custom YouTube transcript handler failed: {str(e)}")
                log_info(f"Falling back to markitdown's built-in YouTube support")
                # Fall through to markitdown's method if our custom handler fails

        # Initialize MarkItDown converter with plugins enabled
        # This enables YouTube support via the built-in YouTubeConverter as fallback
        md = MarkItDown(enable_plugins=True)

        try:
            # Try direct conversion with the URL
            # This will use markitdown's built-in YouTube handling for YouTube URLs
            log_info(f"Attempting direct URL conversion with markitdown...")
            result = md.convert(url)
            if result and hasattr(result, 'text_content') and result.text_content:
                content = result.text_content
                log_info(f"Direct URL conversion successful, content length: {len(content)}")

                # Normalize line endings for consistency
                content = content.replace('\r\n', '\n')

                # Strip any problematic characters that might cause JSON issues
                content = ''.join(c for c in content if ord(c) >= 32 or c in '\n\r\t')

                return {
                    "markdown": content,
                    "next_cursor": None,
                    "has_more": False
                }
        except Exception as e:
            log_info(f"Direct URL conversion failed: {str(e)}")

        # If direct URL conversion failed or for non-URL inputs, download the file and try again
        log_info(f"Downloading file for conversion...")
        local_path = download_file(url)
        log_info(f"Downloaded file to: {local_path}")

        # Convert the file to markdown
        result = md.convert(local_path)
        content = result.text_content

        # For images, if content is empty, provide enhanced content using Ollama when available
        if os.path.splitext(local_path)[1].lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'] and not content:
            image_markdown = f"![Image from {url}]({url})"

            # If Ollama is available, generate a caption
            if OLLAMA_AVAILABLE and PREFERRED_MODEL:
                log_info(f"Generating image caption using {PREFERRED_MODEL}...")
                caption = generate_image_caption(local_path)
                content = f"{image_markdown}\n\n## Image Description\n\n{caption}"
                log_info(f"Added image with AI-generated caption")
            else:
                content = f"{image_markdown}\n\n*This is an image file. For detailed image description, install Ollama with gemma3:4b or qwen2.5vl:7b.*"
                log_info(f"Added basic image tag for image file")

        log_info(f"Conversion successful, content length: {len(content)}")

        # Clean up temporary file
        os.remove(local_path)

        return {
            "markdown": content,
            "next_cursor": None,
            "has_more": False
        }

    except Exception as e:
        log_info(f"Error: {str(e)}")
        return {
            "markdown": f"Error processing {url}: {str(e)}",
            "next_cursor": None,
            "has_more": False
        }


# ===== TEST FUNCTIONS ===== #

def test_markitdown_fetch(url, next_cursor=None, response_limit=50000):
    """Test function to try markitdown_fetch functionality directly without starting the MCP server.

    This function mirrors the behavior of the MCP tool but is designed for direct
    command-line testing with the --test flag. It provides detailed console output
    of the conversion process and a preview of the result.
    """
    log_info(f"Testing markitdown_fetch with URL: {url}")
    try:
        # Clean up URL - remove quotes and brackets that might be accidentally included
        url = url.strip().rstrip('"\'[]')
        log_info(f"Processing URL: {url}")

        # Initialize MarkItDown converter with plugins enabled
        # This enables YouTube support via the built-in YouTubeConverter
        md = MarkItDown(enable_plugins=True)

        # First check if this is a YouTube URL
        if is_youtube_url(url):
            try:
                # Try our custom YouTube transcript handler with pagination support
                log_info(f"Detected YouTube URL, using custom transcript handler")
                result = process_youtube_url(url, response_limit, next_cursor)
                markdown_content = result["markdown"]

                # Show pagination info if available
                if result.get("next_cursor"):
                    log_info(f"Pagination: More content available. Next cursor: {result['next_cursor']}")

                # Normalize line endings for consistency
                markdown_content = markdown_content.replace('\r\n', '\n')

                # Strip any problematic characters that might cause JSON issues
                markdown_content = ''.join(c for c in markdown_content if ord(c) >= 32 or c in '\n\r\t')
                log_info(f"Custom YouTube transcript handler successful, content length: {len(markdown_content)}")
            except Exception as e:
                log_info(f"Custom YouTube transcript handler failed: {str(e)}")
                log_info(f"Falling back to markitdown's built-in YouTube support")

                # Fall back to markitdown's built-in handling
                try:
                    log_info(f"Attempting direct URL conversion with markitdown...")
                    result = md.convert(url)
                    if result and hasattr(result, 'text_content') and result.text_content:
                        markdown_content = result.text_content
                        log_info(f"Markitdown conversion successful, content length: {len(markdown_content)}")

                        # Normalize line endings for consistency
                        markdown_content = markdown_content.replace('\r\n', '\n')

                        # Strip any problematic characters that might cause JSON issues
                        markdown_content = ''.join(c for c in markdown_content if ord(c) >= 32 or c in '\n\r\t')
                    else:
                        raise Exception("Markitdown conversion returned empty result")
                except Exception as e2:
                    log_info(f"Markitdown YouTube handling also failed: {str(e2)}")
                    raise Exception(f"Both custom and markitdown YouTube handlers failed: {str(e)}, {str(e2)}")
        else:
            # For non-YouTube URLs, use regular markitdown conversion
            try:
                log_info(f"Attempting direct URL conversion with markitdown...")
                result = md.convert(url)
                if result and hasattr(result, 'text_content') and result.text_content:
                    markdown_content = result.text_content
                    log_info(f"Direct URL conversion successful, content length: {len(markdown_content)}")

                    # Normalize line endings for consistency
                    markdown_content = markdown_content.replace('\r\n', '\n')

                    # Strip any problematic characters that might cause JSON issues
                    markdown_content = ''.join(c for c in markdown_content if ord(c) >= 32 or c in '\n\r\t')
                else:
                    raise Exception("Direct URL conversion returned empty result")
            except Exception as e:
                log_info(f"Direct URL conversion failed: {str(e)}")
                raise
        # If direct URL conversion or YouTube handling failed, download the file and try again
        log_info(f"Downloading file for conversion...")
        local_path = download_file(url)
        log_info(f"Downloaded file to: {local_path}")

        # Convert the file to markdown
        conversion_result = md.convert(local_path)
        markdown_content = conversion_result.text_content

        # For images, if content is empty, provide enhanced content using Ollama when available
        if os.path.splitext(local_path)[1].lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'] and not markdown_content:
            image_markdown = f"![Image from {url}]({url})"

            # If Ollama is available, generate a caption
            if OLLAMA_AVAILABLE and PREFERRED_MODEL:
                log_info(f"Generating image caption using {PREFERRED_MODEL}...")
                caption = generate_image_caption(local_path)
                markdown_content = f"{image_markdown}\n\n## Image Description\n\n{caption}"
                log_info(f"Added image with AI-generated caption")
            else:
                markdown_content = f"{image_markdown}\n\n*This is an image file. For detailed image description, install Ollama with gemma3:4b or qwen2.5vl:7b.*"
                log_info(f"Added basic image tag for image file")

        log_info(f"Conversion successful, content length: {len(markdown_content)}")

        # Clean up temporary file
        os.remove(local_path)

        # Print only the first 500 characters of the result to avoid flooding the console
        preview = markdown_content[:500] + "..." if len(markdown_content) > 500 else markdown_content
        log_info(f"Preview:\n{preview}")
        return markdown_content
    except Exception as e:
        log_info(f"Test failed: {str(e)}")
        return None


# ===== MAIN ENTRY POINT ===== #

def main():
    """Main entry point for the application.

    Handles command-line arguments to either:
    1. Run in test mode with a specific URL
    2. Start the MCP server with stdio transport
    """
    import sys

    # Check if URL is provided as command line argument for testing
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        if len(sys.argv) > 2:
            test_url = sys.argv[2]
            test_markitdown_fetch(test_url)
        else:
            log_info("Please provide a URL to test")
            log_info("Usage: python main.py --test <url>")
        return

    # Start normal MCP server mode
    log_info("Starting MarkItDown Fetch Server")

    transport = DEFAULT_TRANSPORT
    log_info(f"Using {transport} transport mode")

    if transport == "http":
        # Bind to all interfaces (0.0.0.0) to allow external connections
        log_info(f"Starting HTTP server on {HTTP_HOST}:{HTTP_PORT}")
        mcp.run(transport=transport, port=HTTP_PORT, host=HTTP_HOST)
    else:
        # Default to stdio transport
        mcp.run(transport=transport)


if __name__ == "__main__":
    main()