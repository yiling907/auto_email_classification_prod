#!/usr/bin/env python3
"""
Laya Healthcare website crawler.
Crawls https://www.layahealthcare.ie/, extracts clean text from each page,
and saves one .txt file per page under tests/test_data/knowledge_base/.
"""
import os
import re
import time
import hashlib
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

START_URL = "https://www.layahealthcare.ie/"
BASE_DOMAIN = "www.layahealthcare.ie"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "test_data" / "knowledge_base"

MAX_PAGES = 500          # safety cap
REQUEST_DELAY = 1.0      # seconds between requests (be polite)
REQUEST_TIMEOUT = 15     # seconds
MAX_RETRIES = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; InsureMailKnowledgeCrawler/1.0; "
        "+https://github.com/insuremail)"
    ),
    "Accept-Language": "en-IE,en;q=0.9",
}

# URL path prefixes to skip (non-content pages)
SKIP_PREFIXES = (
    "/cdn-cgi/", "/wp-admin/", "/wp-login",
    "/feed/", "/xmlrpc", "/sitemap",
    "/.well-known/",
)

# File extensions to skip
SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".zip", ".gz", ".tar", ".exe",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".ico",
}

# HTML tags whose text is noise
NOISE_TAGS = [
    "script", "style", "noscript", "nav", "header", "footer",
    "aside", "form", "button", "iframe", "figure", "figcaption",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalise_url(url: str) -> str:
    """Strip fragment and trailing slash for deduplication."""
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, query="", fragment="").geturl()


def is_crawlable(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != BASE_DOMAIN:
        return False
    if parsed.scheme not in ("http", "https", ""):
        return False
    path = parsed.path.lower()
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return False
    ext = Path(path).suffix.lower()
    if ext in SKIP_EXTENSIONS:
        return False
    return True


def url_to_filename(url: str) -> str:
    """Convert a URL to a safe, human-readable filename."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "__") or "index"
    path = re.sub(r"[^\w\-.]", "_", path)
    if not path:
        path = "index"
    # Truncate and add hash suffix to avoid collisions on very long paths
    if len(path) > 120:
        h = hashlib.md5(path.encode()).hexdigest()[:8]
        path = path[:112] + "_" + h
    return path + ".txt"


def extract_text(soup: BeautifulSoup, url: str) -> str:
    """Extract clean, structured plain text from a BeautifulSoup page."""
    # Remove noise tags
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    # Page title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Meta description
    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_desc = meta["content"].strip()

    # Main content: prefer <main> or <article>, fall back to <body>
    main = soup.find("main") or soup.find("article") or soup.find("body")
    if not main:
        main = soup

    lines = []
    if title:
        lines.append(f"PAGE TITLE: {title}")
        lines.append("=" * 60)
    if meta_desc:
        lines.append(f"DESCRIPTION: {meta_desc}")
        lines.append("")
    lines.append(f"SOURCE URL: {url}")
    lines.append("")

    # Walk content elements in document order
    for elem in main.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "dt", "dd"]):
        tag = elem.name
        text = elem.get_text(separator=" ", strip=True)
        if not text or len(text) < 3:
            continue
        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text).strip()

        if tag == "h1":
            lines.append(f"\n## {text}")
        elif tag == "h2":
            lines.append(f"\n### {text}")
        elif tag in ("h3", "h4", "h5", "h6"):
            lines.append(f"\n#### {text}")
        elif tag == "li":
            lines.append(f"  - {text}")
        elif tag in ("td", "th"):
            lines.append(f"  | {text}")
        elif tag in ("dt", "dd"):
            lines.append(f"  {text}")
        else:  # p
            lines.append(text)

    body = "\n".join(lines).strip()

    # Drop very short or near-empty pages
    if len(body) < 200:
        return ""

    return body


def fetch(session: requests.Session, url: str) -> str | None:
    """Fetch a URL and return HTML string, or None on failure."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS, allow_redirects=True)
            ct = resp.headers.get("Content-Type", "")
            if "text/html" not in ct:
                return None
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (301, 302, 303, 307, 308):
                return None  # requests follows redirects automatically
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"  [429] Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            print(f"  [HTTP {resp.status_code}] {url}")
            return None
        except requests.exceptions.Timeout:
            print(f"  [TIMEOUT] attempt {attempt+1} — {url}")
        except requests.exceptions.RequestException as e:
            print(f"  [ERROR] {e} — {url}")
            break
    return None


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

def crawl() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    visited: set[str] = set()
    queue: deque[str] = deque([normalise_url(START_URL)])
    saved = 0
    skipped = 0

    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"Starting crawl of {START_URL}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Max pages: {MAX_PAGES}\n")

    while queue and saved + skipped < MAX_PAGES:
        url = queue.popleft()

        if url in visited:
            continue
        visited.add(url)

        print(f"[{saved + 1:>3}] Fetching: {url}")
        html = fetch(session, url)
        time.sleep(REQUEST_DELAY)

        if not html:
            skipped += 1
            continue

        soup = BeautifulSoup(html, "lxml")

        # Extract and save text
        text = extract_text(soup, url)
        if text:
            fname = url_to_filename(url)
            fpath = OUTPUT_DIR / fname
            # Avoid overwriting if filename collision
            if fpath.exists():
                h = hashlib.md5(url.encode()).hexdigest()[:6]
                fpath = OUTPUT_DIR / (fpath.stem + f"_{h}.txt")
            fpath.write_text(text, encoding="utf-8")
            saved += 1
            print(f"       → saved as {fpath.name} ({len(text):,} chars)")
        else:
            skipped += 1
            print(f"       → skipped (too short / no content)")

        # Discover links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            abs_url = normalise_url(urljoin(url, href))
            if is_crawlable(abs_url) and abs_url not in visited:
                queue.append(abs_url)

    print(f"\n{'='*60}")
    print(f"Crawl complete.")
    print(f"  Pages saved : {saved}")
    print(f"  Pages skipped: {skipped}")
    print(f"  Output dir  : {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    crawl()
