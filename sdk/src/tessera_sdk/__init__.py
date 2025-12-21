"""Tessera SDK - Python client for Tessera data contract coordination.

Example usage:

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

For async usage:

    >>> import asyncio
    >>> from tessera_sdk import AsyncTesseraClient
    >>>
    >>> async def main():
    ...     async with AsyncTesseraClient() as client:
    ...         team = await client.teams.create(name="data-platform")
    ...         print(f"Created team: {team.name}")
    >>>
    >>> asyncio.run(main())
"""

from tessera_sdk.client import AsyncTesseraClient, TesseraClient
from tessera_sdk.http import (
    ConflictError,
    NotFoundError,
    ServerError,
    TesseraError,
    ValidationError,
)
from tessera_sdk.models import (
    Acknowledgment,
    AcknowledgmentCreate,
    AcknowledgmentResponseType,
    Asset,
    AssetCreate,
    AssetUpdate,
    BreakingChange,
    ChangeType,
    CompatibilityMode,
    Contract,
    ContractCreate,
    ContractDiff,
    ContractStatus,
    Dependency,
    DependencyCreate,
    DependencyType,
    Guarantees,
    ImpactAnalysis,
    LineageResponse,
    Proposal,
    ProposalCreate,
    ProposalStatus,
    ProposalStatusResponse,
    PublishResult,
    Registration,
    RegistrationCreate,
    RegistrationStatus,
    RegistrationUpdate,
    Team,
    TeamCreate,
    TeamUpdate,
)

__version__ = "0.1.0"

__all__ = [
    # Clients
    "TesseraClient",
    "AsyncTesseraClient",
    # Exceptions
    "TesseraError",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "ServerError",
    # Enums
    "CompatibilityMode",
    "ContractStatus",
    "RegistrationStatus",
    "ChangeType",
    "ProposalStatus",
    "AcknowledgmentResponseType",
    "DependencyType",
    # Models
    "Team",
    "TeamCreate",
    "TeamUpdate",
    "Asset",
    "AssetCreate",
    "AssetUpdate",
    "Guarantees",
    "Contract",
    "ContractCreate",
    "ContractDiff",
    "Registration",
    "RegistrationCreate",
    "RegistrationUpdate",
    "BreakingChange",
    "Proposal",
    "ProposalCreate",
    "ProposalStatusResponse",
    "Acknowledgment",
    "AcknowledgmentCreate",
    "Dependency",
    "DependencyCreate",
    "ImpactAnalysis",
    "LineageResponse",
    "PublishResult",
]
