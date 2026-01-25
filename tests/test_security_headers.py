"""Tests for security headers middleware."""

import pytest
from httpx import AsyncClient


class TestSecurityHeaders:
    """Tests for SecurityHeadersMiddleware."""

    @pytest.mark.asyncio
    async def test_api_endpoint_has_security_headers(self, client: AsyncClient) -> None:
        """API endpoints should return security headers."""
        resp = await client.get("/health/live")
        assert resp.status_code == 200

        # Check required security headers
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "geolocation=()" in resp.headers.get("Permissions-Policy", "")

        # API endpoints should have strict CSP
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_api_v1_has_security_headers(self, client: AsyncClient) -> None:
        """API v1 endpoints should return security headers."""
        resp = await client.get("/api/v1/teams")
        assert resp.status_code == 200

        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    @pytest.mark.asyncio
    async def test_request_id_header_preserved(self, client: AsyncClient) -> None:
        """Custom X-Request-ID should be preserved in response."""
        custom_id = "test-request-12345"
        resp = await client.get("/health/live", headers={"X-Request-ID": custom_id})
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == custom_id

    @pytest.mark.asyncio
    async def test_request_id_generated_when_missing(self, client: AsyncClient) -> None:
        """X-Request-ID should be generated if not provided."""
        resp = await client.get("/health/live")
        assert resp.status_code == 200
        request_id = resp.headers.get("X-Request-ID")
        assert request_id is not None
        # Should be a valid UUID format (36 chars with hyphens)
        assert len(request_id) == 36

    @pytest.mark.asyncio
    async def test_no_hsts_in_development(self, client: AsyncClient) -> None:
        """HSTS header should not be present in development environment."""
        resp = await client.get("/health/live")
        assert resp.status_code == 200
        # In test/development, HSTS should not be set
        # (only added when environment == "production")
        assert "Strict-Transport-Security" not in resp.headers
