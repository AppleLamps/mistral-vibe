from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchArgs(BaseModel):
    query: str = Field(description="The search query.")
    max_results: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Maximum number of results to return.",
    )


class WebSearchResult(BaseModel):
    query: str
    results: list[SearchResult]
    total_found: int


class WebSearchConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    timeout: float = Field(default=30.0, description="Search timeout in seconds.")


class WebSearchState(BaseToolState):
    recent_queries: list[str] = Field(default_factory=list)


def _parse_ddg_html(html: str, max_results: int) -> list[SearchResult]:
    """Parse DuckDuckGo HTML results page."""
    import re

    results: list[SearchResult] = []

    # Find result blocks - DDG uses class="result" or similar
    # This is a simplified parser that works with DDG's HTML structure
    result_pattern = re.compile(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>.*?'
        r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([^<]*(?:<[^>]+>[^<]*)*)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    # Alternative pattern for different DDG layouts
    alt_pattern = re.compile(
        r'<a[^>]*href="(https?://[^"]+)"[^>]*>.*?<h2[^>]*>([^<]+)</h2>.*?'
        r'<[^>]*class="[^"]*snippet[^"]*"[^>]*>([^<]+)',
        re.DOTALL | re.IGNORECASE,
    )

    # Try primary pattern
    for match in result_pattern.finditer(html):
        if len(results) >= max_results:
            break
        url, title, snippet = match.groups()
        # Clean snippet of HTML tags
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        if url and title:
            results.append(
                SearchResult(
                    title=title.strip(),
                    url=url,
                    snippet=snippet[:300],
                )
            )

    # If no results, try alternative pattern
    if not results:
        for match in alt_pattern.finditer(html):
            if len(results) >= max_results:
                break
            url, title, snippet = match.groups()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            if url and title:
                results.append(
                    SearchResult(
                        title=title.strip(),
                        url=url,
                        snippet=snippet[:300],
                    )
                )

    # Fallback: extract any links with reasonable content
    if not results:
        link_pattern = re.compile(
            r'<a[^>]*href="(https?://(?!duckduckgo)[^"]+)"[^>]*>([^<]{10,})</a>',
            re.IGNORECASE,
        )
        seen_urls: set[str] = set()
        for match in link_pattern.finditer(html):
            if len(results) >= max_results:
                break
            url, title = match.groups()
            if url not in seen_urls and not url.startswith("https://duckduckgo"):
                seen_urls.add(url)
                results.append(
                    SearchResult(
                        title=title.strip(),
                        url=url,
                        snippet="",
                    )
                )

    return results


class WebSearch(
    BaseTool[WebSearchArgs, WebSearchResult, WebSearchConfig, WebSearchState],
    ToolUIData[WebSearchArgs, WebSearchResult],
):
    description: ClassVar[str] = (
        "Search the web using DuckDuckGo. Returns a list of results with titles, "
        "URLs, and snippets. Useful for finding documentation, solutions, and "
        "current information."
    )

    @final
    async def run(self, args: WebSearchArgs) -> WebSearchResult:
        if not args.query.strip():
            raise ToolError("Search query cannot be empty")

        # Use DuckDuckGo HTML search (no API key required)
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(args.query)}"

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.get(
                    search_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                )

            if response.status_code != 200:
                raise ToolError(f"Search failed with status {response.status_code}")

            results = _parse_ddg_html(response.text, args.max_results)

            # Update state
            self.state.recent_queries.append(args.query)
            if len(self.state.recent_queries) > 10:
                self.state.recent_queries.pop(0)

            return WebSearchResult(
                query=args.query,
                results=results,
                total_found=len(results),
            )

        except httpx.TimeoutException:
            raise ToolError(f"Search timed out after {self.config.timeout}s")
        except httpx.RequestError as e:
            raise ToolError(f"Search request failed: {e}")

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, WebSearchArgs):
            return ToolCallDisplay(summary="web_search")

        query = event.args.query
        if len(query) > 50:
            query = query[:47] + "..."
        return ToolCallDisplay(summary=f"web_search: {query}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, WebSearchResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        message = f"Found {result.total_found} result{'s' if result.total_found != 1 else ''}"

        return ToolResultDisplay(
            success=True,
            message=message,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Searching the web"
