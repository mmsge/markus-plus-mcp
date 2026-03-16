from __future__ import annotations

import asyncio
import contextlib
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
_pages_cache: cachetools.TTLCache[str, list[str]] = cachetools.TTLCache(maxsize=1, ttl=1800)
_pages_cache_lock = asyncio.Lock()


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
    if content:
        text = content.get_text(separator="\n", strip=True)
        if text:
            return text
    # Fallback: broader content selectors for pages with non-standard structure
    for selector in [".view-content", "main", "article"]:
        content = soup.select_one(selector)
        if content:
            text = content.get_text(separator="\n", strip=True)
            if text:
                return text
    return ""


async def _fetch_sitemap() -> list[str]:
    """Fetch and parse sitemap.xml using Playwright (handles bot protection/CDN blocking)."""
    browser = await _get_browser()
    page = await browser.new_page()
    try:
        response = await page.goto(f"{BASE_URL}/sitemap.xml")
        if response is None or not response.ok:
            return []
        body = await response.body()
    finally:
        await page.close()

    root = ET.parse(BytesIO(body)).getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = root.findall(".//sm:loc", ns)
    if not locs:
        # Fallback: try without namespace prefix (some sitemap generators omit it)
        locs = root.findall(".//loc")
    paths = []
    for loc in locs:
        if not loc.text or not loc.text.startswith(BASE_URL):
            continue
        path = loc.text.removeprefix(BASE_URL) or "/"
        # Skip internal Obsidian Publish configuration entries
        if path.startswith("/_publish/"):
            continue
        paths.append(path)
    return paths


async def _fetch_homepage_for_nav() -> str:  # pragma: no cover
    """Fetch homepage HTML waiting specifically for nav elements, bypassing the content cache."""
    browser = await _get_browser()
    page = await browser.new_page()
    try:
        await page.goto(BASE_URL)
        with contextlib.suppress(Exception):
            await page.wait_for_selector(".nav-file-title", timeout=10000)
        return await page.content()
    finally:
        await page.close()


async def list_all_pages() -> list[str]:
    async with _pages_cache_lock:
        cached = _pages_cache.get("pages")
        if cached is not None:
            return cached

    # Try sitemap.xml first (Obsidian Publish standard, no JS needed)
    try:
        urls = await _fetch_sitemap()
        if urls:
            async with _pages_cache_lock:
                _pages_cache["pages"] = urls
            return urls
    except Exception:
        pass

    # Fallback: scrape Obsidian Publish nav from homepage, waiting for nav elements
    html = await _fetch_homepage_for_nav()
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[str] = []

    # Obsidian Publish file tree: .nav-file-title[data-path] (e.g. data-path="om.md")
    for el in soup.select(".nav-file-title[data-path]"):
        data_path = el.get("data-path", "")
        if isinstance(data_path, str) and data_path:
            slug = "/" + data_path.removesuffix(".md")
            if slug not in seen:
                seen.add(slug)
                result.append(slug)

    if result:
        async with _pages_cache_lock:
            _pages_cache["pages"] = result
        return result

    # Final fallback: generic nav links
    for a in soup.select("nav a[href]"):
        href = a.get("href", "")
        if isinstance(href, str) and href.startswith("/") and href not in seen:
            seen.add(href)
            result.append(href)
    if result:
        async with _pages_cache_lock:
            _pages_cache["pages"] = result
    return result


async def search_pages(
    query: str, offset: int = 0, page_size: int = 10
) -> dict[str, Any]:
    all_pages = await list_all_pages()
    total_pages = len(all_pages)
    batch = all_pages[offset : offset + page_size]
    lower_query = query.lower()
    semaphore = asyncio.Semaphore(5)

    async def check_page(path: str) -> dict[str, Any] | None:
        async with semaphore:
            try:
                text = await get_page_text(path)
            except Exception:
                return None
            lower_text = text.lower()
            if lower_query in lower_text:
                idx = lower_text.index(lower_query)
                excerpt = text[max(0, idx - 100) : idx + 200]
                return {"path": path, "excerpt": excerpt}
            return None

    hits = await asyncio.gather(*[check_page(p) for p in batch])
    matches = [h for h in hits if h is not None]
    next_offset = offset + page_size
    return {
        "matches": matches,
        "offset": offset,
        "page_size": page_size,
        "pages_searched": len(batch),
        "next_offset": next_offset if next_offset < total_pages else None,
        "total_pages": total_pages,
    }


async def get_page_frontmatter(path: str) -> dict[str, str]:
    html = await _get_page_html(path)
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, str] = {}

    # Obsidian Publish (v1.4+): .metadata-property elements
    for prop in soup.select(".metadata-property"):
        key_el = prop.select_one(".metadata-property-name")
        val_el = prop.select_one(".metadata-property-value")
        if key_el and val_el:
            result[key_el.get_text(strip=True)] = val_el.get_text(strip=True)

    if result:
        return result

    # Fallback: table-based .metadata-container or .frontmatter
    table = soup.select_one(".metadata-container, .frontmatter")
    if not table:
        return {}
    for row in table.select("tr"):
        key_el = row.select_one("th, td:first-child")
        val_el = row.select_one("td:last-child")
        if key_el and val_el and key_el != val_el:
            result[key_el.get_text(strip=True)] = val_el.get_text(strip=True)
    return result
