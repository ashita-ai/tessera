"""Tessera SDK clients - sync and async."""

from __future__ import annotations

from typing import Any

from tessera_sdk.http import AsyncHttpClient, HttpClient
from tessera_sdk.resources import (
    AssetsResource,
    AsyncAssetsResource,
    AsyncContractsResource,
    AsyncProposalsResource,
    AsyncRegistrationsResource,
    AsyncTeamsResource,
    ContractsResource,
    ProposalsResource,
    RegistrationsResource,
    TeamsResource,
)


class TesseraClient:
    """Synchronous client for Tessera API.

    Example:
        >>> from tessera_sdk import TesseraClient
        >>> client = TesseraClient(base_url="http://localhost:8000")
        >>>
        >>> # Create a team
        >>> team = client.teams.create(name="data-platform")
        >>>
        >>> # Create an asset
        >>> asset = client.assets.create(
        ...     fqn="warehouse.analytics.dim_customers",
        ...     owner_team_id=team.id
        ... )
        >>>
        >>> # Publish a contract
        >>> result = client.assets.publish_contract(
        ...     asset_id=asset.id,
        ...     schema={"type": "object", "properties": {"id": {"type": "integer"}}},
        ...     version="1.0.0"
        ... )
        >>>
        >>> # Check impact of changes
        >>> impact = client.assets.check_impact(
        ...     asset_id=asset.id,
        ...     proposed_schema={"type": "object", "properties": {"id": {"type": "string"}}}
        ... )
        >>> if not impact.safe_to_publish:
        ...     print(f"Breaking changes: {impact.breaking_changes}")
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize the Tessera client.

        Args:
            base_url: Base URL for the Tessera API. Defaults to TESSERA_URL
                     environment variable or http://localhost:8000.
            timeout: Request timeout in seconds.
            headers: Additional headers to include in requests.
        """
        self._http = HttpClient(base_url=base_url, timeout=timeout, headers=headers)

        # Initialize resources
        self.teams = TeamsResource(self._http)
        self.assets = AssetsResource(self._http)
        self.contracts = ContractsResource(self._http)
        self.registrations = RegistrationsResource(self._http)
        self.proposals = ProposalsResource(self._http)

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    def __enter__(self) -> TesseraClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def health(self) -> dict[str, str]:
        """Check if the API is healthy."""
        return self._http.get("/health")

    def health_ready(self) -> dict[str, Any]:
        """Check if the API is ready (including database)."""
        return self._http.get("/health/ready")


class AsyncTesseraClient:
    """Asynchronous client for Tessera API.

    Example:
        >>> import asyncio
        >>> from tessera_sdk import AsyncTesseraClient
        >>>
        >>> async def main():
        ...     async with AsyncTesseraClient() as client:
        ...         team = await client.teams.create(name="data-platform")
        ...         asset = await client.assets.create(
        ...             fqn="warehouse.analytics.dim_customers",
        ...             owner_team_id=team.id
        ...         )
        ...         print(f"Created asset: {asset.fqn}")
        >>>
        >>> asyncio.run(main())
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize the async Tessera client.

        Args:
            base_url: Base URL for the Tessera API. Defaults to TESSERA_URL
                     environment variable or http://localhost:8000.
            timeout: Request timeout in seconds.
            headers: Additional headers to include in requests.
        """
        self._http = AsyncHttpClient(base_url=base_url, timeout=timeout, headers=headers)

        # Initialize resources
        self.teams = AsyncTeamsResource(self._http)
        self.assets = AsyncAssetsResource(self._http)
        self.contracts = AsyncContractsResource(self._http)
        self.registrations = AsyncRegistrationsResource(self._http)
        self.proposals = AsyncProposalsResource(self._http)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.close()

    async def __aenter__(self) -> AsyncTesseraClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def health(self) -> dict[str, str]:
        """Check if the API is healthy."""
        return await self._http.get("/health")

    async def health_ready(self) -> dict[str, Any]:
        """Check if the API is ready (including database)."""
        return await self._http.get("/health/ready")
