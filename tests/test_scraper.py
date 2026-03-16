from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import markus_plus_mcp.scraper as scraper

SAMPLE_PAGE_HTML = """
<html>
<body>
  <div class="markdown-preview-view">
    <p>Hello from markus.plus</p>
    <p>This is some content about Python and testing.</p>
  </div>
</body>
</html>
"""

NAV_HTML = """
<html>
<body>
  <nav>
    <a href="/om">Om</a>
    <a href="/prosjekt">Prosjekt</a>
    <a href="https://external.com">External</a>
  </nav>
</body>
</html>
"""

FRONTMATTER_HTML = """
<html>
<body>
  <div class="metadata-container">
    <table>
      <tr><th>title</th><td>My Page</td></tr>
      <tr><th>date</th><td>2024-01-01</td></tr>
      <tr><th>tags</th><td>python, mcp</td></tr>
    </table>
  </div>
</body>
</html>
"""

NO_CONTENT_HTML = "<html><body><p>No content div here</p></body></html>"

OBSIDIAN_FRONTMATTER_HTML = """
<html>
<body>
  <div class="metadata-container mod-trustall">
    <div class="metadata-content">
      <div class="metadata-properties">
        <div class="metadata-property" data-property-key="permalink">
          <div class="metadata-property-key">
            <span class="metadata-property-name">permalink</span>
          </div>
          <div class="metadata-property-value">
            <div class="metadata-input-longtext mod-truncate">/</div>
          </div>
        </div>
        <div class="metadata-property" data-property-key="description">
          <div class="metadata-property-key">
            <span class="metadata-property-name">description</span>
          </div>
          <div class="metadata-property-value">
            <div class="metadata-input-longtext mod-truncate">Om meg og tankane mine</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""

NAV_FILE_TREE_HTML = """
<html>
<body>
  <div class="nav-folder-children">
    <div class="nav-file">
      <div class="nav-file-title" data-path="om.md">Om</div>
    </div>
    <div class="nav-file">
      <div class="nav-file-title" data-path="prosjekt.md">Prosjekt</div>
    </div>
    <div class="nav-folder">
      <div class="nav-file-title" data-path="reiser/tog.md">Tog</div>
    </div>
  </div>
</body>
</html>
"""

BROADER_CONTENT_HTML = """
<html>
<body>
  <div class="markdown-preview-view"></div>
  <main>
    <p>Fallback content here</p>
  </main>
</body>
</html>
"""

SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://markus.plus/om</loc></url>
  <url><loc>https://markus.plus/prosjekt</loc></url>
</urlset>"""

SITEMAP_XML_NO_NS = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset>
  <url><loc>https://markus.plus/reisar</loc></url>
  <url><loc>https://markus.plus/tankekart</loc></url>
</urlset>"""


@pytest.fixture(autouse=True)
def clear_page_cache() -> None:
    scraper._page_cache.clear()
    scraper._pages_cache.clear()


@pytest.mark.asyncio
async def test_get_page_text_returns_text() -> None:
    with patch.object(scraper, "_get_page_html", new=AsyncMock(return_value=SAMPLE_PAGE_HTML)):
        result = await scraper.get_page_text("/om")
    assert "Hello from markus.plus" in result
    assert "Python and testing" in result


@pytest.mark.asyncio
async def test_get_page_text_empty_when_no_selector() -> None:
    with patch.object(scraper, "_get_page_html", new=AsyncMock(return_value=NO_CONTENT_HTML)):
        result = await scraper.get_page_text("/missing")
    assert result == ""


def test_fetch_sitemap_parses_xml() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = SITEMAP_XML
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = scraper._fetch_sitemap()

    assert "/om" in result
    assert "/prosjekt" in result


def test_fetch_sitemap_parses_xml_no_namespace() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = SITEMAP_XML_NO_NS
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = scraper._fetch_sitemap()

    assert "/reisar" in result
    assert "/tankekart" in result


def test_fetch_sitemap_excludes_external() -> None:
    xml_with_external = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://markus.plus/om</loc></url>
  <url><loc>https://other.com/page</loc></url>
</urlset>"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = xml_with_external
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = scraper._fetch_sitemap()

    assert "/om" in result
    assert "https://other.com/page" not in result


def test_fetch_sitemap_excludes_publish_entries() -> None:
    xml_with_publish = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://markus.plus/_publish/Hovud</loc></url>
  <url><loc>https://markus.plus/meg</loc></url>
</urlset>"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = xml_with_publish
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = scraper._fetch_sitemap()

    assert "/meg" in result
    assert "/_publish/Hovud" not in result


def test_fetch_sitemap_normalizes_bare_domain() -> None:
    xml_bare = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://markus.plus</loc></url>
  <url><loc>https://markus.plus/om</loc></url>
</urlset>"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = xml_bare
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = scraper._fetch_sitemap()

    assert "/" in result
    assert "/om" in result
    assert "" not in result


@pytest.mark.asyncio
async def test_list_all_pages_caches_result() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = SITEMAP_XML
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    scraper._pages_cache.clear()
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        await scraper.list_all_pages()
        await scraper.list_all_pages()

    # urlopen called only once; second call served from cache
    assert mock_urlopen.call_count == 1


@pytest.mark.asyncio
async def test_list_all_pages_uses_sitemap() -> None:
    mock_resp = MagicMock()
    mock_resp.read.return_value = SITEMAP_XML
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = await scraper.list_all_pages()

    assert "/om" in result
    assert "/prosjekt" in result


@pytest.mark.asyncio
async def test_list_all_pages_falls_back_to_nav() -> None:
    with (
        patch("urllib.request.urlopen", side_effect=OSError("network error")),
        patch.object(scraper, "_fetch_homepage_for_nav", new=AsyncMock(return_value=NAV_HTML)),
    ):
        result = await scraper.list_all_pages()

    assert "/om" in result
    assert "/prosjekt" in result
    assert "https://external.com" not in result


@pytest.mark.asyncio
async def test_search_pages_finds_match() -> None:
    async def fake_list() -> list[str]:
        return ["/om", "/prosjekt"]

    async def fake_text(path: str) -> str:
        if path == "/om":
            return "This page is about Python programming and testing frameworks."
        return "Unrelated content about cooking."

    with (
        patch.object(scraper, "list_all_pages", new=AsyncMock(side_effect=fake_list)),
        patch.object(scraper, "get_page_text", new=AsyncMock(side_effect=fake_text)),
    ):
        results = await scraper.search_pages("Python")

    assert len(results) == 1
    assert results[0]["path"] == "/om"
    assert "Python" in results[0]["excerpt"]


@pytest.mark.asyncio
async def test_search_pages_no_match() -> None:
    async def fake_list() -> list[str]:
        return ["/om"]

    async def fake_text(path: str) -> str:
        return "Nothing relevant here."

    with (
        patch.object(scraper, "list_all_pages", new=AsyncMock(side_effect=fake_list)),
        patch.object(scraper, "get_page_text", new=AsyncMock(side_effect=fake_text)),
    ):
        results = await scraper.search_pages("nonexistent")

    assert results == []


@pytest.mark.asyncio
async def test_get_frontmatter_returns_dict() -> None:
    with patch.object(scraper, "_get_page_html", new=AsyncMock(return_value=FRONTMATTER_HTML)):
        result = await scraper.get_page_frontmatter("/om")

    assert result.get("title") == "My Page"
    assert result.get("date") == "2024-01-01"
    assert result.get("tags") == "python, mcp"


@pytest.mark.asyncio
async def test_get_frontmatter_empty_when_no_table() -> None:
    with patch.object(scraper, "_get_page_html", new=AsyncMock(return_value=NO_CONTENT_HTML)):
        result = await scraper.get_page_frontmatter("/om")

    assert result == {}


@pytest.mark.asyncio
async def test_get_frontmatter_obsidian_publish_format() -> None:
    with patch.object(scraper, "_get_page_html", new=AsyncMock(return_value=OBSIDIAN_FRONTMATTER_HTML)):
        result = await scraper.get_page_frontmatter("/")

    assert result.get("permalink") == "/"
    assert result.get("description") == "Om meg og tankane mine"


@pytest.mark.asyncio
async def test_list_all_pages_falls_back_to_nav_file_title() -> None:
    with (
        patch("urllib.request.urlopen", side_effect=OSError("network error")),
        patch.object(scraper, "_fetch_homepage_for_nav", new=AsyncMock(return_value=NAV_FILE_TREE_HTML)),
    ):
        result = await scraper.list_all_pages()

    assert "/om" in result
    assert "/prosjekt" in result
    assert "/reiser/tog" in result
    assert "https://external.com" not in result


@pytest.mark.asyncio
async def test_get_page_text_falls_back_to_broader_selector() -> None:
    with patch.object(scraper, "_get_page_html", new=AsyncMock(return_value=BROADER_CONTENT_HTML)):
        result = await scraper.get_page_text("/om")

    assert "Fallback content here" in result
