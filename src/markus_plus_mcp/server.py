from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .scraper import get_page_frontmatter, get_page_text, list_all_pages, search_pages

mcp = FastMCP("markus-plus")


@mcp.tool()
async def list_pages() -> list[str]:
    """List all published pages on markus.plus"""
    return await list_all_pages()


@mcp.tool()
async def get_page(path: str) -> str:
    """Get plain text content of a page, e.g. /om"""
    return await get_page_text(path)


@mcp.tool()
async def search(query: str, offset: int = 0, page_size: int = 10) -> dict[str, Any]:
    """Search across all pages for a query, returns matches with excerpts.
    Use offset and page_size to paginate through results (default: 10 pages per call).
    If next_offset is present in the response, pass it as offset to get the next batch."""
    return await search_pages(query, offset=offset, page_size=page_size)


@mcp.tool()
async def get_frontmatter(path: str) -> dict[str, str]:
    """Get metadata (title, tags, date) from a page"""
    return await get_page_frontmatter(path)


app = mcp.http_app()
