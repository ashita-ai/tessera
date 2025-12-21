"""Resource classes for Tessera SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from tessera_sdk.models import (
    Acknowledgment,
    AcknowledgmentResponseType,
    Asset,
    AssetCreate,
    AssetUpdate,
    CompatibilityMode,
    Contract,
    ContractCreate,
    ContractDiff,
    ContractStatus,
    Dependency,
    DependencyCreate,
    DependencyType,
    ImpactAnalysis,
    LineageResponse,
    Proposal,
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

if TYPE_CHECKING:
    from tessera_sdk.http import AsyncHttpClient, HttpClient


class TeamsResource:
    """Teams API resource (sync)."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._base = "/api/v1/teams"

    def create(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> Team:
        """Create a new team."""
        data = TeamCreate(name=name, metadata=metadata or {})
        response = self._http.post(self._base, json=data.model_dump())
        return Team.model_validate(response)

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Team]:
        """List all teams."""
        response = self._http.get(self._base, params={"limit": limit, "offset": offset})
        return [Team.model_validate(t) for t in response]

    def get(self, team_id: UUID | str) -> Team:
        """Get a team by ID."""
        response = self._http.get(f"{self._base}/{team_id}")
        return Team.model_validate(response)

    def update(
        self,
        team_id: UUID | str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Team:
        """Update a team."""
        data = TeamUpdate(name=name, metadata=metadata)
        response = self._http.patch(
            f"{self._base}/{team_id}",
            json=data.model_dump(exclude_none=True),
        )
        return Team.model_validate(response)


class AsyncTeamsResource:
    """Teams API resource (async)."""

    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http
        self._base = "/api/v1/teams"

    async def create(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> Team:
        """Create a new team."""
        data = TeamCreate(name=name, metadata=metadata or {})
        response = await self._http.post(self._base, json=data.model_dump())
        return Team.model_validate(response)

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Team]:
        """List all teams."""
        response = await self._http.get(self._base, params={"limit": limit, "offset": offset})
        return [Team.model_validate(t) for t in response]

    async def get(self, team_id: UUID | str) -> Team:
        """Get a team by ID."""
        response = await self._http.get(f"{self._base}/{team_id}")
        return Team.model_validate(response)

    async def update(
        self,
        team_id: UUID | str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Team:
        """Update a team."""
        data = TeamUpdate(name=name, metadata=metadata)
        response = await self._http.patch(
            f"{self._base}/{team_id}",
            json=data.model_dump(exclude_none=True),
        )
        return Team.model_validate(response)


class AssetsResource:
    """Assets API resource (sync)."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._base = "/api/v1/assets"

    def create(
        self,
        fqn: str,
        owner_team_id: UUID | str,
        metadata: dict[str, Any] | None = None,
    ) -> Asset:
        """Create a new asset."""
        data = AssetCreate(
            fqn=fqn,
            owner_team_id=UUID(str(owner_team_id)),
            metadata=metadata or {},
        )
        response = self._http.post(self._base, json=data.model_dump(mode="json"))
        return Asset.model_validate(response)

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        owner_team_id: UUID | str | None = None,
    ) -> list[Asset]:
        """List all assets."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if owner_team_id:
            params["owner_team_id"] = str(owner_team_id)
        response = self._http.get(self._base, params=params)
        return [Asset.model_validate(a) for a in response]

    def search(
        self,
        q: str,
        limit: int = 100,
    ) -> list[Asset]:
        """Search assets by FQN pattern."""
        response = self._http.get(f"{self._base}/search", params={"q": q, "limit": limit})
        return [Asset.model_validate(a) for a in response]

    def get(self, asset_id: UUID | str) -> Asset:
        """Get an asset by ID."""
        response = self._http.get(f"{self._base}/{asset_id}")
        return Asset.model_validate(response)

    def update(
        self,
        asset_id: UUID | str,
        fqn: str | None = None,
        owner_team_id: UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Asset:
        """Update an asset."""
        data = AssetUpdate(
            fqn=fqn,
            owner_team_id=UUID(str(owner_team_id)) if owner_team_id else None,
            metadata=metadata,
        )
        response = self._http.patch(
            f"{self._base}/{asset_id}",
            json=data.model_dump(exclude_none=True, mode="json"),
        )
        return Asset.model_validate(response)

    def publish_contract(
        self,
        asset_id: UUID | str,
        schema: dict[str, Any],
        version: str,
        compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD,
        force: bool = False,
        dry_run: bool = False,
        published_by: UUID | str | None = None,
    ) -> PublishResult:
        """Publish a new contract for the asset."""
        data = ContractCreate(
            version=version,
            schema_def=schema,
            compatibility_mode=compatibility_mode,
        )
        params: dict[str, Any] = {}
        if force:
            params["force"] = "true"
        if dry_run:
            params["dry_run"] = "true"
        if published_by:
            params["published_by"] = str(published_by)

        response = self._http.post(
            f"{self._base}/{asset_id}/contracts",
            json=data.model_dump(by_alias=True, mode="json"),
            params=params if params else None,
        )
        return PublishResult.model_validate(response)

    def list_contracts(
        self,
        asset_id: UUID | str,
        status: ContractStatus | None = None,
    ) -> list[Contract]:
        """List contracts for an asset."""
        params: dict[str, Any] = {}
        if status:
            params["status"] = status.value
        response = self._http.get(f"{self._base}/{asset_id}/contracts", params=params or None)
        return [Contract.model_validate(c) for c in response]

    def get_contract_history(
        self,
        asset_id: UUID | str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get contract version history for an asset."""
        response = self._http.get(
            f"{self._base}/{asset_id}/contracts/history",
            params={"limit": limit},
        )
        return response  # type: ignore[return-value]

    def diff_contracts(
        self,
        asset_id: UUID | str,
        from_version: str,
        to_version: str,
    ) -> ContractDiff:
        """Compare two contract versions."""
        response = self._http.get(
            f"{self._base}/{asset_id}/contracts/diff",
            params={"from_version": from_version, "to_version": to_version},
        )
        return ContractDiff.model_validate(response)

    def check_impact(
        self,
        asset_id: UUID | str,
        proposed_schema: dict[str, Any],
    ) -> ImpactAnalysis:
        """Check impact of proposed schema changes."""
        response = self._http.post(
            f"{self._base}/{asset_id}/impact",
            json={"proposed_schema": proposed_schema},
        )
        return ImpactAnalysis.model_validate(response)

    def get_lineage(
        self,
        asset_id: UUID | str,
        depth: int = 3,
    ) -> LineageResponse:
        """Get lineage graph for an asset."""
        response = self._http.get(
            f"{self._base}/{asset_id}/lineage",
            params={"depth": depth},
        )
        return LineageResponse.model_validate(response)

    def add_dependency(
        self,
        asset_id: UUID | str,
        target_asset_id: UUID | str,
        dependency_type: DependencyType,
        metadata: dict[str, Any] | None = None,
    ) -> Dependency:
        """Add a dependency from this asset to another."""
        data = DependencyCreate(
            target_asset_id=UUID(str(target_asset_id)),
            dependency_type=dependency_type,
            metadata=metadata or {},
        )
        response = self._http.post(
            f"{self._base}/{asset_id}/dependencies",
            json=data.model_dump(mode="json"),
        )
        return Dependency.model_validate(response)

    def list_dependencies(
        self,
        asset_id: UUID | str,
    ) -> list[Dependency]:
        """List dependencies for an asset."""
        response = self._http.get(f"{self._base}/{asset_id}/dependencies")
        return [Dependency.model_validate(d) for d in response]

    def remove_dependency(
        self,
        asset_id: UUID | str,
        dependency_id: UUID | str,
    ) -> None:
        """Remove a dependency."""
        self._http.delete(f"{self._base}/{asset_id}/dependencies/{dependency_id}")


class AsyncAssetsResource:
    """Assets API resource (async)."""

    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http
        self._base = "/api/v1/assets"

    async def create(
        self,
        fqn: str,
        owner_team_id: UUID | str,
        metadata: dict[str, Any] | None = None,
    ) -> Asset:
        """Create a new asset."""
        data = AssetCreate(
            fqn=fqn,
            owner_team_id=UUID(str(owner_team_id)),
            metadata=metadata or {},
        )
        response = await self._http.post(self._base, json=data.model_dump(mode="json"))
        return Asset.model_validate(response)

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        owner_team_id: UUID | str | None = None,
    ) -> list[Asset]:
        """List all assets."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if owner_team_id:
            params["owner_team_id"] = str(owner_team_id)
        response = await self._http.get(self._base, params=params)
        return [Asset.model_validate(a) for a in response]

    async def search(
        self,
        q: str,
        limit: int = 100,
    ) -> list[Asset]:
        """Search assets by FQN pattern."""
        response = await self._http.get(f"{self._base}/search", params={"q": q, "limit": limit})
        return [Asset.model_validate(a) for a in response]

    async def get(self, asset_id: UUID | str) -> Asset:
        """Get an asset by ID."""
        response = await self._http.get(f"{self._base}/{asset_id}")
        return Asset.model_validate(response)

    async def update(
        self,
        asset_id: UUID | str,
        fqn: str | None = None,
        owner_team_id: UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Asset:
        """Update an asset."""
        data = AssetUpdate(
            fqn=fqn,
            owner_team_id=UUID(str(owner_team_id)) if owner_team_id else None,
            metadata=metadata,
        )
        response = await self._http.patch(
            f"{self._base}/{asset_id}",
            json=data.model_dump(exclude_none=True, mode="json"),
        )
        return Asset.model_validate(response)

    async def publish_contract(
        self,
        asset_id: UUID | str,
        schema: dict[str, Any],
        version: str,
        compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD,
        force: bool = False,
        dry_run: bool = False,
        published_by: UUID | str | None = None,
    ) -> PublishResult:
        """Publish a new contract for the asset."""
        data = ContractCreate(
            version=version,
            schema_def=schema,
            compatibility_mode=compatibility_mode,
        )
        params: dict[str, Any] = {}
        if force:
            params["force"] = "true"
        if dry_run:
            params["dry_run"] = "true"
        if published_by:
            params["published_by"] = str(published_by)

        response = await self._http.post(
            f"{self._base}/{asset_id}/contracts",
            json=data.model_dump(by_alias=True, mode="json"),
            params=params if params else None,
        )
        return PublishResult.model_validate(response)

    async def list_contracts(
        self,
        asset_id: UUID | str,
        status: ContractStatus | None = None,
    ) -> list[Contract]:
        """List contracts for an asset."""
        params: dict[str, Any] = {}
        if status:
            params["status"] = status.value
        response = await self._http.get(f"{self._base}/{asset_id}/contracts", params=params or None)
        return [Contract.model_validate(c) for c in response]

    async def get_contract_history(
        self,
        asset_id: UUID | str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get contract version history for an asset."""
        response = await self._http.get(
            f"{self._base}/{asset_id}/contracts/history",
            params={"limit": limit},
        )
        return response  # type: ignore[return-value]

    async def diff_contracts(
        self,
        asset_id: UUID | str,
        from_version: str,
        to_version: str,
    ) -> ContractDiff:
        """Compare two contract versions."""
        response = await self._http.get(
            f"{self._base}/{asset_id}/contracts/diff",
            params={"from_version": from_version, "to_version": to_version},
        )
        return ContractDiff.model_validate(response)

    async def check_impact(
        self,
        asset_id: UUID | str,
        proposed_schema: dict[str, Any],
    ) -> ImpactAnalysis:
        """Check impact of proposed schema changes."""
        response = await self._http.post(
            f"{self._base}/{asset_id}/impact",
            json={"proposed_schema": proposed_schema},
        )
        return ImpactAnalysis.model_validate(response)

    async def get_lineage(
        self,
        asset_id: UUID | str,
        depth: int = 3,
    ) -> LineageResponse:
        """Get lineage graph for an asset."""
        response = await self._http.get(
            f"{self._base}/{asset_id}/lineage",
            params={"depth": depth},
        )
        return LineageResponse.model_validate(response)

    async def add_dependency(
        self,
        asset_id: UUID | str,
        target_asset_id: UUID | str,
        dependency_type: DependencyType,
        metadata: dict[str, Any] | None = None,
    ) -> Dependency:
        """Add a dependency from this asset to another."""
        data = DependencyCreate(
            target_asset_id=UUID(str(target_asset_id)),
            dependency_type=dependency_type,
            metadata=metadata or {},
        )
        response = await self._http.post(
            f"{self._base}/{asset_id}/dependencies",
            json=data.model_dump(mode="json"),
        )
        return Dependency.model_validate(response)

    async def list_dependencies(
        self,
        asset_id: UUID | str,
    ) -> list[Dependency]:
        """List dependencies for an asset."""
        response = await self._http.get(f"{self._base}/{asset_id}/dependencies")
        return [Dependency.model_validate(d) for d in response]

    async def remove_dependency(
        self,
        asset_id: UUID | str,
        dependency_id: UUID | str,
    ) -> None:
        """Remove a dependency."""
        await self._http.delete(f"{self._base}/{asset_id}/dependencies/{dependency_id}")


class ContractsResource:
    """Contracts API resource (sync)."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._base = "/api/v1/contracts"

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        asset_id: UUID | str | None = None,
        status: ContractStatus | None = None,
    ) -> list[Contract]:
        """List contracts with optional filters."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if asset_id:
            params["asset_id"] = str(asset_id)
        if status:
            params["status"] = status.value
        response = self._http.get(self._base, params=params)
        return [Contract.model_validate(c) for c in response]

    def get(self, contract_id: UUID | str) -> Contract:
        """Get a contract by ID."""
        response = self._http.get(f"{self._base}/{contract_id}")
        return Contract.model_validate(response)

    def get_registrations(self, contract_id: UUID | str) -> list[Registration]:
        """Get registrations for a contract."""
        response = self._http.get(f"{self._base}/{contract_id}/registrations")
        return [Registration.model_validate(r) for r in response]

    def compare(
        self,
        old_schema: dict[str, Any],
        new_schema: dict[str, Any],
        compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD,
    ) -> dict[str, Any]:
        """Compare two schemas without publishing."""
        response = self._http.post(
            f"{self._base}/compare",
            json={
                "old_schema": old_schema,
                "new_schema": new_schema,
                "compatibility_mode": compatibility_mode.value,
            },
        )
        return response


class AsyncContractsResource:
    """Contracts API resource (async)."""

    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http
        self._base = "/api/v1/contracts"

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        asset_id: UUID | str | None = None,
        status: ContractStatus | None = None,
    ) -> list[Contract]:
        """List contracts with optional filters."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if asset_id:
            params["asset_id"] = str(asset_id)
        if status:
            params["status"] = status.value
        response = await self._http.get(self._base, params=params)
        return [Contract.model_validate(c) for c in response]

    async def get(self, contract_id: UUID | str) -> Contract:
        """Get a contract by ID."""
        response = await self._http.get(f"{self._base}/{contract_id}")
        return Contract.model_validate(response)

    async def get_registrations(self, contract_id: UUID | str) -> list[Registration]:
        """Get registrations for a contract."""
        response = await self._http.get(f"{self._base}/{contract_id}/registrations")
        return [Registration.model_validate(r) for r in response]

    async def compare(
        self,
        old_schema: dict[str, Any],
        new_schema: dict[str, Any],
        compatibility_mode: CompatibilityMode = CompatibilityMode.BACKWARD,
    ) -> dict[str, Any]:
        """Compare two schemas without publishing."""
        response = await self._http.post(
            f"{self._base}/compare",
            json={
                "old_schema": old_schema,
                "new_schema": new_schema,
                "compatibility_mode": compatibility_mode.value,
            },
        )
        return response


class RegistrationsResource:
    """Registrations API resource (sync)."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._base = "/api/v1/registrations"

    def create(
        self,
        contract_id: UUID | str,
        consumer_team_id: UUID | str,
        pinned_version: str | None = None,
    ) -> Registration:
        """Register as a consumer of a contract."""
        data = RegistrationCreate(
            consumer_team_id=UUID(str(consumer_team_id)),
            pinned_version=pinned_version,
        )
        response = self._http.post(
            self._base,
            json=data.model_dump(mode="json"),
            params={"contract_id": str(contract_id)},
        )
        return Registration.model_validate(response)

    def get(self, registration_id: UUID | str) -> Registration:
        """Get a registration by ID."""
        response = self._http.get(f"{self._base}/{registration_id}")
        return Registration.model_validate(response)

    def update(
        self,
        registration_id: UUID | str,
        pinned_version: str | None = None,
        status: RegistrationStatus | None = None,
    ) -> Registration:
        """Update a registration."""
        data = RegistrationUpdate(
            pinned_version=pinned_version,
            status=status,
        )
        response = self._http.patch(
            f"{self._base}/{registration_id}",
            json=data.model_dump(exclude_none=True, mode="json"),
        )
        return Registration.model_validate(response)

    def delete(self, registration_id: UUID | str) -> None:
        """Delete a registration."""
        self._http.delete(f"{self._base}/{registration_id}")


class AsyncRegistrationsResource:
    """Registrations API resource (async)."""

    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http
        self._base = "/api/v1/registrations"

    async def create(
        self,
        contract_id: UUID | str,
        consumer_team_id: UUID | str,
        pinned_version: str | None = None,
    ) -> Registration:
        """Register as a consumer of a contract."""
        data = RegistrationCreate(
            consumer_team_id=UUID(str(consumer_team_id)),
            pinned_version=pinned_version,
        )
        response = await self._http.post(
            self._base,
            json=data.model_dump(mode="json"),
            params={"contract_id": str(contract_id)},
        )
        return Registration.model_validate(response)

    async def get(self, registration_id: UUID | str) -> Registration:
        """Get a registration by ID."""
        response = await self._http.get(f"{self._base}/{registration_id}")
        return Registration.model_validate(response)

    async def update(
        self,
        registration_id: UUID | str,
        pinned_version: str | None = None,
        status: RegistrationStatus | None = None,
    ) -> Registration:
        """Update a registration."""
        data = RegistrationUpdate(
            pinned_version=pinned_version,
            status=status,
        )
        response = await self._http.patch(
            f"{self._base}/{registration_id}",
            json=data.model_dump(exclude_none=True, mode="json"),
        )
        return Registration.model_validate(response)

    async def delete(self, registration_id: UUID | str) -> None:
        """Delete a registration."""
        await self._http.delete(f"{self._base}/{registration_id}")


class ProposalsResource:
    """Proposals API resource (sync)."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._base = "/api/v1/proposals"

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        asset_id: UUID | str | None = None,
        status: ProposalStatus | None = None,
    ) -> list[Proposal]:
        """List proposals with optional filters."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if asset_id:
            params["asset_id"] = str(asset_id)
        if status:
            params["status"] = status.value
        response = self._http.get(self._base, params=params)
        return [Proposal.model_validate(p) for p in response]

    def get(self, proposal_id: UUID | str) -> Proposal:
        """Get a proposal by ID."""
        response = self._http.get(f"{self._base}/{proposal_id}")
        return Proposal.model_validate(response)

    def get_status(self, proposal_id: UUID | str) -> ProposalStatusResponse:
        """Get detailed status of a proposal including acknowledgments."""
        response = self._http.get(f"{self._base}/{proposal_id}/status")
        return ProposalStatusResponse.model_validate(response)

    def acknowledge(
        self,
        proposal_id: UUID | str,
        consumer_team_id: UUID | str,
        response_type: AcknowledgmentResponseType,
        notes: str | None = None,
    ) -> Acknowledgment:
        """Acknowledge a proposal."""
        response = self._http.post(
            f"{self._base}/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": str(consumer_team_id),
                "response": response_type.value,
                "notes": notes,
            },
        )
        return Acknowledgment.model_validate(response)

    def withdraw(self, proposal_id: UUID | str) -> Proposal:
        """Withdraw a proposal."""
        response = self._http.post(f"{self._base}/{proposal_id}/withdraw")
        return Proposal.model_validate(response)

    def force(self, proposal_id: UUID | str) -> Proposal:
        """Force approve a proposal (admin only)."""
        response = self._http.post(f"{self._base}/{proposal_id}/force")
        return Proposal.model_validate(response)

    def publish(self, proposal_id: UUID | str) -> Contract:
        """Publish an approved proposal as a new contract."""
        response = self._http.post(f"{self._base}/{proposal_id}/publish")
        return Contract.model_validate(response)


class AsyncProposalsResource:
    """Proposals API resource (async)."""

    def __init__(self, http: AsyncHttpClient) -> None:
        self._http = http
        self._base = "/api/v1/proposals"

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        asset_id: UUID | str | None = None,
        status: ProposalStatus | None = None,
    ) -> list[Proposal]:
        """List proposals with optional filters."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if asset_id:
            params["asset_id"] = str(asset_id)
        if status:
            params["status"] = status.value
        response = await self._http.get(self._base, params=params)
        return [Proposal.model_validate(p) for p in response]

    async def get(self, proposal_id: UUID | str) -> Proposal:
        """Get a proposal by ID."""
        response = await self._http.get(f"{self._base}/{proposal_id}")
        return Proposal.model_validate(response)

    async def get_status(self, proposal_id: UUID | str) -> ProposalStatusResponse:
        """Get detailed status of a proposal including acknowledgments."""
        response = await self._http.get(f"{self._base}/{proposal_id}/status")
        return ProposalStatusResponse.model_validate(response)

    async def acknowledge(
        self,
        proposal_id: UUID | str,
        consumer_team_id: UUID | str,
        response_type: AcknowledgmentResponseType,
        notes: str | None = None,
    ) -> Acknowledgment:
        """Acknowledge a proposal."""
        response = await self._http.post(
            f"{self._base}/{proposal_id}/acknowledge",
            json={
                "consumer_team_id": str(consumer_team_id),
                "response": response_type.value,
                "notes": notes,
            },
        )
        return Acknowledgment.model_validate(response)

    async def withdraw(self, proposal_id: UUID | str) -> Proposal:
        """Withdraw a proposal."""
        response = await self._http.post(f"{self._base}/{proposal_id}/withdraw")
        return Proposal.model_validate(response)

    async def force(self, proposal_id: UUID | str) -> Proposal:
        """Force approve a proposal (admin only)."""
        response = await self._http.post(f"{self._base}/{proposal_id}/force")
        return Proposal.model_validate(response)

    async def publish(self, proposal_id: UUID | str) -> Contract:
        """Publish an approved proposal as a new contract."""
        response = await self._http.post(f"{self._base}/{proposal_id}/publish")
        return Contract.model_validate(response)
