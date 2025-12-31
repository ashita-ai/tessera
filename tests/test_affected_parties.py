"""Tests for affected parties and objections functionality."""

import pytest
from httpx import AsyncClient


class TestAffectedParties:
    """Test that proposals compute and store affected parties."""

    @pytest.mark.asyncio
    async def test_proposal_includes_affected_parties_from_dependencies_table(
        self, client: AsyncClient
    ) -> None:
        """Test that affected parties are populated from dependencies table."""
        # Create teams
        owner_team = (await client.post("/api/v1/teams", json={"name": "owner-team"})).json()
        downstream_team = (
            await client.post("/api/v1/teams", json={"name": "downstream-team"})
        ).json()

        # Create upstream asset with contract
        upstream = (
            await client.post(
                "/api/v1/assets", json={"fqn": "db.raw.orders", "owner_team_id": owner_team["id"]}
            )
        ).json()

        schema_v1 = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        # Create downstream asset owned by different team
        downstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.staging.stg_orders", "owner_team_id": downstream_team["id"]},
            )
        ).json()

        # Create dependency: downstream depends on upstream
        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        # Now publish a breaking change to upstream
        schema_v2 = {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        }  # type changed
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        data = result.json()
        assert data.get("action") == "proposal_created", f"Expected proposal, got: {data}"
        proposal_id = data["proposal"]["id"]

        # Fetch the proposal and verify affected parties
        proposal = (await client.get(f"/api/v1/proposals/{proposal_id}")).json()

        assert len(proposal["affected_teams"]) == 1
        assert proposal["affected_teams"][0]["team_id"] == downstream_team["id"]
        assert proposal["affected_teams"][0]["team_name"] == "downstream-team"

        assert len(proposal["affected_assets"]) == 1
        assert proposal["affected_assets"][0]["asset_fqn"] == "db.staging.stg_orders"
        assert proposal["affected_assets"][0]["owner_team_id"] == downstream_team["id"]

    @pytest.mark.asyncio
    async def test_proposal_excludes_owner_team_from_affected_parties(
        self, client: AsyncClient
    ) -> None:
        """Test that the asset owner's team is not included in affected parties."""
        # Create team that owns both assets
        owner_team = (await client.post("/api/v1/teams", json={"name": "same-owner"})).json()

        # Create upstream asset with contract
        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.raw.self_orders", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"id": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        # Create downstream asset owned by SAME team
        downstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.staging.self_stg", "owner_team_id": owner_team["id"]},
            )
        ).json()

        # Create dependency
        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        # Publish breaking change
        schema_v2 = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        data = result.json()
        assert data.get("action") == "proposal_created"
        proposal_id = data["proposal"]["id"]

        proposal = (await client.get(f"/api/v1/proposals/{proposal_id}")).json()
        # Same team should be excluded
        assert len(proposal["affected_teams"]) == 0
        assert len(proposal["affected_assets"]) == 0


class TestObjections:
    """Test objection filing and display."""

    @pytest.mark.asyncio
    async def test_affected_team_can_file_objection(self, client: AsyncClient) -> None:
        """Test that an affected team can file an objection."""
        # Setup: create teams and assets
        owner_team = (await client.post("/api/v1/teams", json={"name": "obj-owner"})).json()
        affected_team = (await client.post("/api/v1/teams", json={"name": "obj-affected"})).json()

        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.raw.objection_test", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"id": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        downstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.mart.objection_downstream", "owner_team_id": affected_team["id"]},
            )
        ).json()

        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        # Create proposal via breaking change
        schema_v2 = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        proposal_id = result.json()["proposal"]["id"]

        # File objection as affected team
        objection_result = await client.post(
            f"/api/v1/proposals/{proposal_id}/object",
            params={"objector_team_id": affected_team["id"]},
            json={"reason": "This will break our downstream pipeline!"},
        )
        assert objection_result.status_code == 201
        obj_data = objection_result.json()
        assert obj_data["action"] == "objection_filed"
        assert obj_data["total_objections"] == 1
        assert obj_data["objection"]["reason"] == "This will break our downstream pipeline!"

        # Verify objection is stored in proposal
        proposal = (await client.get(f"/api/v1/proposals/{proposal_id}")).json()
        assert len(proposal["objections"]) == 1
        assert proposal["objections"][0]["team_name"] == "obj-affected"
        assert proposal["has_objections"] is True

    @pytest.mark.asyncio
    async def test_non_affected_team_cannot_file_objection(self, client: AsyncClient) -> None:
        """Test that a non-affected team cannot file an objection."""
        owner_team = (await client.post("/api/v1/teams", json={"name": "obj-owner2"})).json()
        random_team = (await client.post("/api/v1/teams", json={"name": "obj-random"})).json()

        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.raw.no_objection_test", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"id": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        # Create breaking change proposal (no dependencies, so no affected teams)
        schema_v2 = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        proposal_id = result.json()["proposal"]["id"]

        # Random team tries to file objection
        objection_result = await client.post(
            f"/api/v1/proposals/{proposal_id}/object",
            params={"objector_team_id": random_team["id"]},
            json={"reason": "I want to object too!"},
        )
        assert (
            objection_result.status_code == 403
        ), f"Expected 403, got {objection_result.status_code}: {objection_result.json()}"
        error_body = objection_result.json()
        assert "Only affected teams" in error_body.get(
            "message", error_body.get("error", {}).get("message", str(error_body))
        )

    @pytest.mark.asyncio
    async def test_cannot_file_duplicate_objection(self, client: AsyncClient) -> None:
        """Test that a team cannot file multiple objections to the same proposal."""
        owner_team = (await client.post("/api/v1/teams", json={"name": "dup-owner"})).json()
        affected_team = (await client.post("/api/v1/teams", json={"name": "dup-affected"})).json()

        upstream = (
            await client.post(
                "/api/v1/assets", json={"fqn": "db.raw.dup_test", "owner_team_id": owner_team["id"]}
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"x": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        downstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.mart.dup_downstream", "owner_team_id": affected_team["id"]},
            )
        ).json()

        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        schema_v2 = {"type": "object", "properties": {"x": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        proposal_id = result.json()["proposal"]["id"]

        # First objection succeeds
        r1 = await client.post(
            f"/api/v1/proposals/{proposal_id}/object",
            params={"objector_team_id": affected_team["id"]},
            json={"reason": "First objection"},
        )
        assert r1.status_code == 201

        # Second objection from same team fails
        r2 = await client.post(
            f"/api/v1/proposals/{proposal_id}/object",
            params={"objector_team_id": affected_team["id"]},
            json={"reason": "Second objection attempt"},
        )
        assert r2.status_code == 409  # Duplicate

    @pytest.mark.asyncio
    async def test_objection_does_not_block_proposal(self, client: AsyncClient) -> None:
        """Test that objections are non-blocking - proposal can still be force approved."""
        owner_team = (await client.post("/api/v1/teams", json={"name": "nonblock-owner"})).json()
        affected_team = (
            await client.post("/api/v1/teams", json={"name": "nonblock-affected"})
        ).json()

        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.raw.nonblock_test", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"y": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        downstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.mart.nonblock_down", "owner_team_id": affected_team["id"]},
            )
        ).json()

        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        schema_v2 = {"type": "object", "properties": {"y": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201
        proposal_id = result.json()["proposal"]["id"]

        # File objection
        await client.post(
            f"/api/v1/proposals/{proposal_id}/object",
            params={"objector_team_id": affected_team["id"]},
            json={"reason": "I object!"},
        )

        # Force approve still works despite objection
        force_result = await client.post(
            f"/api/v1/proposals/{proposal_id}/force",
            params={"actor_id": owner_team["id"]},
        )
        assert force_result.status_code == 200
        assert force_result.json()["status"] == "approved"


class TestGetAffectedPartiesService:
    """Test the get_affected_parties service function directly."""

    @pytest.mark.asyncio
    async def test_affected_parties_from_metadata_depends_on(self, client: AsyncClient) -> None:
        """Test that affected parties are discovered from metadata.depends_on field."""
        owner_team = (await client.post("/api/v1/teams", json={"name": "meta-owner"})).json()
        downstream_team = (
            await client.post("/api/v1/teams", json={"name": "meta-affected"})
        ).json()

        # Create upstream asset
        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.source.meta_src", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"z": {"type": "integer"}}}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        # Create downstream asset with metadata.depends_on
        await client.post(
            "/api/v1/assets",
            json={
                "fqn": "db.model.meta_model",
                "owner_team_id": downstream_team["id"],
                "metadata": {"depends_on": ["db.source.meta_src"]},
            },
        )

        # Publish breaking change
        schema_v2 = {"type": "object", "properties": {"z": {"type": "string"}}}
        result = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result.status_code == 201

        data = result.json()
        assert data.get("action") == "proposal_created"
        proposal_id = data["proposal"]["id"]

        proposal = (await client.get(f"/api/v1/proposals/{proposal_id}")).json()
        # Should find the downstream asset via metadata.depends_on
        assert len(proposal["affected_assets"]) >= 1
        affected_fqns = [a["asset_fqn"] for a in proposal["affected_assets"]]
        assert "db.model.meta_model" in affected_fqns


class TestDuplicateProposalPrevention:
    """Test that the API prevents duplicate proposals for the same asset."""

    @pytest.mark.asyncio
    async def test_cannot_create_duplicate_proposal_for_same_asset(
        self, client: AsyncClient
    ) -> None:
        """Test that a second breaking change while proposal pending fails."""
        # Setup: create team and assets
        owner_team = (await client.post("/api/v1/teams", json={"name": "dup-prop-owner"})).json()
        consumer_team = (
            await client.post("/api/v1/teams", json={"name": "dup-prop-consumer"})
        ).json()

        # Create asset with initial contract
        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.raw.dup_proposal_test", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        # Create downstream asset owned by different team and register dependency
        downstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.staging.dup_downstream", "owner_team_id": consumer_team["id"]},
            )
        ).json()

        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        # First breaking change should create a proposal
        schema_v2 = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
        result1 = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result1.status_code == 201
        data1 = result1.json()
        assert data1.get("action") == "proposal_created"

        # Second breaking change while first proposal is pending should fail
        schema_v3 = {
            "type": "object",
            "properties": {"id": {"type": "boolean"}},
            "required": ["id"],
        }
        result2 = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v3, "compatibility_mode": "backward"},
        )
        assert result2.status_code == 409  # Conflict/Duplicate
        error_body = result2.json()
        assert (
            "pending proposal" in error_body.get("message", "").lower()
            or "pending proposal" in str(error_body).lower()
        )

    @pytest.mark.asyncio
    async def test_can_create_new_proposal_after_previous_resolved(
        self, client: AsyncClient
    ) -> None:
        """Test that a new proposal can be created after the previous one is resolved."""
        # Setup
        owner_team = (
            await client.post("/api/v1/teams", json={"name": "resolved-prop-owner"})
        ).json()
        consumer_team = (
            await client.post("/api/v1/teams", json={"name": "resolved-prop-consumer"})
        ).json()

        upstream = (
            await client.post(
                "/api/v1/assets",
                json={"fqn": "db.raw.resolved_proposal_test", "owner_team_id": owner_team["id"]},
            )
        ).json()

        schema_v1 = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
        await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v1, "compatibility_mode": "backward"},
        )

        downstream = (
            await client.post(
                "/api/v1/assets",
                json={
                    "fqn": "db.staging.resolved_downstream",
                    "owner_team_id": consumer_team["id"],
                },
            )
        ).json()

        await client.post(
            f"/api/v1/assets/{downstream['id']}/dependencies",
            json={"depends_on_asset_id": upstream["id"]},
        )

        # First breaking change creates proposal
        schema_v2 = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        result1 = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v2, "compatibility_mode": "backward"},
        )
        assert result1.status_code == 201
        proposal_id = result1.json()["proposal"]["id"]

        # Withdraw the proposal (resolve it)
        withdraw_result = await client.post(
            f"/api/v1/proposals/{proposal_id}/withdraw",
            params={"actor_id": owner_team["id"]},
        )
        assert withdraw_result.status_code == 200

        # Now we should be able to create a new proposal
        schema_v3 = {"type": "object", "properties": {"x": {"type": "boolean"}}, "required": ["x"]}
        result2 = await client.post(
            f"/api/v1/assets/{upstream['id']}/contracts",
            params={"published_by": owner_team["id"]},
            json={"schema": schema_v3, "compatibility_mode": "backward"},
        )
        assert result2.status_code == 201
        assert result2.json().get("action") == "proposal_created"
