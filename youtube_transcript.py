"""
YouTube transcript fetching module.

Enhanced implementation based on youtube-transcript-api and yt-dlp that provides robust
transcript retrieval with pagination support and anti-scraping measures.

This module implements a reliable YouTube transcript fetcher with multiple fallback mechanisms:
1. Primary: Uses youtube-transcript-api for fast, direct transcript retrieval
2. Fallback: Uses yt-dlp for subtitle extraction when the API method fails
3. Enhanced: Supports bgutil-ytdlp-pot-provider for SABR protection bypass

Features:
- Multiple extraction methods with automatic fallback
- Pagination support for large transcripts
- Video metadata extraction (title, uploader, duration, etc.)
- Intelligent subtitle parsing and content deduplication
- Anti-bot detection measures

Usage:
    from youtube_transcript import get_youtube_transcript
    result = get_youtube_transcript("https://youtu.be/VIDEO_ID")
    if result["success"]:
        print(result["transcript"])
    else:
        print(f"Failed: {result['error']}")
"""

from functools import lru_cache
import logging
import subprocess
import tempfile
import os
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
from itertools import islice

import requests
import time
import random
import humanize
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig, GenericProxyConfig, ProxyConfig
import yt_dlp
from yt_dlp.extractor.youtube import YoutubeIE

# Set up logging
logger = logging.getLogger(__name__)

# Optional: enable detailed yt-dlp POT tracing via env
POT_TRACE_ENABLED = str(os.environ.get('YTDLP_POT_TRACE', '')).lower() in ('1', 'true', 'yes', 'on')

def _probe_bgutil(url: str, timeout: float = 1.5) -> bool:
    """Return True if a bgutil POT provider responds at url/ping."""
    try:
        resp = requests.get(f"{url.rstrip('/')}/ping", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _resolve_bgutil_provider_url() -> Optional[str]:
    """Determine a usable bgutil provider URL via env or common defaults.

    Priority:
    1) Explicit env var YTDLP_BGUTIL_POT_PROVIDER_URL
    2) Docker Compose service hostname: http://bgutil-provider:4416
    3) Localhost: http://127.0.0.1:4416, then http://localhost:4416
    """
    candidates = []

    env_url = os.environ.get('YTDLP_BGUTIL_POT_PROVIDER_URL')
    if env_url:
        candidates.append(env_url)

    # Common defaults for compose and local runs
    candidates.extend([
        'http://bgutil-provider:4416',
        'http://127.0.0.1:4416',
        'http://localhost:4416',
    ])

    seen = set()
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        if _probe_bgutil(url):
            return url
    return None


# Detect and set bgutil provider URL (enables tokens automatically when available)
BGUTIL_POT_PROVIDER_URL = _resolve_bgutil_provider_url()
if BGUTIL_POT_PROVIDER_URL:
    os.environ['YTDLP_BGUTIL_POT_PROVIDER_URL'] = BGUTIL_POT_PROVIDER_URL
    # Some setups also look for a generic switch – set if helpful
    os.environ['YTDLP_BGUTIL_PO_PROVIDER'] = 'bgutil'
    logger.info(f"bgutil POT provider enabled at {BGUTIL_POT_PROVIDER_URL}")
    # Check for yt-dlp plugin presence non-intrusively (filesystem-based)
    try:
        import yt_dlp_plugins  # namespace package used by yt-dlp
        plugin_paths = list(getattr(yt_dlp_plugins, '__path__', []))
        detected = False
        for base in plugin_paths:
            candidate = os.path.join(base, 'extractor', 'getpot_bgutil_http.py')
            if os.path.isfile(candidate):
                logger.info("Detected bgutil yt-dlp plugin files under yt_dlp_plugins/extractor")
                detected = True
                break
        if not detected:
            logger.info("yt_dlp_plugins present but bgutil plugin files not found; relying on yt-dlp plugin loader")
    except Exception:
        # Do not warn; yt-dlp may still load plugins via its loader without importability here
        logger.info("yt_dlp_plugins package not importable; continuing (yt-dlp may still discover plugins)")
else:
    logger.info("bgutil POT provider not detected; proceeding without SABR token support")

# Note: bgutil-ytdlp-pot-provider plugins are automatically discovered and registered by yt-dlp
# when installed in the yt_dlp_plugins directory. No manual configuration is needed.

# ===== UTILITY FUNCTIONS ===== #

def extract_video_id(url: str) -> str:
    """Extract the YouTube video ID from various URL formats.

    Supports standard youtube.com URLs, youtu.be short URLs, and embed URLs.

    Args:
        url: YouTube URL in any supported format

    Returns:
        The extracted video ID

    Raises:
        ValueError: If the video ID cannot be extracted from the URL
    """
    parsed_url = urlparse(url)

    # Handle youtu.be URLs
    if parsed_url.hostname == "youtu.be":
        return parsed_url.path.lstrip("/")

    # Handle youtube.com URLs
    if parsed_url.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        query = parse_qs(parsed_url.query)
        if 'v' in query:
            return query['v'][0]

        # Handle /embed/ URLs
        if parsed_url.path.startswith('/embed/'):
            return parsed_url.path.split('/')[2]

        # Handle /v/ URLs
        if parsed_url.path.startswith('/v/'):
            return parsed_url.path.split('/')[2]

    # If we get here, we couldn't extract a video ID
    raise ValueError(f"Could not extract video ID from URL: {url}")


def get_video_title(session: requests.Session, video_id: str, languages: List[str]) -> str:
    """Get the title of a YouTube video."""
    try:
        # Add slight delay to avoid rate limiting
        time.sleep(random.uniform(0.5, 1.5))

        response = session.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={
                "Accept-Language": ",".join(languages),
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            }
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string
            # Remove " - YouTube" suffix if present
            if " - YouTube" in title:
                title = title.replace(" - YouTube", "")
            return title
    except Exception as e:
        logger.warning(f"Failed to get video title: {e}")

    return "Unknown Title"


class VideoInfo:
    """Class to hold video information metadata."""

    def __init__(self, title: str, description: str, uploader: str, upload_date: datetime, duration: str):
        self.title = title
        self.description = description
        self.uploader = uploader
        self.upload_date = upload_date
        self.duration = duration


def _parse_time_info(date: int, timestamp: int, duration: int) -> Tuple[datetime, str]:
    """Parse time information from YouTube metadata."""
    try:
        parsed_date = datetime.strptime(str(date), "%Y%m%d").date()
        parsed_time = datetime.strptime(str(timestamp), "%H%M%S%f").time()
        upload_date = datetime.combine(parsed_date, parsed_time)
    except (ValueError, TypeError):
        # Fallback if the timestamp format doesn't match
        upload_date = datetime.now()

    duration_str = humanize.naturaldelta(timedelta(seconds=duration))
    return upload_date, duration_str


class YouTubeTranscriptFetcher:
    """Class to fetch transcripts from YouTube videos while avoiding anti-scraping measures.

    This class implements multiple strategies for transcript extraction:
    1. youtube-transcript-api: Fast direct access to YouTube's transcript data
    2. yt-dlp fallback: Uses subtitle extraction when the API fails
    3. SABR protection bypass: Optional integration with bgutil-ytdlp-pot-provider

    The fetcher handles pagination for large transcripts and provides detailed
    video metadata along with the transcript content. It automatically deduplicates
    subtitle content to remove repeated lines common in auto-generated captions.
    """

    def __init__(
        self,
        webshare_username: Optional[str] = None,
        webshare_password: Optional[str] = None,
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
        response_limit: int = -1
    ):
        """Initialize the transcript fetcher with optional proxy configuration.

        Args:
            webshare_username: Username for Webshare proxy service
            webshare_password: Password for Webshare proxy service
            http_proxy: HTTP proxy URL
            https_proxy: HTTPS proxy URL
            response_limit: Maximum number of characters for paginated responses (-1 for no pagination)
        """
        self.session = requests.Session()
        self.response_limit = response_limit

        # Set a realistic User-Agent
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Referer': 'https://www.google.com/'
        })

        # Configure proxy if provided
        self.proxy_config = None
        if webshare_username and webshare_password:
            self.proxy_config = WebshareProxyConfig(webshare_username, webshare_password)
        elif http_proxy or https_proxy:
            self.proxy_config = GenericProxyConfig(http_proxy, https_proxy)

        # Initialize YouTubeTranscriptApi with http_client like mcp-youtube-transcript does
        self.ytt_api = YouTubeTranscriptApi(http_client=self.session, proxy_config=self.proxy_config)

        # Initialize yt-dlp for video info
        # Configure yt-dlp with bgutil provider URL if available
        ydl_params = {"quiet": True}

        if BGUTIL_POT_PROVIDER_URL:
            logger.info(f"Initializing YoutubeDL with bgutil POT provider at {BGUTIL_POT_PROVIDER_URL}")
            ydl_params["extractor_args"] = {
                # Select the provider
                "youtube": {
                    "pot_provider": ["bgutil:http"],
                },
                # Configure provider-specific base_url
                "youtubepot-bgutilhttp": {
                    "base_url": [BGUTIL_POT_PROVIDER_URL],
                },
            }
            if POT_TRACE_ENABLED:
                ydl_params["extractor_args"]["youtube"]["pot_trace"] = ["true"]

        self.ydl = yt_dlp.YoutubeDL(params=ydl_params, auto_init=False)
        self.ydl.add_info_extractor(YoutubeIE())

    def get_transcript(
        self,
        url: str,
        language: str = "en",
        with_timestamps: bool = False,
        max_retries: int = 3,
        next_cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get the transcript for a YouTube video.

        Args:
            url: YouTube video URL or ID
            language: Preferred language code (defaults to English)
            with_timestamps: Whether to include timestamps in the output
            max_retries: Maximum number of retries if fetching fails
            next_cursor: Cursor for pagination (if response_limit is set)

        Returns:
            Dictionary with transcript information including pagination cursor if needed
        """
        # Try to extract video ID from URL
        try:
            video_id = extract_video_id(url)
        except ValueError:
            # If extraction fails, assume the input is already a video ID
            if not url.isalnum() or len(url) != 11:
                raise ValueError(f"Invalid YouTube video URL or ID: {url}")
            video_id = url

        # Set up language preferences with fallback
        languages = [language] if language == "en" else [language, "en"]

        # Get the video title
        title = get_video_title(self.session, video_id, languages)

        # Try to get the transcript with pagination support - simplified approach like mcp-youtube-transcript
        try:
            # Use the instance method like mcp-youtube-transcript does
            raw_transcript = self.ytt_api.fetch(video_id, languages=languages)

            # Store the transcript language (default to first requested language)
            transcript_lang = languages[0]

            # Format the transcript data
            if with_timestamps:
                transcript_list = [f"[{item['start']:.1f}s] {item['text']}" for item in raw_transcript]
            else:
                transcript_list = [item['text'] for item in raw_transcript]

            # Handle pagination if response limit is set
            if self.response_limit > 0:
                # Parse the cursor as integer with fallback
                try:
                    cursor_idx = int(next_cursor) if next_cursor else 0
                except (ValueError, TypeError):
                    cursor_idx = 0

                # Get the subset of transcript lines based on cursor
                result = ""
                next_cursor_out = None
                for i, line in islice(enumerate(transcript_list), cursor_idx, None):
                    if line is None:
                        continue
                    if len(result) + len(line) + 1 > self.response_limit:
                        next_cursor_out = str(i)
                        break
                    result += f"{line}\n"

                # Remove trailing newline
                if result:
                    result = result[:-1]

                # Return the paginated result
                return {
                    "title": title,
                    "transcript": result,
                    "language": transcript_lang,
                    "success": True,
                    "video_id": video_id,
                    "next_cursor": next_cursor_out
                }
            else:
                # Return the full transcript without pagination
                return {
                    "title": title,
                    "transcript": "\n".join(transcript_list),
                    "language": transcript_lang,
                    "success": True,
                    "video_id": video_id,
                    "next_cursor": None
                }

        except Exception as e:
            logger.error(f"Error fetching transcript with youtube-transcript-api: {e}")
            last_error = str(e)

        # If we reach here, regular transcript fetching failed, try using yt-dlp as a fallback
        logger.info(f"youtube-transcript-api failed, trying yt-dlp fallback...")
        try:
            # Try the yt-dlp fallback method
            transcript_text = self._get_transcript_via_ytdlp(video_id)
            logger.info(f"yt-dlp returned transcript length: {len(transcript_text) if transcript_text else 0}")
            if transcript_text:
                # Handle pagination if needed
                if self.response_limit > 0:
                    lines = transcript_text.split('\n')

                    # Parse the cursor as integer with fallback
                    try:
                        cursor_idx = int(next_cursor) if next_cursor else 0
                    except (ValueError, TypeError):
                        cursor_idx = 0

                    # Get the subset of transcript lines based on cursor
                    result = ""
                    next_cursor_out = None
                    for i, line in islice(enumerate(lines), cursor_idx, None):
                        if line is None:
                            continue
                        if len(result) + len(line) + 1 > self.response_limit:
                            next_cursor_out = str(i)
                            break
                        result += f"{line}\n"

                    # Remove trailing newline
                    if result:
                        result = result[:-1]

                    return {
                        "title": title,
                        "transcript": result,
                        "language": "auto",
                        "success": True,
                        "video_id": video_id,
                        "method": "yt-dlp",
                        "next_cursor": next_cursor_out
                    }
                else:
                    # Return the full transcript without pagination
                    return {
                        "title": title,
                        "transcript": transcript_text,
                        "language": "auto",
                        "success": True,
                        "video_id": video_id,
                        "method": "yt-dlp",
                        "next_cursor": None
                    }
        except Exception as e:
            logger.warning(f"yt-dlp fallback also failed: {e}")
            last_error = f"{last_error}; yt-dlp fallback: {str(e)}"

        # If all methods failed
        return {
            "title": title,
            "transcript": "",
            "language": None,
            "success": False,
            "error": last_error,
            "video_id": video_id
        }

    def _get_transcript_via_ytdlp(self, video_id: str) -> str:
        """Try to get transcript using yt-dlp as a fallback method."""
        url = f"https://www.youtube.com/watch?v={video_id}"

        # Create a temporary file for the subtitle
        with tempfile.NamedTemporaryFile(suffix='.vtt', delete=False) as temp_file:
            subtitle_path = temp_file.name

        try:
            # Configure yt-dlp options - create fresh instance to avoid conflicts
            ydl_opts = {
                'skip_download': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['en'],
                'subtitlesformat': 'vtt',
                'outtmpl': subtitle_path.replace('.vtt', ''),
                'quiet': True,  # Keep consistent with class initialization
                'ignore_no_formats_error': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                },
                # Minimal extractor args; let yt-dlp choose client; bgutil supplies tokens
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios']
                    }
                },
            }

            # Configure bgutil POT provider parameters if available
            if BGUTIL_POT_PROVIDER_URL:
                logger.info(f"Using bgutil POT provider at {BGUTIL_POT_PROVIDER_URL}")
                # Select provider and set base_url for plugin
                ydl_opts['extractor_args']['youtube']['pot_provider'] = ['bgutil:http']
                ydl_opts['extractor_args'].setdefault('youtubepot-bgutilhttp', {})['base_url'] = [BGUTIL_POT_PROVIDER_URL]
                if POT_TRACE_ENABLED:
                    ydl_opts['extractor_args']['youtube']['pot_trace'] = ['true']

            # bgutil plugins are automatically discovered by yt-dlp if installed

            # Run yt-dlp to download subtitles
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Check for subtitle files
            base_path = subtitle_path.replace('.vtt', '')
            subtitle_files = [f for f in os.listdir(os.path.dirname(base_path))
                             if os.path.isfile(os.path.join(os.path.dirname(base_path), f))
                             and f.startswith(os.path.basename(base_path))
                             and (f.endswith('.vtt') or f.endswith('.srt'))]

            if subtitle_files:
                # Use the first subtitle file found
                sub_file_path = os.path.join(os.path.dirname(base_path), subtitle_files[0])
                with open(sub_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Process the VTT/SRT file to extract just the text
                # This is a simple approach - for production use, consider a proper VTT/SRT parser
                lines = []
                prev_line = None
                for line in content.split('\n'):
                    stripped_line = line.strip()
                    # Skip timing lines, metadata, and empty lines
                    if ('-->' in line or                         # Timing information
                        stripped_line.isdigit() or               # Caption numbers
                        line.startswith('WEBVTT') or             # VTT header
                        line.startswith('Kind:') or              # VTT metadata
                        line.startswith('Language:') or          # VTT metadata
                        'align:start position:' in line or       # Positioning info
                        not stripped_line):                      # Empty lines
                        continue
                    # Also skip lines that are just HTML/XML tags with timing info like <00:00:00.320><c> I</c>
                    # These are common in YouTube's auto-generated captions
                    if '<' in stripped_line and '>' in stripped_line and ':' in stripped_line:
                        continue

                    # Deduplicate: skip if this line is identical to the previous line
                    # YouTube captions often have duplicate lines due to timing adjustments
                    if stripped_line != prev_line:
                        lines.append(stripped_line)
                        prev_line = stripped_line

                return '\n'.join(lines)
            else:
                logger.warning("No subtitle files found with yt-dlp")
                return ""
        except Exception as e:
            logger.error(f"Error using yt-dlp for transcript: {e}")
            raise
        finally:
            # Clean up temporary files
            try:
                if os.path.exists(subtitle_path):
                    os.remove(subtitle_path)
                # Also try to remove any other subtitle files that might have been created
                base_path = subtitle_path.replace('.vtt', '')
                for file in os.listdir(os.path.dirname(base_path)):
                    if file.startswith(os.path.basename(base_path)) and (file.endswith('.vtt') or file.endswith('.srt')):
                        try:
                            os.remove(os.path.join(os.path.dirname(base_path), file))
                        except:
                            pass
            except:
                pass


    @lru_cache(maxsize=32)
    def get_video_info(self, url: str) -> Dict[str, Any]:
        """Get detailed information about a YouTube video.

        Uses yt-dlp to extract rich metadata about the video including title,
        uploader, upload date, duration, and description. Results are cached
        to improve performance for repeated requests.

        Args:
            url: YouTube video URL

        Returns:
            Dictionary with video metadata including:
            - title: Video title
            - description: Video description
            - uploader: Channel or user who uploaded the video
            - upload_date: datetime object of when the video was uploaded
            - duration: Human-readable duration string
            - video_id: YouTube video ID
            - success: Boolean indicating if the request was successful
            - error: Error message if the request failed (only if success=False)
        """
        try:
            # Try to extract video ID from URL
            try:
                video_id = extract_video_id(url)
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            except ValueError:
                if not url.isalnum() or len(url) != 11:
                    raise ValueError(f"Invalid YouTube video URL or ID: {url}")
                video_id = url
                video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Extract info using yt-dlp
            info = self.ydl.extract_info(video_url, download=False)

            # Parse upload date and duration
            if "upload_date" in info and "timestamp" in info and "duration" in info:
                upload_date, duration_str = _parse_time_info(info["upload_date"], info["timestamp"], info["duration"])
            else:
                upload_date = datetime.now()
                duration_str = "Unknown duration"

            # Create VideoInfo object
            video_info = {
                "title": info.get("title", "Unknown Title"),
                "description": info.get("description", ""),
                "uploader": info.get("uploader", "Unknown Uploader"),
                "upload_date": upload_date,
                "duration": duration_str,
                "video_id": video_id,
                "success": True
            }

            return video_info
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return {
                "title": "Unknown Title",
                "description": "",
                "uploader": "Unknown Uploader",
                "upload_date": datetime.now(),
                "duration": "Unknown",
                "video_id": video_id if 'video_id' in locals() else "unknown",
                "success": False,
                "error": str(e)
            }

# Convenience function for simple usage
# ===== PUBLIC API FUNCTIONS ===== #

def get_youtube_transcript(
    url: str,
    language: str = "en",
    with_timestamps: bool = False,
    webshare_username: Optional[str] = None,
    webshare_password: Optional[str] = None,
    http_proxy: Optional[str] = None,
    https_proxy: Optional[str] = None,
    response_limit: int = -1,
    next_cursor: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to get a YouTube transcript without creating a fetcher instance.

    Args:
        url: YouTube video URL or ID
        language: Preferred language code
        with_timestamps: Whether to include timestamps
        webshare_username: Optional Webshare proxy username
        webshare_password: Optional Webshare proxy password
        http_proxy: Optional HTTP proxy URL
        https_proxy: Optional HTTPS proxy URL
        response_limit: Maximum number of characters for paginated responses (-1 for no pagination)
        next_cursor: Cursor for pagination

    Returns:
        Dictionary with transcript information
    """
    fetcher = YouTubeTranscriptFetcher(
        webshare_username=webshare_username,
        webshare_password=webshare_password,
        http_proxy=http_proxy,
        https_proxy=https_proxy,
        response_limit=response_limit
    )
    return fetcher.get_transcript(url, language, with_timestamps, next_cursor=next_cursor)


# Get video info convenience function
def get_youtube_video_info(
    url: str,
    webshare_username: Optional[str] = None,
    webshare_password: Optional[str] = None,
    http_proxy: Optional[str] = None,
    https_proxy: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to get YouTube video information without creating a fetcher instance.

    Args:
        url: YouTube video URL
        webshare_username: Optional Webshare proxy username
        webshare_password: Optional Webshare proxy password
        http_proxy: Optional HTTP proxy URL
        https_proxy: Optional HTTPS proxy URL

    Returns:
        Dictionary with video metadata
    """
    fetcher = YouTubeTranscriptFetcher(
        webshare_username=webshare_username,
        webshare_password=webshare_password,
        http_proxy=http_proxy,
        https_proxy=https_proxy
    )
    return fetcher.get_video_info(url)


# Direct yt-dlp function for transcript extraction
def get_transcript_via_ytdlp(
    url: str,
    timeout: int = 60,
    response_limit: int = -1,
    next_cursor: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a YouTube transcript using only yt-dlp.
    This is often more reliable than the YouTube Transcript API.

    Args:
        url: YouTube video URL
        timeout: Maximum time to wait for subtitle download
        response_limit: Maximum number of characters for paginated responses (-1 for no pagination)
        next_cursor: Cursor for pagination

    Returns:
        Dictionary with transcript information
    """
    try:
        # Try to extract video ID from URL
        try:
            video_id = extract_video_id(url)
        except ValueError:
            if not url.isalnum() or len(url) != 11:
                raise ValueError(f"Invalid YouTube video URL or ID: {url}")
            video_id = url
            url = f"https://www.youtube.com/watch?v={video_id}"

        # Create a temporary file for the subtitle
        with tempfile.NamedTemporaryFile(suffix='.vtt', delete=False) as temp_file:
            subtitle_path = temp_file.name

        logger.info(f"Fetching transcript for {url} using yt-dlp...")

        # bgutil plugins are automatically discovered by yt-dlp if installed

        # Configure yt-dlp options
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'subtitlesformat': 'vtt',
            'outtmpl': subtitle_path.replace('.vtt', ''),
            'quiet': True,
            'ignore_no_formats_error': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            },
            # Add extractor args to avoid SABR issues
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios']
                },
            },
        }

        # Configure bgutil POT provider parameters if available
        if BGUTIL_POT_PROVIDER_URL:
            logger.info(f"Using bgutil POT provider at {BGUTIL_POT_PROVIDER_URL}")
            # Select provider and set base_url for plugin
            ydl_opts['extractor_args']['youtube']['pot_provider'] = ['bgutil:http']
            ydl_opts['extractor_args'].setdefault('youtubepot-bgutilhttp', {})['base_url'] = [BGUTIL_POT_PROVIDER_URL]
            if POT_TRACE_ENABLED:
                ydl_opts['extractor_args']['youtube']['pot_trace'] = ['true']

        # Create a session to get the video title
        session = requests.Session()
        title = get_video_title(session, video_id, ["en"])

        # Run yt-dlp to download subtitles
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Check for subtitle files
        base_path = subtitle_path.replace('.vtt', '')
        subtitle_files = [f for f in os.listdir(os.path.dirname(base_path))
                        if os.path.isfile(os.path.join(os.path.dirname(base_path), f))
                        and f.startswith(os.path.basename(base_path))
                        and (f.endswith('.vtt') or f.endswith('.srt'))]

        if subtitle_files:
            # Use the first subtitle file found
            sub_file_path = os.path.join(os.path.dirname(base_path), subtitle_files[0])
            with open(sub_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Process the VTT/SRT file to extract just the text
            lines = []
            for line in content.split('\n'):
                # Skip timing lines and metadata
                if '-->' in line or line.strip().isdigit() or line.startswith('WEBVTT') or not line.strip():
                    continue
                lines.append(line.strip())

            transcript_text = '\n'.join(lines)
            return {
                "title": title,
                "transcript": transcript_text,
                "language": "auto",  # We don't know the exact language from yt-dlp
                "success": True,
                "video_id": video_id,
                "method": "yt-dlp-direct"
            }
        else:
            logger.warning("No subtitle files found with yt-dlp")
            return {
                "title": title,
                "transcript": "",
                "language": None,
                "success": False,
                "error": "No subtitle files found",
                "video_id": video_id
            }
    except Exception as e:
        logger.error(f"Error using yt-dlp for transcript: {e}")
        return {
            "title": "Unknown Title",
            "transcript": "",
            "language": None,
            "success": False,
            "error": str(e),
            "video_id": video_id if 'video_id' in locals() else "unknown"
        }
    finally:
        # Clean up temporary files
        try:
            if os.path.exists(subtitle_path):
                os.remove(subtitle_path)
            # Also try to remove any other subtitle files that might have been created
            if 'base_path' in locals():
                for file in os.listdir(os.path.dirname(base_path)):
                    if file.startswith(os.path.basename(base_path)) and (file.endswith('.vtt') or file.endswith('.srt')):
                        try:
                            os.remove(os.path.join(os.path.dirname(base_path), file))
                        except:
                            pass
        except:
            pass
