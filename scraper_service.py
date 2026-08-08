"""Scraper service module - refactored from webnovelScraper.py

This module provides web-friendly, testable scraping functions without console I/O.
"""

import requests
import time
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass
from bs4 import BeautifulSoup
from ebooklib import epub
from deep_translator import GoogleTranslator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from PIL import Image
import io


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/118.0.5993.118 Safari/537.36"
})


@dataclass
class Chapter:
    """Represents a scraped chapter with metadata."""
    index: int  # 1-based sequence number
    title: str
    body: str
    title_translated: bool = False
    body_translated: bool = False


def normalize_filename(name: str, title: str) -> str:
    """Derive filename from title when name is empty, ensure exactly one .epub suffix.
    
    Args:
        name: User-provided filename (may be empty)
        title: Book title to derive filename from if name is empty
        
    Returns:
        Normalized filename ending in exactly one .epub extension
        
    Validates: Requirements 1.7, 1.8
    """
    # Use title if name is empty
    if not name or not name.strip():
        filename = title.strip()
    else:
        filename = name.strip()
    
    # Remove any existing .epub suffix (case-insensitive)
    if filename.lower().endswith('.epub'):
        filename = filename[:-5]
    
    # Ensure exactly one .epub suffix
    filename += '.epub'
    
    return filename


def derive_toc_url(main_url: str) -> str:
    """Derive table-of-contents URL from main page URL.
    
    Args:
        main_url: Main page URL of the webnovel
        
    Returns:
        TOC URL (main_url + "/chapter")
        
    Validates: Requirements 2.1
    """
    return main_url + "/chapter"


def safe_get(url: str, *, attempts: int = 3, delay: int = 2, timeout: int = 30) -> Optional[requests.Response]:
    """Fetch URL with retries, retry only on transient errors.
    
    Makes up to `attempts` total attempts with `delay` seconds between attempts.
    Each attempt has a `timeout` second timeout.
    
    Retries only on transient errors:
    - Connection failures (requests.ConnectionError)
    - Timeouts (requests.Timeout)
    - Server errors (5xx status codes)
    
    Does NOT retry on non-transient errors:
    - Client errors (4xx status codes)
    
    Args:
        url: URL to fetch
        attempts: Total number of attempts (default: 3)
        delay: Seconds to wait between attempts (default: 2)
        timeout: Timeout in seconds per attempt (default: 30)
        
    Returns:
        Response object on success, None when all attempts exhausted
        
    Validates: Requirements 7.1, 7.2, 7.4, 7.5
    """
    for attempt in range(1, attempts + 1):
        try:
            response = SESSION.get(url, timeout=timeout)
            
            # Check for 4xx errors (non-transient - don't retry)
            if 400 <= response.status_code < 500:
                # Non-transient error, return None immediately without retry
                return None
            
            # Raise for 5xx errors (transient - will retry)
            response.raise_for_status()
            
            # Success
            return response
            
        except (requests.ConnectionError, requests.Timeout) as e:
            # Transient errors - retry
            if attempt < attempts:
                time.sleep(delay)
            # If this was the last attempt, fall through to return None
            
        except requests.HTTPError as e:
            # HTTPError for 5xx (transient - retry)
            if attempt < attempts:
                time.sleep(delay)
            # If this was the last attempt, fall through to return None
            
        except requests.RequestException as e:
            # Other request exceptions - treat as transient, retry
            if attempt < attempts:
                time.sleep(delay)
            # If this was the last attempt, fall through to return None
    
    # All attempts exhausted
    return None



def translate_text(text: str, translator, timeout: int = 60) -> tuple[str, bool]:
    """Translate text with a hard time bound, falling back to original on failure.
    
    Args:
        text: Text to translate
        translator: GoogleTranslator instance (or None to skip translation)
        timeout: Maximum seconds to wait for translation
        
    Returns:
        Tuple of (result_text, translated_ok) where translated_ok is False
        when original text was kept due to failure or timeout
        
    Validates: Requirements 4.4, 4.5
    """
    if not translator:
        return text, False
    
    notices = []
    
    def translate_chunked(text, translator, chunk_size=4000):
        """Translate text in chunks to avoid size limits."""
        translated = ""
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            try:
                translated += translator.translate(chunk)
            except Exception as e:
                notices.append(f"Translation failed: {e}")
                return text
            start = end
        return translated
    
    # Run translation in a worker thread with timeout
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(translate_chunked, text, translator)
    
    try:
        result = future.result(timeout=timeout)
    except FuturesTimeoutError:
        notices.append(f"Translation timed out after {timeout} seconds")
        result = text
    except Exception as e:
        notices.append(f"Translation failed: {e}")
        result = text
    finally:
        executor.shutdown(wait=False)
    
    translated_ok = not notices
    return result, translated_ok


def fetch_chapters(
    toc_url: str,
    chapter_count: int,
    do_translate: bool,
    translator,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> List[Chapter]:
    """Fetch chapters sequentially with progress callback, fallback titles, and translation.
    
    Fetches chapters from 1 up to chapter_count, stopping at the first stopping
    condition (missing page, empty content, or exhausted retries). Keeps chapters
    already retrieved.
    
    Args:
        toc_url: Table of contents URL base (e.g., "https://site.com/novel/chapter")
        chapter_count: Maximum number of chapters to fetch
        do_translate: Whether to translate chapter title and body
        translator: GoogleTranslator instance (or None)
        progress_callback: Optional callback to report progress events
        
    Returns:
        List of Chapter objects (may be fewer than chapter_count if stopped early)
        
    Validates: Requirements 2.3, 2.4, 2.5, 2.6, 4.2, 4.3, 4.4, 4.5
    """
    chapters = []
    
    def notify(event: Dict[str, Any]):
        """Helper to call progress callback if provided."""
        if progress_callback:
            progress_callback(event)
    
    for index in range(1, chapter_count + 1):
        # Notify starting this chapter
        notify({"type": "chapter_start", "index": index, "total": chapter_count})
        
        # Construct chapter URL
        url = f"{toc_url}-{index}"
        
        # Fetch chapter page using safe_get (with retries)
        response = safe_get(url)
        
        # Stopping condition: missing page or exhausted retries
        if response is None:
            notify({"type": "chapter_missing", "index": index, "url": url})
            break
        
        # Parse HTML
        soup = BeautifulSoup(response.text, "html.parser")
        content = soup.select_one("#content")
        
        # Stopping condition: empty content
        if content is None:
            notify({"type": "chapter_empty", "index": index, "url": url})
            break
        
        # Extract title (with fallback)
        title_tag = soup.select_one("span.chapter-title")
        if title_tag is not None:
            chapter_title = title_tag.get_text(strip=True)
        else:
            # Fallback title identifying chapter by sequence number (Req 2.6)
            chapter_title = f"Chapter {index}"
            notify({"type": "title_fallback", "index": index})
        
        # Extract body text
        chapter_body = content.get_text("\n", strip=True)
        
        # Translate independently if enabled (Req 4.2, 4.4, 4.5)
        title_translated = False
        body_translated = False
        
        if do_translate:
            # Translate title (independent, 60s bounded, fallback on failure)
            translated_title, title_ok = translate_text(chapter_title, translator, timeout=60)
            if title_ok:
                chapter_title = translated_title
                title_translated = True
            else:
                notify({
                    "type": "translation_failure",
                    "field": "title",
                    "index": index
                })
            
            # Translate body (independent, 60s bounded, fallback on failure)
            translated_body, body_ok = translate_text(chapter_body, translator, timeout=60)
            if body_ok:
                chapter_body = translated_body
                body_translated = True
            else:
                notify({
                    "type": "translation_failure",
                    "field": "body",
                    "index": index
                })
        
        # Create chapter object
        chapter = Chapter(
            index=index,
            title=chapter_title,
            body=chapter_body,
            title_translated=title_translated,
            body_translated=body_translated
        )
        chapters.append(chapter)
        
        # Notify chapter complete
        notify({
            "type": "chapter_complete",
            "index": index,
            "fetched": len(chapters),
            "total": chapter_count
        })
        
        # Small delay to avoid hammering the server
        time.sleep(0.2)
    
    return chapters


def fetch_cover(main_url: str, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> Optional[bytes]:
    """Fetch and validate cover image from main URL.
    
    Retrieves cover via safe_get semantics (3 attempts, 30s timeout), validates
    as a decodable raster image with size 1 byte–10 MB. Treats empty/oversized/
    undecodable as unavailable.
    
    Args:
        main_url: Main page URL of the webnovel
        progress_callback: Optional callback to report progress events
        
    Returns:
        Cover image bytes if valid, None if unavailable
        
    Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
    """
    def notify(event: Dict[str, Any]):
        if progress_callback:
            progress_callback(event)
    
    notify({"type": "cover_fetch_start"})
    
    # Fetch main page to find cover image
    response = safe_get(main_url)
    if response is None:
        notify({"type": "cover_unavailable", "reason": "main page not accessible"})
        return None
    
    # Parse HTML to find cover image
    soup = BeautifulSoup(response.text, "html.parser")
    img_tag = soup.select_one("figure.cover img")
    
    if not img_tag:
        notify({"type": "cover_unavailable", "reason": "no cover image tag found"})
        return None
    
    # Get image source URL
    src = img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("src")
    if not src:
        notify({"type": "cover_unavailable", "reason": "no valid image source"})
        return None
    
    # Fetch cover image bytes
    cover_response = safe_get(src)
    if cover_response is None:
        notify({"type": "cover_unavailable", "reason": "image download failed"})
        return None
    
    cover_bytes = cover_response.content
    
    # Validate: size must be 1 byte to 10 MB (Req 3.2)
    size_mb = len(cover_bytes) / (1024 * 1024)
    if len(cover_bytes) < 1 or size_mb > 10:
        notify({"type": "cover_invalid", "reason": f"size {size_mb:.2f} MB out of range"})
        return None
    
    # Validate: must be decodable raster image (Req 3.2)
    try:
        img = Image.open(io.BytesIO(cover_bytes))
        img.verify()  # Verify it's a valid image
        notify({"type": "cover_valid", "size_mb": size_mb})
        return cover_bytes
    except Exception as e:
        notify({"type": "cover_invalid", "reason": f"not a valid image: {e}"})
        return None


def build_epub(chapters: List[Chapter], cover: Optional[bytes], title: str, author: str) -> bytes:
    """Build EPUB from chapters, preserving fetch order and embedding cover.
    
    Produces exactly one EPUB containing chapters in their original fetch order,
    embedding cover only when valid, setting title/author from user values.
    
    Args:
        chapters: List of Chapter objects in fetch order
        cover: Cover image bytes (or None)
        title: EPUB title
        author: EPUB author
        
    Returns:
        EPUB file content as bytes
        
    Validates: Requirements 2.7, 2.8, 3.2
    """
    book = epub.EpubBook()
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    
    # Embed cover if valid (Req 3.2)
    if cover:
        book.set_cover("cover.jpg", cover)
    
    # Add chapters in fetch order (Req 2.7)
    epub_chapters = []
    for chapter in chapters:
        chap = epub.EpubHtml(
            title=chapter.title,
            file_name=f"chap_{chapter.index}.xhtml"
        )
        html_content = f"<h1>{chapter.title}</h1>\n"
        html_content += "<p>" + chapter.body.replace("\n", "<br/>") + "</p>"
        chap.content = html_content
        book.add_item(chap)
        epub_chapters.append(chap)
    
    # Set up table of contents and spine
    book.toc = tuple(epub_chapters)
    book.spine = ["nav"] + epub_chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    # Write EPUB to bytes
    epub_bytes = io.BytesIO()
    epub.write_epub(epub_bytes, book)
    return epub_bytes.getvalue()


def run_scrape(params: Dict[str, Any], progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> bytes:
    """Orchestrate full scrape: TOC derivation → chapter fetch → cover → EPUB bytes.
    
    Args:
        params: Dictionary with keys:
            - source_url: Main page URL
            - title: Book title
            - author: Book author
            - chapter_count: Number of chapters to fetch
            - translate: Whether to translate (bool)
        progress_callback: Optional callback to report progress events
        
    Returns:
        EPUB file content as bytes
        
    Validates: Requirements 2.1, 2.3-2.8, 3.1-3.5, 4.2-4.5
    """
    def notify(event: Dict[str, Any]):
        if progress_callback:
            progress_callback(event)
    
    # Extract parameters
    source_url = params["source_url"]
    title = params["title"]
    author = params.get("author", "Unknown")
    chapter_count = params["chapter_count"]
    do_translate = params.get("translate", False)
    
    # Derive TOC URL (Req 2.1)
    toc_url = derive_toc_url(source_url)
    notify({"type": "stage", "stage": "toc_derived", "toc_url": toc_url})
    
    # Initialize translator if needed
    translator = None
    if do_translate:
        try:
            translator = GoogleTranslator(source="auto", target="en")
            notify({"type": "translator_ready"})
        except Exception as e:
            notify({"type": "translator_failed", "error": str(e)})
            # Continue without translation
    
    # Fetch chapters
    notify({"type": "stage", "stage": "fetching_chapters"})
    chapters = fetch_chapters(toc_url, chapter_count, do_translate, translator, progress_callback)
    
    if not chapters:
        raise ValueError("No chapters were fetched")
    
    # Fetch cover
    notify({"type": "stage", "stage": "fetching_cover"})
    cover = fetch_cover(source_url, progress_callback)
    
    # Build EPUB
    notify({"type": "stage", "stage": "building_epub"})
    epub_bytes = build_epub(chapters, cover, title, author)
    
    notify({"type": "stage", "stage": "complete", "size_bytes": len(epub_bytes)})
    return epub_bytes
