from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar, final
from urllib.parse import urlparse

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


class WebFetchArgs(BaseModel):
    url: str = Field(description="The URL to fetch content from.")
    extract_text: bool = Field(
        default=True,
        description="If True, extract readable text content. If False, return raw HTML.",
    )
    timeout: float = Field(
        default=30.0,
        description="Request timeout in seconds.",
    )


class WebFetchResult(BaseModel):
    url: str
    final_url: str = Field(description="Final URL after redirects.")
    status_code: int
    content: str
    content_type: str
    was_truncated: bool = False


class WebFetchConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    max_content_bytes: int = Field(
        default=100_000,
        description="Maximum content size to return.",
    )
    allowed_domains: list[str] = Field(
        default_factory=list,
        description="If set, only allow fetching from these domains.",
    )
    blocked_domains: list[str] = Field(
        default_factory=list,
        description="Block fetching from these domains.",
    )


class WebFetchState(BaseToolState):
    fetched_urls: list[str] = Field(default_factory=list)


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML, removing scripts and styles."""
    import re

    # Remove script and style elements
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<noscript[^>]*>.*?</noscript>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    # Replace block elements with newlines
    html = re.sub(r"<(?:p|div|br|hr|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)

    # Remove remaining tags
    html = re.sub(r"<[^>]+>", " ", html)

    # Decode common HTML entities
    entities = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
        "&apos;": "'",
    }
    for entity, char in entities.items():
        html = html.replace(entity, char)

    # Clean up whitespace
    lines = []
    for line in html.split("\n"):
        line = " ".join(line.split())
        if line:
            lines.append(line)

    return "\n".join(lines)


class WebFetch(
    BaseTool[WebFetchArgs, WebFetchResult, WebFetchConfig, WebFetchState],
    ToolUIData[WebFetchArgs, WebFetchResult],
):
    description: ClassVar[str] = (
        "Fetch content from a URL. Can extract readable text from HTML pages "
        "or return raw content. Useful for reading documentation, API responses, "
        "and web pages."
    )

    @final
    async def run(self, args: WebFetchArgs) -> WebFetchResult:
        # Validate URL
        parsed = urlparse(args.url)
        if not parsed.scheme:
            raise ToolError("URL must include a scheme (http:// or https://)")
        if parsed.scheme not in ("http", "https"):
            raise ToolError(f"Unsupported URL scheme: {parsed.scheme}")

        domain = parsed.netloc.lower()

        # Check domain restrictions
        if self.config.blocked_domains:
            for blocked in self.config.blocked_domains:
                if domain == blocked.lower() or domain.endswith(f".{blocked.lower()}"):
                    raise ToolError(f"Domain '{domain}' is blocked")

        if self.config.allowed_domains:
            allowed = False
            for allow in self.config.allowed_domains:
                if domain == allow.lower() or domain.endswith(f".{allow.lower()}"):
                    allowed = True
                    break
            if not allowed:
                raise ToolError(f"Domain '{domain}' is not in the allowed list")

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=args.timeout,
            ) as client:
                response = await client.get(
                    args.url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; VibeAgent/1.0)",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )

            content_type = response.headers.get("content-type", "")
            content = response.text

            was_truncated = False
            if len(content) > self.config.max_content_bytes:
                content = content[: self.config.max_content_bytes]
                was_truncated = True

            # Extract text if requested and content is HTML
            if args.extract_text and "html" in content_type.lower():
                content = _extract_text_from_html(content)

            # Update state
            self.state.fetched_urls.append(str(response.url))

            return WebFetchResult(
                url=args.url,
                final_url=str(response.url),
                status_code=response.status_code,
                content=content,
                content_type=content_type,
                was_truncated=was_truncated,
            )

        except httpx.TimeoutException:
            raise ToolError(f"Request timed out after {args.timeout}s")
        except httpx.RequestError as e:
            raise ToolError(f"Request failed: {e}")

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, WebFetchArgs):
            return ToolCallDisplay(summary="web_fetch")

        parsed = urlparse(event.args.url)
        domain = parsed.netloc or event.args.url[:50]
        return ToolCallDisplay(summary=f"web_fetch: {domain}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, WebFetchResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        size = len(result.content)
        size_str = f"{size:,}" if size < 10000 else f"{size // 1000}KB"

        message = f"Fetched {size_str} chars (status {result.status_code})"
        if result.was_truncated:
            message += " [truncated]"

        return ToolResultDisplay(
            success=result.status_code < 400,
            message=message,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Fetching URL"
