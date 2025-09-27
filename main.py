#!/usr/bin/env python

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
from urllib.parse import urlparse
from markitdown import MarkItDown
from fastmcp import FastMCP
from PIL import Image
import io

# Setup logging to file instead of stdout when running as MCP server
# This prevents print statements from interfering with stdio transport
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

# Initialize MCP server
mcp = FastMCP("MarkItDown Fetch Server")


def download_file(url):
    """Download a file from a URL to a temporary location and return the local path."""
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


# YouTube handling now uses the built-in markitdown YouTubeConverter


@mcp.tool(
    name="markitdown_fetch",
    description="Fetch a document from a URL and convert it to markdown format. Supports PDF, DOCX, PPTX, XLSX, HTML, YouTube transcripts, and images.",
    output_schema={
        "type": "object",
        "properties": {
            "markdown": {
                "type": "string",
                "description": "Markdown representation of the fetched document"
            }
        }
    }
)
def markitdown_fetch(
    url: str = None,  # URL pointing to the document to fetch and convert
) -> dict:
    """
    Fetch a document from the provided URL and convert it to markdown.

    Supports:
    - PDF documents
    - Word documents (docx)
    - PowerPoint presentations (pptx)
    - Excel spreadsheets (xlsx)
    - HTML pages
    - YouTube video transcripts
    - Image files

    Args:
        url: The URL pointing to the document to fetch and convert

    Returns:
        Markdown representation of the document
    """
    try:
        log_info(f"Processing URL: {url}")

        # Clean up URL - remove quotes and brackets that might be accidentally included
        url = url.strip().rstrip('"\'[]')

        # Initialize MarkItDown converter with plugins enabled
        # This enables YouTube support via the built-in YouTubeConverter
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

                return {"markdown": content}
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

        return {"markdown": content}

    except Exception as e:
        log_info(f"Error: {str(e)}")
        return {"markdown": f"Error processing {url}: {str(e)}"}


def test_markitdown_fetch(url):
    """Test function to try markitdown_fetch functionality directly without starting the MCP server"""
    log_info(f"Testing markitdown_fetch with URL: {url}")
    try:
        # Clean up URL - remove quotes and brackets that might be accidentally included
        url = url.strip().rstrip('"\'[]')
        log_info(f"Processing URL: {url}")

        # Initialize MarkItDown converter with plugins enabled
        # This enables YouTube support via the built-in YouTubeConverter
        md = MarkItDown(enable_plugins=True)

        try:
            # Try direct conversion with the URL first
            # This will use markitdown's built-in YouTube handling for YouTube URLs
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

            # If direct URL conversion failed, download the file and try again
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


def main():
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
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()