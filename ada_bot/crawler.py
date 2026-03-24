"""
Web crawler: discovers all pages of a site and its subdirectories.

Strategy
--------
1. Start from the given URL.
2. Follow every internal ``<a href>`` that stays on the same origin.
3. Respect an optional ``max_depth`` and ``max_pages`` limit.
4. Optionally honour ``robots.txt``.
5. Return a list of :class:`PageInfo` objects, each carrying the URL,
   final status code, response time, page title, and the raw HTML.
"""

from __future__ import annotations

import re
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class PageInfo:
    """Minimal metadata about a discovered page."""

    url: str
    status_code: int
    response_time_ms: float
    title: str
    html: str
    depth: int = 0
    error: Optional[str] = None


class Crawler:
    """Breadth-first crawler that stays within the origin of *start_url*."""

    _DEFAULT_HEADERS = {
        "User-Agent": (
            "ADAComplianceBot/1.0 (+https://github.com/JeffreyLebowsk1/ada-compliance)"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(
        self,
        start_url: str,
        *,
        max_pages: int = 200,
        max_depth: int = 10,
        timeout: int = 30,
        respect_robots: bool = True,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        headers: dict[str, str] | None = None,
        on_page_discovered: object = None,
    ) -> None:
        self.start_url = start_url.rstrip("/")
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.include_patterns = [re.compile(p) for p in (include_patterns or [])]
        self.exclude_patterns = [re.compile(p) for p in (exclude_patterns or [])]
        self.on_page_discovered = on_page_discovered  # callable(PageInfo)

        parsed = urlparse(self.start_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"

        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(headers or self._DEFAULT_HEADERS)
        self._session = session

        self._robots: urllib.robotparser.RobotFileParser | None = None
        if respect_robots:
            self._robots = self._load_robots()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def crawl(self) -> list[PageInfo]:
        """Crawl the site and return a list of :class:`PageInfo` objects."""
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(self.start_url, 0)])
        pages: list[PageInfo] = []

        while queue and len(pages) < self.max_pages:
            url, depth = queue.popleft()
            url = self._normalise(url)

            if url in visited:
                continue
            if depth > self.max_depth:
                continue
            if not self._is_allowed(url):
                continue

            visited.add(url)
            page = self._fetch(url, depth)
            pages.append(page)

            if self.on_page_discovered:
                try:
                    self.on_page_discovered(page)
                except Exception:
                    pass

            if page.error or page.status_code >= 400:
                continue

            for link in self._extract_links(page.html, url):
                link = self._normalise(link)
                if link not in visited and self._is_internal(link):
                    queue.append((link, depth + 1))

        return pages

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch(self, url: str, depth: int) -> PageInfo:
        t0 = time.perf_counter()
        try:
            resp = self._session.get(url, timeout=self.timeout, allow_redirects=True)
            elapsed = (time.perf_counter() - t0) * 1000
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return PageInfo(
                    url=url,
                    status_code=resp.status_code,
                    response_time_ms=elapsed,
                    title="",
                    html="",
                    depth=depth,
                    error=f"Non-HTML content type: {content_type}",
                )
            html = resp.text
            title = self._extract_title(html)
            return PageInfo(
                url=url,
                status_code=resp.status_code,
                response_time_ms=elapsed,
                title=title,
                html=html,
                depth=depth,
            )
        except requests.RequestException as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            return PageInfo(
                url=url,
                status_code=0,
                response_time_ms=elapsed,
                title="",
                html="",
                depth=depth,
                error=str(exc),
            )

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        from bs4 import BeautifulSoup

        links: list[str] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup.find_all("a", href=True):
                href = tag["href"].strip()
                if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                    continue
                full = urljoin(base_url, href)
                full, _ = urldefrag(full)
                links.append(full)
        except Exception:
            pass
        return links

    @staticmethod
    def _extract_title(html: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
        return ""

    def _is_internal(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        return f"{parsed.scheme}://{parsed.netloc}" == self.origin

    def _is_allowed(self, url: str) -> bool:
        if self.include_patterns and not any(p.search(url) for p in self.include_patterns):
            return False
        if any(p.search(url) for p in self.exclude_patterns):
            return False
        if self._robots and not self._robots.can_fetch("*", url):
            return False
        return True

    def _load_robots(self) -> urllib.robotparser.RobotFileParser:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{self.origin}/robots.txt")
        try:
            rp.read()
        except Exception:
            # If robots.txt cannot be fetched, be permissive (allow all).
            # Without this, can_fetch() returns False for every URL because
            # last_checked is never set on a failed read.
            rp.allow_all = True
        return rp

    @staticmethod
    def _normalise(url: str) -> str:
        url, _ = urldefrag(url)
        return url.rstrip("/") if url != "/" else url
