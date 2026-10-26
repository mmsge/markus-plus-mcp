from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import cachetools
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Browser, async_playwright

BASE_URL = "https://markus.plus"
CONTENT_SELECTOR = ".markdown-preview-view"

# Obsidian Publish serves the vault index and raw markdown without a browser
SITE_ID = "8528a8f5ceabc10547ce0121dbdada5d"
INDEX_URL = f"https://publish-01.obsidian.md/cache/{SITE_ID}"
ACCESS_URL = f"https://publish-01.obsidian.md/access/{SITE_ID}"
INDEX_REFRESH_INTERVAL = 60.0
HTTP_TIMEOUT = 15.0

_browser: Browser | None = None
_browser_lock = asyncio.Lock()

_page_cache: cachetools.TTLCache[str, str] = cachetools.TTLCache(maxsize=100, ttl=1800)
_cache_lock = asyncio.Lock()
_pages_cache: cachetools.TTLCache[str, list[str]] = cachetools.TTLCache(maxsize=1, ttl=1800)
_pages_cache_lock = asyncio.Lock()
_index_cache: cachetools.TTLCache[str, dict[str, Any]] = cachetools.TTLCache(maxsize=1, ttl=1800)
_index_lock = asyncio.Lock()
_last_index_fetch = float("-inf")

_FRONTMATTER_RE = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(?:.*?\r?\n)?(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.DOTALL
)


class PageNotFoundError(LookupError):
    """Raised when a path matches no page in the published vault."""


async def _http_get_text(url: str) -> str:  # pragma: no cover
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def _fetch_index() -> dict[str, Any]:
    data = json.loads(await _http_get_text(INDEX_URL))
    if not isinstance(data, dict):
        raise ValueError("Unexpected index format from Obsidian Publish")
    return data


async def _load_index(force: bool = False) -> dict[str, Any]:
    """Return the cached vault index, fetching it when missing or when forced."""
    global _last_index_fetch
    async with _index_lock:
        cached = _index_cache.get("index")
        if cached is not None and not force:
            return cached
        # Stamp before fetching so a failing endpoint is not hammered either
        _last_index_fetch = time.monotonic()
        index = await _fetch_index()
        _index_cache["index"] = index
        return index


def _normalize_path(path: str) -> str:
    """Reduce a URL or path to a bare permalink: no host, no slashes, decoded."""
    p = path.strip()
    if "://" in p:
        p = urlsplit(p).path
    return unquote(p).strip("/")


def _permalink_of(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    frontmatter = entry.get("frontmatter")
    if not isinstance(frontmatter, dict):
        return None
    permalink = frontmatter.get("permalink")
    return permalink.strip("/") if isinstance(permalink, str) else None


def _lookup_path(index: dict[str, Any], path: str) -> str | None:
    """Find the vault path for a permalink, falling back to case-insensitive and vault paths."""
    wanted = _normalize_path(path)
    folded: dict[str, str] = {}
    for vault_path, entry in index.items():
        if not vault_path.endswith(".md"):
            continue
        permalink = _permalink_of(entry)
        if permalink is None:
            continue
        if permalink == wanted:
            return str(vault_path)
        folded.setdefault(permalink.casefold(), str(vault_path))
    if wanted.casefold() in folded:
        return folded[wanted.casefold()]
    # Notes without a permalink are addressed by their vault path
    for candidate in (wanted, f"{wanted}.md"):
        if candidate.endswith(".md") and candidate in index:
            return candidate
    return None


async def _resolve_page(path: str) -> str:
    """Resolve a path to a vault path, refreshing the index once on a miss (max once a minute)."""
    index = await _load_index()
    vault_path = _lookup_path(index, path)
    if vault_path is None and time.monotonic() - _last_index_fetch >= INDEX_REFRESH_INTERVAL:
        vault_path = _lookup_path(await _load_index(force=True), path)
    if vault_path is None:
        raise PageNotFoundError(f"Page not found: {path}")
    return vault_path


def _strip_frontmatter(markdown: str) -> str:
    """Remove a leading YAML frontmatter block, leaving the markdown body."""
    match = _FRONTMATTER_RE.match(markdown)
    if match is None:
        return markdown
    return markdown[match.end() :].lstrip("\r\n")


def _stringify_frontmatter(frontmatter: dict[str, Any]) -> dict[str, str]:
    """Flatten index frontmatter to strings: lists joined with ', ', nulls skipped."""
    result: dict[str, str] = {}
    for key, value in frontmatter.items():
        if value is None:
            continue
        if isinstance(value, list):
            result[str(key)] = ", ".join(str(v) for v in value if v is not None)
        else:
            result[str(key)] = str(value)
    return result


def _raw_url(vault_path: str) -> str:
    encoded = "/".join(quote(segment, safe="") for segment in vault_path.split("/"))
    return f"{ACCESS_URL}/{encoded}"


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
        with contextlib.suppress(Exception):
            await page.wait_for_selector(".metadata-container", timeout=3000)
        html = await page.content()
    finally:
        await page.close()

    async with _cache_lock:
        _page_cache[path] = html
    return html


async def get_page_text(path: str) -> str:
    """Return the markdown body of a page, raising PageNotFoundError for unknown paths."""
    try:
        vault_path = await _resolve_page(path)
        markdown = await _http_get_text(_raw_url(vault_path))
    except PageNotFoundError:
        raise
    except (httpx.HTTPError, ValueError):
        # Index or raw fetch unavailable: render the page in a browser instead
        return await _get_rendered_text(path)
    return _strip_frontmatter(markdown)


async def _get_rendered_text(path: str) -> str:
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


def _permalinks_from_index(index: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for vault_path, entry in index.items():
        permalink = _permalink_of(entry) if vault_path.endswith(".md") else None
        if permalink is None:
            continue
        page = "/" + permalink
        if page not in seen:
            seen.add(page)
            result.append(page)
    return result


async def list_all_pages() -> list[str]:
    async with _pages_cache_lock:
        cached = _pages_cache.get("pages")
        if cached is not None:
            return cached

    # Prefer permalinks from the Obsidian Publish index (includes fresh notes)
    try:
        pages = _permalinks_from_index(await _load_index())
        if pages:
            async with _pages_cache_lock:
                _pages_cache["pages"] = pages
            return pages
    except (httpx.HTTPError, ValueError):
        pass

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


async def search_pages(query: str, offset: int = 0, page_size: int = 10) -> dict[str, Any]:
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


def _extract_property_value(val_el: Any) -> str:
    """Extract text from a metadata property value element.

    Handles multi-select pills (e.g. tags rendered as a list) by joining
    them with ', '. Falls back to plain text for scalar values.
    """
    pills = val_el.select(".multi-select-pill-content")
    if pills:
        return ", ".join(p.get_text(strip=True) for p in pills)
    return str(val_el.get_text(strip=True))


async def get_page_frontmatter(path: str) -> dict[str, str]:
    try:
        vault_path = await _resolve_page(path)
        entry = (await _load_index()).get(vault_path)
        if isinstance(entry, dict) and isinstance(entry.get("frontmatter"), dict):
            return _stringify_frontmatter(entry["frontmatter"])
    except (PageNotFoundError, httpx.HTTPError, ValueError):
        pass
    return await _get_rendered_frontmatter(path)


async def _get_rendered_frontmatter(path: str) -> dict[str, str]:
    html = await _get_page_html(path)
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, str] = {}

    # Obsidian Publish (v1.4+): .metadata-property elements
    for prop in soup.select(".metadata-property"):
        key_el = prop.select_one(".metadata-property-name")
        val_el = prop.select_one(".metadata-property-value")
        if key_el and val_el:
            result[key_el.get_text(strip=True)] = _extract_property_value(val_el)

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
            result[key_el.get_text(strip=True)] = _extract_property_value(val_el)
    return result
