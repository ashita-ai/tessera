import pytest
from httpx import ASGITransport, AsyncClient

from tessera.main import app


@pytest.mark.asyncio
async def test_cors_preflight():
    """Test CORS preflight with default settings."""
    # Note: testing production environment changes after app initialization
    # is complex with module-level app instance. This test verifies
    # that CORS middleware is active and responding.

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Default allowed origin in settings.py is ["http://localhost:3000"]
        response = await client.options(
            "/api/v1/assets",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

        # Disallowed origin
        response = await client.options(
            "/api/v1/assets",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORSMiddleware doesn't include the header if origin not allowed
        assert "access-control-allow-origin" not in response.headers
