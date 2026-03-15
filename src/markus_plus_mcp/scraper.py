from __future__ import annotations

import asyncio
import contextlib
import urllib.request
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Any

import cachetools
from bs4 import BeautifulSoup
from playwright.async_api import Browser, async_playwright

BASE_URL = "https://markus.plus"
CONTENT_SELECTOR = ".markdown-preview-view"

_browser: Browser | None = None
_browser_lock = asyncio.Lock()

_page_cache: cachetools.TTLCache[str, str] = cachetools.TTLCache(maxsize=100, ttl=1800)
_cache_lock = asyncio.Lock()


async def _get_browser() -> Browser:  # pragma: no cover
    global _browser
    async with _browser_lock:
        if _browser is None or not _browser.is_connected():
            p = await async_playwright().start()
            _browser = await p.chromium.launch()
    return _browser


async def _get_page_html(path: str) -> str:  # pragma: no cover
    cached = _page_cache.get(path)
    if cached is not None:
        return cached

    browser = await _get_browser()
    page = await browser.new_page()
    try:
        await page.goto(f"{BASE_URL}{path}")
        with contextlib.suppress(Exception):
            await page.wait_for_selector(CONTENT_SELECTOR, timeout=10000)
        html = await page.content()
    finally:
        await page.close()

    async with _cache_lock:
        _page_cache[path] = html
    return html


async def get_page_text(path: str) -> str:
    html = await _get_page_html(path)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(CONTENT_SELECTOR)
    return content.get_text(separator="\n", strip=True) if content else ""


def _fetch_sitemap() -> list[str]:
    """Fetch and parse sitemap.xml using urllib (no JS needed)."""
    with urllib.request.urlopen(f"{BASE_URL}/sitemap.xml", timeout=10) as resp:
        body = resp.read()
    root = ET.parse(BytesIO(body)).getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [
        loc.text.replace(BASE_URL, "")
        for loc in root.findall(".//sm:loc", ns)
        if loc.text and loc.text.startswith(BASE_URL)
    ]


async def list_all_pages() -> list[str]:
    # Try sitemap.xml first (Obsidian Publish standard, no JS needed)
    try:
        loop = asyncio.get_event_loop()
        urls = await loop.run_in_executor(None, _fetch_sitemap)
        if urls:
            return urls
    except Exception:
        pass

    # Fallback: scrape nav links from homepage
    html = await _get_page_html("/")
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("nav a[href]")
    seen: set[str] = set()
    result: list[str] = []
    for a in links:
        href = a.get("href", "")
        if isinstance(href, str) and href.startswith("/") and href not in seen:
            seen.add(href)
            result.append(href)
    return result


async def search_pages(query: str) -> list[dict[str, Any]]:
    pages = await list_all_pages()
    results: list[dict[str, Any]] = []
    for path in pages:
        text = await get_page_text(path)
        lower_text = text.lower()
        lower_query = query.lower()
        if lower_query in lower_text:
            idx = lower_text.index(lower_query)
            excerpt = text[max(0, idx - 100) : idx + 200]
            results.append({"path": path, "excerpt": excerpt})
    return results


async def get_page_frontmatter(path: str) -> dict[str, str]:
    html = await _get_page_html(path)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(".metadata-container, .frontmatter")
    if not table:
        return {}
    rows = table.select("tr")
    result: dict[str, str] = {}
    for row in rows:
        key_el = row.select_one("th, td:first-child")
        val_el = row.select_one("td:last-child")
        if key_el and val_el and key_el != val_el:
            result[key_el.get_text(strip=True)] = val_el.get_text(strip=True)
    return result
