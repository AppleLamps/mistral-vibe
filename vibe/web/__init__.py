from __future__ import annotations

"""Web interface module for Mistral Vibe.

This module provides an optional web UI for interacting with the Vibe agent,
similar to the CLI but accessible via a web browser.

Install dependencies with: pip install mistral-vibe[web]
"""

__all__ = ["run_server"]


def run_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
    api_key: str | None = None,
    allowed_origins: list[str] | None = None,
) -> None:
    """Start the web server.

    Args:
        host: Host to bind to (default: 127.0.0.1)
        port: Port to bind to (default: 8080)
        open_browser: Whether to open the browser automatically
        api_key: Optional API key for authentication. If provided, all API
            requests must include this key in the X-API-Key header.
        allowed_origins: List of allowed CORS origins. If None, defaults to
            localhost only for security.
    """
    try:
        import uvicorn
    except ImportError as e:
        raise ImportError(
            "Web dependencies not installed. Run: pip install mistral-vibe[web]"
        ) from e

    from vibe.web.server import create_app

    app = create_app(api_key=api_key, allowed_origins=allowed_origins)

    if open_browser:
        import threading
        import time
        import webbrowser

        def open_browser_delayed() -> None:
            time.sleep(1.0)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=open_browser_delayed, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
