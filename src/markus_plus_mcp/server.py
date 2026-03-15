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
async def search(query: str) -> list[dict[str, Any]]:
    """Search across all pages for a query, returns matches with excerpts"""
    return await search_pages(query)


@mcp.tool()
async def get_frontmatter(path: str) -> dict[str, str]:
    """Get metadata (title, tags, date) from a page"""
    return await get_page_frontmatter(path)


app = mcp.http_app()
