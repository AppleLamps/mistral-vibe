from __future__ import annotations

"""Tests for the web server security and functionality."""

import json
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from vibe.web.server import (
    MAX_ATTACHMENT_SIZE,
    MAX_ATTACHMENTS,
    MAX_MESSAGE_LENGTH,
    RateLimiter,
    _sanitize_error_message,
    _verify_api_key,
    create_app,
)


class TestRateLimiter:
    """Tests for the rate limiter."""

    def test_allows_requests_under_limit(self) -> None:
        """Requests under the limit should be allowed."""
        limiter = RateLimiter(requests_per_minute=10)
        for _ in range(10):
            assert limiter.is_allowed("127.0.0.1") is True

    def test_blocks_requests_over_limit(self) -> None:
        """Requests over the limit should be blocked."""
        limiter = RateLimiter(requests_per_minute=5)
        for _ in range(5):
            assert limiter.is_allowed("127.0.0.1") is True
        assert limiter.is_allowed("127.0.0.1") is False

    def test_separate_limits_per_client(self) -> None:
        """Each client should have separate rate limits."""
        limiter = RateLimiter(requests_per_minute=3)
        for _ in range(3):
            assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is False
        # Different client should still be allowed
        assert limiter.is_allowed("192.168.1.2") is True


class TestErrorSanitization:
    """Tests for error message sanitization."""

    def test_sanitizes_validation_error(self) -> None:
        """ValidationError should return safe message."""
        error = type("ValidationError", (Exception,), {})()
        assert _sanitize_error_message(error) == "Invalid input data"

    def test_sanitizes_json_decode_error(self) -> None:
        """JSONDecodeError should return safe message."""
        error = json.JSONDecodeError("test", "doc", 0)
        assert _sanitize_error_message(error) == "Invalid JSON format"

    def test_sanitizes_unknown_error(self) -> None:
        """Unknown errors should return generic message."""
        error = RuntimeError("sensitive internal details")
        assert _sanitize_error_message(error) == "An internal error occurred"

    def test_does_not_leak_sensitive_info(self) -> None:
        """Error messages should not contain sensitive information."""
        error = FileNotFoundError("/etc/passwd")
        result = _sanitize_error_message(error)
        assert "/etc/passwd" not in result
        assert "An internal error occurred" == result


class TestAPIKeyVerification:
    """Tests for API key verification."""

    def test_allows_when_no_key_configured(self) -> None:
        """Should allow access when no API key is configured."""
        with patch("vibe.web.server._api_key", None):
            assert _verify_api_key(None) is True
            assert _verify_api_key("any-key") is True

    def test_rejects_when_key_missing(self) -> None:
        """Should reject when key is configured but not provided."""
        with patch("vibe.web.server._api_key", "secret-key"):
            assert _verify_api_key(None) is False

    def test_rejects_invalid_key(self) -> None:
        """Should reject invalid API keys."""
        with patch("vibe.web.server._api_key", "secret-key"):
            assert _verify_api_key("wrong-key") is False

    def test_accepts_valid_key(self) -> None:
        """Should accept valid API key."""
        with patch("vibe.web.server._api_key", "secret-key"):
            assert _verify_api_key("secret-key") is True


class TestCORSConfiguration:
    """Tests for CORS configuration."""

    @pytest.fixture
    def app(self) -> Any:
        """Create test app with mocked dependencies."""
        with patch("vibe.web.server.get_session_manager"):
            return create_app()

    def test_cors_restricts_origins(self, app: Any) -> None:
        """CORS should restrict to localhost by default."""
        client = TestClient(app)
        response = client.options(
            "/api/sessions", headers={"Origin": "https://evil.com"}
        )
        # Should not have the malicious origin in response
        assert response.headers.get("access-control-allow-origin") != "https://evil.com"

    def test_cors_allows_localhost(self, app: Any) -> None:
        """CORS should allow localhost origins."""
        client = TestClient(app)
        response = client.options(
            "/api/sessions", headers={"Origin": "http://localhost:8080"}
        )
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:8080"
        )


class TestSecurityHeaders:
    """Tests for security headers."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create test client with mocked dependencies."""
        with patch("vibe.web.server.get_session_manager"):
            app = create_app()
            return TestClient(app)

    def test_x_content_type_options(self, client: TestClient) -> None:
        """Should set X-Content-Type-Options header."""
        response = client.get("/")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self, client: TestClient) -> None:
        """Should set X-Frame-Options header."""
        response = client.get("/")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_x_xss_protection(self, client: TestClient) -> None:
        """Should set X-XSS-Protection header."""
        response = client.get("/")
        assert response.headers.get("x-xss-protection") == "1; mode=block"

    def test_referrer_policy(self, client: TestClient) -> None:
        """Should set Referrer-Policy header."""
        response = client.get("/")
        assert (
            response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        )

    def test_content_security_policy(self, client: TestClient) -> None:
        """Should set Content-Security-Policy header."""
        response = client.get("/")
        csp = response.headers.get("content-security-policy")
        assert csp is not None
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp


class TestAPIKeyAuthentication:
    """Tests for API key authentication on endpoints."""

    @pytest.fixture
    def protected_client(self) -> TestClient:
        """Create test client with API key protection."""
        with patch("vibe.web.server.get_session_manager"):
            app = create_app(api_key="test-secret-key")
            return TestClient(app)

    def test_api_requires_key(self, protected_client: TestClient) -> None:
        """API endpoints should require API key when configured."""
        response = protected_client.get("/api/sessions")
        assert response.status_code == 401
        assert "Invalid or missing API key" in response.json()["error"]

    def test_api_accepts_valid_key(self, protected_client: TestClient) -> None:
        """API endpoints should accept valid API key."""
        with patch("vibe.web.server.get_session_manager") as mock_manager:
            mock_manager.return_value.list_sessions = AsyncMock(return_value=[])
            response = protected_client.get(
                "/api/sessions", headers={"X-API-Key": "test-secret-key"}
            )
            assert response.status_code == 200

    def test_api_rejects_invalid_key(self, protected_client: TestClient) -> None:
        """API endpoints should reject invalid API key."""
        response = protected_client.get(
            "/api/sessions", headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code == 401

    def test_static_files_dont_require_key(self, protected_client: TestClient) -> None:
        """Static files should not require API key."""
        # Index page should be accessible without API key
        response = protected_client.get("/")
        # Status may vary depending on static file existence, but not 401
        assert response.status_code != 401


class TestRateLimiting:
    """Tests for rate limiting on endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create test client."""
        with patch("vibe.web.server.get_session_manager") as mock_manager:
            mock_manager.return_value.list_sessions = AsyncMock(return_value=[])
            app = create_app()
            return TestClient(app)

    def test_rate_limit_returns_429(self, client: TestClient) -> None:
        """Should return 429 when rate limit exceeded."""
        # Make many requests quickly - rate limit is 120/min
        with patch("vibe.web.server._rate_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = False
            response = client.get("/api/sessions")
            assert response.status_code == 429
            assert "Too many requests" in response.json()["error"]


class TestInputValidation:
    """Tests for input validation constants and behavior."""

    def test_max_message_length_defined(self) -> None:
        """MAX_MESSAGE_LENGTH should be defined and reasonable."""
        assert MAX_MESSAGE_LENGTH == 100_000  # 100KB

    def test_max_attachment_size_defined(self) -> None:
        """MAX_ATTACHMENT_SIZE should be defined and reasonable."""
        assert MAX_ATTACHMENT_SIZE == 10 * 1024 * 1024  # 10MB

    def test_max_attachments_defined(self) -> None:
        """MAX_ATTACHMENTS should be defined and reasonable."""
        assert MAX_ATTACHMENTS == 10


class TestCreateApp:
    """Tests for the create_app function."""

    def test_creates_app_with_defaults(self) -> None:
        """Should create app with default settings."""
        with patch("vibe.web.server.get_session_manager"):
            app = create_app()
            assert app.title == "Mistral Vibe Web"

    def test_creates_app_with_api_key(self) -> None:
        """Should create app with API key."""
        with patch("vibe.web.server.get_session_manager"):
            app = create_app(api_key="secret")
            assert app is not None

    def test_creates_app_with_custom_origins(self) -> None:
        """Should create app with custom CORS origins."""
        with patch("vibe.web.server.get_session_manager"):
            origins = ["https://myapp.example.com"]
            app = create_app(allowed_origins=origins)
            assert app is not None
