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
from urllib.parse import urlparse
from markitdown import MarkItDown
from fastmcp import FastMCP
from PIL import Image
import io

# Global variables for Ollama availability
OLLAMA_AVAILABLE = False
PREFERRED_MODEL = None

# Function to check if Ollama is available
def check_ollama_availability():
    """Check if Ollama is available on the system by trying to connect to it."""
    global OLLAMA_AVAILABLE, PREFERRED_MODEL

    try:
        # Try to import ollama
        import ollama

        # Get Ollama host from environment variable
        ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
        print(f"Attempting to connect to Ollama at: {ollama_host}")

        # Create Ollama client with custom host
        client = ollama.Client(host=ollama_host)

        # Check if Ollama service is running by listing models
        try:
            # Try to get the list of models
            models_response = client.list()

            # Handle different response formats
            if not models_response:
                print("Ollama responded with empty data")
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
                            print(f"Found models under key: {key}")
                            break

            if models:
                print("Ollama is available with the following models:")
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
                            print(f"  - {model_name}")
                            model_names.append(model_name)
                        else:
                            # Fallback: print the whole model but don't use it
                            print(f"  - {model} (unable to extract name)")
                    except Exception as e:
                        print(f"  - Error extracting model name: {str(e)}")

                # Priority order of models
                preferred_models = ["gemma3:4b", "qwen2.5vl:7b"]

                for model in preferred_models:
                    if model in model_names:
                        PREFERRED_MODEL = model
                        print(f"Using {PREFERRED_MODEL} for image captioning")
                        OLLAMA_AVAILABLE = True
                        return True

                print("No preferred vision models available. Please install gemma3:4b or qwen2.5vl:7b")
                OLLAMA_AVAILABLE = False
            else:
                print("Ollama is installed but no models are available")
                OLLAMA_AVAILABLE = False
        except Exception as e:
            print(f"Error listing Ollama models: {str(e)}")
            OLLAMA_AVAILABLE = False
            PREFERRED_MODEL = None

    except ImportError:
        print("Ollama Python package is not available")
        OLLAMA_AVAILABLE = False
        PREFERRED_MODEL = None
    except Exception as e:
        print(f"Ollama is not available: {str(e)}")
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
        print(f"Error generating image caption: {str(e)}")
        return f"Failed to generate image caption: {str(e)}"

# Check Ollama availability at startup
print("Checking Ollama availability...")
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


def download_youtube_transcript(url):
    """Download a YouTube video transcript using yt-dlp and return the local path to a text file."""
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as temp_file:
        temp_path = temp_file.name

    # Extract video ID from URL
    video_id = None
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/|youtube\.com\/e\/|youtube\.com\/user\/.+\/|youtube\.com\/c\/.+\/|youtube\.com\/\w+\/|youtube\.com\/[^\/]+\?v=)([^&\n?#]+)',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([^&\n?#]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            break

    if not video_id:
        raise ValueError("Could not extract YouTube video ID from URL")

    # Options for yt-dlp with simpler approach for subtitle extraction
    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'skip_download': True,
        'quiet': True,
        'outtmpl': temp_path,
        'format': 'best',  # Just to satisfy the format requirement
        # Basic impersonation without complex client settings
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # The subtitle file might be named differently
            subtitle_path = f"{temp_path}.en.vtt"

            if os.path.exists(subtitle_path):
                # Read VTT and convert to plain text
                with open(subtitle_path, 'r', encoding='utf-8') as vtt_file:
                    content = vtt_file.read()

                # Enhanced VTT to text conversion with better formatting cleanup
                lines = content.split('\n')

                # Process lines to remove formatting
                filtered_lines = []
                last_clean_line = ""

                for line in lines:
                    # Skip WebVTT header, timestamps, position tags, etc.
                    if (not re.match(r'^WEBVTT|^\d{2}:|^NOTE|^Kind:|^Language:|^STYLE|^REGION', line) and
                        not re.match(r'^\d{2}:\d{2}:\d{2}\.\d{3}', line) and
                        not line.startswith('-->') and
                        line.strip()):

                        # Remove all VTT formatting tags: <00:00:00.000>, <c>, etc.
                        clean_line = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', line)
                        clean_line = re.sub(r'</?[a-zA-Z]>', '', clean_line)
                        clean_line = re.sub(r'</?[a-zA-Z]:[^>]*>', '', clean_line)

                        # Clean up any remaining tags
                        clean_line = re.sub(r'<[^>]*>', '', clean_line)

                        # Only add if there's content and it's not a duplicate of the previous line
                        if clean_line.strip() and clean_line.strip() != last_clean_line:
                            filtered_lines.append(clean_line.strip())
                            last_clean_line = clean_line.strip()

                # Write cleaned text to the output file
                with open(temp_path, 'w', encoding='utf-8') as text_file:
                    text_file.write(f"# Transcript for YouTube Video: {info.get('title', 'Unknown Title')}\n\n")
                    text_file.write('\n'.join(filtered_lines))

                # Clean up the VTT file
                if os.path.exists(subtitle_path):
                    os.remove(subtitle_path)

                return temp_path
            else:
                raise Exception("No subtitles were found for this video")
    except Exception as e:
        # Clean up temporary files in case of error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise Exception(f"Failed to download YouTube transcript: {str(e)}")


def is_youtube_url(url):
    """Check if the URL is from YouTube."""
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/'
    ]

    for pattern in patterns:
        if re.match(pattern, url):
            return True
    return False


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
        print(f"Processing URL: {url}")

        # Clean up URL - remove quotes and brackets that might be accidentally included
        url = url.strip().rstrip('"\'[]')

        # Initialize MarkItDown converter
        md = MarkItDown(enable_plugins=True)

        # Special handling for YouTube URLs
        if is_youtube_url(url):
            local_path = download_youtube_transcript(url)
            with open(local_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            # Clean up temporary file
            os.remove(local_path)
            return {"markdown": markdown_content}

        # For all other URLs, download the file and convert with markitdown
        local_path = download_file(url)
        print(f"Downloaded file to: {local_path}")

        # Convert the file to markdown
        result = md.convert(local_path)
        content = result.text_content

        # For images, if content is empty, provide enhanced content using Ollama when available
        if os.path.splitext(local_path)[1].lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'] and not content:
            image_markdown = f"![Image from {url}]({url})"

            # If Ollama is available, generate a caption
            if OLLAMA_AVAILABLE and PREFERRED_MODEL:
                print(f"Generating image caption using {PREFERRED_MODEL}...")
                caption = generate_image_caption(local_path)
                content = f"{image_markdown}\n\n## Image Description\n\n{caption}"
                print(f"Added image with AI-generated caption")
            else:
                content = f"{image_markdown}\n\n*This is an image file. For detailed image description, install Ollama with gemma3:4b or qwen2.5vl:7b.*"
                print(f"Added basic image tag for image file")

        print(f"Conversion successful, content length: {len(content)}")

        # Clean up temporary file
        os.remove(local_path)

        return {"markdown": content}

    except Exception as e:
        print(f"Error: {str(e)}")
        return {"markdown": f"Error processing {url}: {str(e)}"}


def test_markitdown_fetch(url):
    """Test function to try markitdown_fetch functionality directly without starting the MCP server"""
    print(f"Testing markitdown_fetch with URL: {url}")
    try:
        # Clean up URL - remove quotes and brackets that might be accidentally included
        url = url.strip().rstrip('"\'[]')
        print(f"Processing URL: {url}")

        # Initialize MarkItDown converter
        md = MarkItDown(enable_plugins=True)

        # Special handling for YouTube URLs
        if is_youtube_url(url):
            local_path = download_youtube_transcript(url)
            with open(local_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            # Clean up temporary file
            os.remove(local_path)
        else:
            # For all other URLs, download the file and convert with markitdown
            local_path = download_file(url)
            print(f"Downloaded file to: {local_path}")

            # Convert the file to markdown
            conversion_result = md.convert(local_path)
            markdown_content = conversion_result.text_content

            # For images, if content is empty, provide enhanced content using Ollama when available
            if os.path.splitext(local_path)[1].lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'] and not markdown_content:
                image_markdown = f"![Image from {url}]({url})"

                # If Ollama is available, generate a caption
                if OLLAMA_AVAILABLE and PREFERRED_MODEL:
                    print(f"Generating image caption using {PREFERRED_MODEL}...")
                    caption = generate_image_caption(local_path)
                    markdown_content = f"{image_markdown}\n\n## Image Description\n\n{caption}"
                    print(f"Added image with AI-generated caption")
                else:
                    markdown_content = f"{image_markdown}\n\n*This is an image file. For detailed image description, install Ollama with gemma3:4b or qwen2.5vl:7b.*"
                    print(f"Added basic image tag for image file")

            print(f"Conversion successful, content length: {len(markdown_content)}")

            # Clean up temporary file
            os.remove(local_path)

        # Print only the first 500 characters of the result to avoid flooding the console
        preview = markdown_content[:500] + "..." if len(markdown_content) > 500 else markdown_content
        print(f"Preview:\n{preview}")
        return markdown_content
    except Exception as e:
        print(f"Test failed: {str(e)}")
        return None


def main():
    import sys

    # Check if URL is provided as command line argument for testing
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        if len(sys.argv) > 2:
            test_url = sys.argv[2]
            test_markitdown_fetch(test_url)
        else:
            print("Please provide a URL to test")
            print("Usage: python main.py --test <url>")
        return

    # Start normal MCP server mode
    print("Starting MarkItDown Fetch Server")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()