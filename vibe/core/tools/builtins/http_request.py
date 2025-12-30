from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal, final

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


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class HttpRequestArgs(BaseModel):
    url: str = Field(description="The URL to send the request to.")
    method: HttpMethod = Field(
        default="GET",
        description="HTTP method to use.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers to include in the request.",
    )
    body: str | None = Field(
        default=None,
        description="Request body (for POST, PUT, PATCH).",
    )
    json_body: dict[str, Any] | list[Any] | None = Field(
        default=None,
        description="JSON body (automatically sets Content-Type). Mutually exclusive with body.",
    )
    timeout: float = Field(
        default=30.0,
        description="Request timeout in seconds.",
    )
    follow_redirects: bool = Field(
        default=True,
        description="Whether to follow redirects.",
    )


class HttpRequestResult(BaseModel):
    url: str
    final_url: str
    method: str
    status_code: int
    status_text: str
    headers: dict[str, str]
    body: str
    elapsed_ms: float
    was_truncated: bool = False


class HttpRequestConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    max_response_bytes: int = Field(
        default=100_000,
        description="Maximum response body size.",
    )
    allowed_hosts: list[str] = Field(
        default_factory=list,
        description="If set, only allow requests to these hosts.",
    )
    blocked_hosts: list[str] = Field(
        default_factory=list,
        description="Block requests to these hosts.",
    )


class HttpRequestState(BaseToolState):
    request_count: int = 0


class HttpRequest(
    BaseTool[HttpRequestArgs, HttpRequestResult, HttpRequestConfig, HttpRequestState],
    ToolUIData[HttpRequestArgs, HttpRequestResult],
):
    description: ClassVar[str] = (
        "Make HTTP requests to APIs and web services. Supports all common HTTP methods, "
        "custom headers, and JSON bodies. Useful for testing APIs, fetching data, "
        "and interacting with web services."
    )

    @final
    async def run(self, args: HttpRequestArgs) -> HttpRequestResult:
        from urllib.parse import urlparse

        # Validate URL
        parsed = urlparse(args.url)
        if not parsed.scheme:
            raise ToolError("URL must include a scheme (http:// or https://)")
        if parsed.scheme not in ("http", "https"):
            raise ToolError(f"Unsupported URL scheme: {parsed.scheme}")

        host = parsed.netloc.lower()

        # Check host restrictions
        if self.config.blocked_hosts:
            for blocked in self.config.blocked_hosts:
                if host == blocked.lower() or host.endswith(f".{blocked.lower()}"):
                    raise ToolError(f"Host '{host}' is blocked")

        if self.config.allowed_hosts:
            allowed = False
            for allow in self.config.allowed_hosts:
                if host == allow.lower() or host.endswith(f".{allow.lower()}"):
                    allowed = True
                    break
            if not allowed:
                raise ToolError(f"Host '{host}' is not in the allowed list")

        # Validate body options
        if args.body and args.json_body:
            raise ToolError("Cannot specify both 'body' and 'json_body'")

        try:
            async with httpx.AsyncClient(
                follow_redirects=args.follow_redirects,
                timeout=args.timeout,
            ) as client:
                # Build request kwargs
                kwargs: dict[str, Any] = {
                    "method": args.method,
                    "url": args.url,
                    "headers": args.headers,
                }

                if args.json_body is not None:
                    kwargs["json"] = args.json_body
                elif args.body is not None:
                    kwargs["content"] = args.body

                response = await client.request(**kwargs)

            # Process response
            response_headers = dict(response.headers)
            body = response.text

            was_truncated = False
            if len(body) > self.config.max_response_bytes:
                body = body[: self.config.max_response_bytes]
                was_truncated = True

            # Update state
            self.state.request_count += 1

            # Get status text
            status_text = httpx.codes.get_reason_phrase(response.status_code)

            return HttpRequestResult(
                url=args.url,
                final_url=str(response.url),
                method=args.method,
                status_code=response.status_code,
                status_text=status_text,
                headers=response_headers,
                body=body,
                elapsed_ms=response.elapsed.total_seconds() * 1000,
                was_truncated=was_truncated,
            )

        except httpx.TimeoutException:
            raise ToolError(f"Request timed out after {args.timeout}s")
        except httpx.RequestError as e:
            raise ToolError(f"Request failed: {e}")

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, HttpRequestArgs):
            return ToolCallDisplay(summary="http_request")

        from urllib.parse import urlparse

        parsed = urlparse(event.args.url)
        path = parsed.path or "/"
        if len(path) > 30:
            path = path[:27] + "..."

        return ToolCallDisplay(
            summary=f"{event.args.method} {parsed.netloc}{path}"
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, HttpRequestResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        size = len(result.body)
        size_str = f"{size:,}" if size < 10000 else f"{size // 1000}KB"

        message = f"{result.status_code} {result.status_text} ({size_str}, {result.elapsed_ms:.0f}ms)"
        if result.was_truncated:
            message += " [truncated]"

        return ToolResultDisplay(
            success=result.status_code < 400,
            message=message,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Making HTTP request"
