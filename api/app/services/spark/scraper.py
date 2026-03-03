"""
Web Scraper — BFS domain crawler for client website ingestion.

Crawls a client's website, extracts text from each page, and stores
results as spark_uploads rows with source_type='scrape'.

Design:
  - BFS from homepage URL
  - Same-domain internal links only
  - Respects robots.txt
  - Rate limit: 1 request/second (polite crawling)
  - Max 200 pages per domain (safety cap)
  - Strips HTML using existing _strip_html() pattern
  - Excludes /blog, /news, /press, /tag, /category URL patterns

Called as Stage 0 of the pipeline, NOT a separate endpoint.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from collections import deque
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from uuid import UUID, uuid4

import httpx
from bs4 import BeautifulSoup

from app.services.spark.ingestion import _strip_html
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

_MAX_PAGES = 200
_REQUEST_DELAY_SECONDS = 1.0
_REQUEST_TIMEOUT_SECONDS = 15
_USER_AGENT = "KinSparkBot/1.0 (+https://trykin.ai)"

# URL path patterns to exclude (low-signal, high-volume content)
_EXCLUDE_PATTERNS = re.compile(
    r"/(?:blog|news|press|tag|category|tags|categories|author|feed|rss|wp-json|wp-admin|wp-content|wp-includes)",
    re.IGNORECASE,
)

# File extensions to skip
_SKIP_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".zip", ".gz", ".tar",
    ".css", ".js", ".xml", ".json", ".ico", ".woff", ".woff2",
    ".ttf", ".eot",
})


def _is_safe_url(url: str) -> bool:
    """Check that a URL does not resolve to a private/reserved IP (SSRF protection)."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return False

    # Block obvious private hostnames
    if hostname in ("localhost", "0.0.0.0", "[::]"):
        return False

    try:
        # Resolve hostname to IP addresses
        addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False

    for family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
            return False

    return True


def _normalize_url(url: str) -> str:
    """Normalize URL: strip fragment, trailing slash, lowercase scheme+host."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _is_same_domain(url: str, base_domain: str) -> bool:
    """Check if URL is on the same domain as base."""
    parsed = urlparse(url)
    return parsed.netloc.lower() == base_domain.lower()


def _should_skip_url(url: str) -> bool:
    """Check if URL should be excluded based on path patterns or extensions."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Skip file extensions
    for ext in _SKIP_EXTENSIONS:
        if path.endswith(ext):
            return True

    # Skip excluded path patterns
    if _EXCLUDE_PATTERNS.search(path):
        return True

    return False


def _extract_links(html: str, base_url: str, base_domain: str) -> list[str]:
    """Extract same-domain internal links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"]

        # Skip anchors, mailto, tel, javascript
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)

        # Only same-domain
        if not _is_same_domain(absolute, base_domain):
            continue

        # Skip excluded patterns
        if _should_skip_url(absolute):
            continue

        normalized = _normalize_url(absolute)
        links.append(normalized)

    return links


def _get_robots_parser(robots_txt: str, base_url: str) -> RobotFileParser:
    """Parse robots.txt content."""
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp


async def scrape_website(
    client_id: UUID,
    website_url: str,
    progress_callback: Callable[[int, int], Any] | None = None,
) -> int:
    """BFS crawl a website and store scraped pages as spark_uploads.

    Args:
        client_id: The client to associate uploads with.
        website_url: The homepage URL to start crawling from.
        progress_callback: Optional async callback(pages_scraped, total_discovered)
            for progress updates.

    Returns:
        Number of pages scraped.
    """
    parsed_base = urlparse(website_url)
    base_domain = parsed_base.netloc.lower()
    start_url = _normalize_url(website_url)

    # SSRF protection: reject private/reserved IPs
    if not _is_safe_url(start_url):
        logger.warning("SSRF blocked: %s resolves to private/reserved IP", website_url)
        return 0

    sb = await get_supabase_client()

    # Delete existing scrape uploads for this client (clean re-scrape)
    await (
        sb.table("spark_uploads")
        .delete()
        .eq("client_id", str(client_id))
        .eq("source_type", "scrape")
        .execute()
    )

    # Fetch robots.txt
    robots_parser: RobotFileParser | None = None
    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
        ) as http:
            robots_url = f"{parsed_base.scheme}://{base_domain}/robots.txt"
            resp = await http.get(robots_url, follow_redirects=True)
            if resp.status_code == 200:
                robots_parser = _get_robots_parser(resp.text, robots_url)
                logger.info("Loaded robots.txt from %s", robots_url)
    except Exception:
        logger.info("No robots.txt found for %s, proceeding without", base_domain)

    # BFS crawl
    visited: set[str] = set()
    queue: deque[str] = deque([start_url])
    pages_scraped = 0

    async with httpx.AsyncClient(
        timeout=_REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as http:
        while queue and pages_scraped < _MAX_PAGES:
            url = queue.popleft()

            if url in visited:
                continue
            visited.add(url)

            # SSRF check on each discovered URL
            if not _is_safe_url(url):
                logger.debug("SSRF blocked discovered URL: %s", url)
                continue

            # Check robots.txt
            if robots_parser and not robots_parser.can_fetch(_USER_AGENT, url):
                logger.debug("Robots.txt disallows: %s", url)
                continue

            # Skip excluded patterns
            if _should_skip_url(url):
                continue

            try:
                resp = await http.get(url)

                # Only process HTML
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type.lower():
                    continue

                if resp.status_code != 200:
                    continue

                html = resp.text
                if not html or len(html) < 100:
                    continue

                # Extract text
                text = _strip_html(html)
                if not text or len(text) < 50:
                    continue

                # Extract page title
                soup = BeautifulSoup(html, "html.parser")
                title_tag = soup.find("title")
                page_title = title_tag.get_text(strip=True) if title_tag else url

                # Store as spark_uploads row
                upload_id = uuid4()
                await (
                    sb.table("spark_uploads")
                    .insert(
                        {
                            "id": str(upload_id),
                            "client_id": str(client_id),
                            "filename": f"scrape_{pages_scraped + 1}.html",
                            "original_name": page_title[:255],
                            "mime_type": "text/html",
                            "file_size": len(html),
                            "storage_path": f"{client_id}/scrape/{upload_id}",
                            "source_type": "scrape",
                            "status": "parsed",
                            "parsed_text": text,
                            "page_count": 1,
                        }
                    )
                    .execute()
                )

                pages_scraped += 1

                # Report progress
                if progress_callback is not None:
                    await progress_callback(pages_scraped, len(visited) + len(queue))

                # Extract links for further crawling
                new_links = _extract_links(html, url, base_domain)
                for link in new_links:
                    if link not in visited:
                        queue.append(link)

                # Rate limit — polite crawling
                await asyncio.sleep(_REQUEST_DELAY_SECONDS)

            except httpx.TimeoutException:
                logger.debug("Timeout fetching %s, skipping", url)
            except httpx.HTTPError as e:
                logger.debug("HTTP error fetching %s: %s", url, e)
            except Exception:
                logger.warning("Error scraping %s", url, exc_info=True)

    logger.info(
        "Scrape complete for %s: %d pages scraped, %d URLs visited",
        base_domain,
        pages_scraped,
        len(visited),
    )
    return pages_scraped
