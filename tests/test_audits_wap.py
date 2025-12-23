"""Tests for WAP (Write-Audit-Publish) audit endpoints."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from httpx import AsyncClient


class TestReportAuditResult:
    """Tests for POST /api/v1/assets/{asset_id}/audit-results endpoint."""

    async def test_report_passed_audit(self, client: AsyncClient):
        """Report a passed audit result."""
        # Create team and asset
        team_resp = await client.post("/api/v1/teams", json={"name": "audit-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.audit_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Report audit result
        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 10,
                "guarantees_passed": 10,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["asset_id"] == asset_id
        assert data["asset_fqn"] == "db.schema.audit_test"
        assert data["status"] == "passed"
        assert data["guarantees_checked"] == 10
        assert data["guarantees_passed"] == 10
        assert data["guarantees_failed"] == 0
        assert data["triggered_by"] == "dbt_test"
        assert "id" in data
        assert "run_at" in data

    async def test_report_failed_audit(self, client: AsyncClient):
        """Report a failed audit result."""
        team_resp = await client.post("/api/v1/teams", json={"name": "fail-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.fail_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "failed",
                "guarantees_checked": 5,
                "guarantees_passed": 3,
                "guarantees_failed": 2,
                "triggered_by": "great_expectations",
                "details": {
                    "failed_tests": [
                        {"name": "not_null_user_id", "message": "Found 5 nulls"},
                        {"name": "unique_order_id", "message": "Found 3 duplicates"},
                    ]
                },
            },
        )

        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["status"] == "failed"
        assert data["guarantees_failed"] == 2
        assert data["triggered_by"] == "great_expectations"

    async def test_report_partial_audit(self, client: AsyncClient):
        """Report a partial audit result (some tests skipped)."""
        team_resp = await client.post("/api/v1/teams", json={"name": "partial-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.partial_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "partial",
                "guarantees_checked": 3,
                "guarantees_passed": 3,
                "guarantees_failed": 0,
                "triggered_by": "soda",
            },
        )

        assert audit_resp.status_code == 200
        assert audit_resp.json()["status"] == "partial"

    async def test_report_audit_with_run_id(self, client: AsyncClient):
        """Report audit with external run ID for correlation."""
        team_resp = await client.post("/api/v1/teams", json={"name": "runid-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.runid_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        invocation_id = "dbt-run-abc123"
        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
                "run_id": invocation_id,
            },
        )

        assert audit_resp.status_code == 200
        assert audit_resp.json()["run_id"] == invocation_id

    async def test_report_audit_with_custom_timestamp(self, client: AsyncClient):
        """Report audit with custom run_at timestamp."""
        team_resp = await client.post("/api/v1/teams", json={"name": "ts-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.ts_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        custom_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "manual",
                "run_at": custom_time,
            },
        )

        assert audit_resp.status_code == 200

    async def test_report_audit_with_active_contract(self, client: AsyncClient):
        """Report audit when asset has active contract."""
        team_resp = await client.post("/api/v1/teams", json={"name": "contract-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.contract_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish contract (requires published_by query param)
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={"version": "1.0.0", "schema": schema, "compatibility_mode": "backward"},
        )
        assert contract_resp.status_code == 201, f"Contract creation failed: {contract_resp.json()}"
        contract_id = contract_resp.json()["contract"]["id"]

        # Report audit
        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 5,
                "guarantees_passed": 5,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["contract_id"] == contract_id
        assert data["contract_version"] == "1.0.0"

    async def test_report_audit_without_contract(self, client: AsyncClient):
        """Report audit for asset without contract."""
        team_resp = await client.post("/api/v1/teams", json={"name": "no-contract"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.no_contract", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "manual",
            },
        )

        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["contract_id"] is None
        assert data["contract_version"] is None

    async def test_report_audit_asset_not_found(self, client: AsyncClient):
        """Report audit for non-existent asset."""
        fake_id = str(uuid4())
        audit_resp = await client.post(
            f"/api/v1/assets/{fake_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        assert audit_resp.status_code == 404
        # Check for error message in response
        resp_data = audit_resp.json()
        assert "detail" in resp_data or "message" in resp_data or "error" in resp_data

    async def test_report_audit_deleted_asset(self, client: AsyncClient):
        """Cannot report audit for soft-deleted asset."""
        team_resp = await client.post("/api/v1/teams", json={"name": "deleted-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.deleted_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Delete asset
        delete_resp = await client.delete(f"/api/v1/assets/{asset_id}")
        assert delete_resp.status_code == 204

        # Try to report audit
        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        assert audit_resp.status_code == 404

    async def test_report_audit_invalid_status(self, client: AsyncClient):
        """Invalid status value is rejected."""
        team_resp = await client.post("/api/v1/teams", json={"name": "invalid-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.invalid_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "invalid_status",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        assert audit_resp.status_code == 422


class TestGetAuditHistory:
    """Tests for GET /api/v1/assets/{asset_id}/audit-history endpoint."""

    async def test_get_empty_history(self, client: AsyncClient):
        """Get history for asset with no audits."""
        team_resp = await client.post("/api/v1/teams", json={"name": "empty-hist"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.empty_history", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        history_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-history")

        assert history_resp.status_code == 200
        data = history_resp.json()
        assert data["asset_id"] == asset_id
        assert data["asset_fqn"] == "db.schema.empty_history"
        assert data["total_runs"] == 0
        assert data["runs"] == []

    async def test_get_history_with_runs(self, client: AsyncClient):
        """Get history with multiple audit runs."""
        team_resp = await client.post("/api/v1/teams", json={"name": "runs-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.runs_history", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create multiple audit runs
        for i in range(3):
            await client.post(
                f"/api/v1/assets/{asset_id}/audit-results",
                json={
                    "status": "passed" if i % 2 == 0 else "failed",
                    "guarantees_checked": i + 1,
                    "guarantees_passed": i + 1 if i % 2 == 0 else 0,
                    "guarantees_failed": 0 if i % 2 == 0 else i + 1,
                    "triggered_by": "dbt_test",
                },
            )

        history_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-history")

        assert history_resp.status_code == 200
        data = history_resp.json()
        assert data["total_runs"] == 3
        assert len(data["runs"]) == 3

    async def test_filter_by_status(self, client: AsyncClient):
        """Filter audit history by status."""
        team_resp = await client.post("/api/v1/teams", json={"name": "filter-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.filter_status", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create passed and failed runs
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "failed",
                "guarantees_checked": 1,
                "guarantees_passed": 0,
                "guarantees_failed": 1,
                "triggered_by": "dbt_test",
            },
        )
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        # Filter by failed
        failed_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-history?status=failed")
        assert failed_resp.status_code == 200
        data = failed_resp.json()
        assert data["total_runs"] == 1
        assert all(r["status"] == "failed" for r in data["runs"])

        # Filter by passed
        passed_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-history?status=passed")
        assert passed_resp.status_code == 200
        data = passed_resp.json()
        assert data["total_runs"] == 2
        assert all(r["status"] == "passed" for r in data["runs"])

    async def test_filter_by_triggered_by(self, client: AsyncClient):
        """Filter audit history by trigger source."""
        team_resp = await client.post("/api/v1/teams", json={"name": "trigger-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.filter_trigger", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create runs from different sources
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "great_expectations",
            },
        )
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        # Filter by dbt_test
        dbt_resp = await client.get(
            f"/api/v1/assets/{asset_id}/audit-history?triggered_by=dbt_test"
        )
        assert dbt_resp.status_code == 200
        data = dbt_resp.json()
        assert data["total_runs"] == 2
        assert all(r["triggered_by"] == "dbt_test" for r in data["runs"])

    async def test_history_limit(self, client: AsyncClient):
        """Limit number of returned runs."""
        team_resp = await client.post("/api/v1/teams", json={"name": "limit-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.limit_history", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create 5 runs
        for i in range(5):
            await client.post(
                f"/api/v1/assets/{asset_id}/audit-results",
                json={
                    "status": "passed",
                    "guarantees_checked": 1,
                    "guarantees_passed": 1,
                    "guarantees_failed": 0,
                    "triggered_by": "dbt_test",
                },
            )

        # Limit to 2
        limited_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-history?limit=2")
        assert limited_resp.status_code == 200
        data = limited_resp.json()
        assert data["total_runs"] == 5  # Total count is still 5
        assert len(data["runs"]) == 2  # But only 2 returned

    async def test_history_with_contract_versions(self, client: AsyncClient):
        """History includes contract versions for each run."""
        team_resp = await client.post("/api/v1/teams", json={"name": "version-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.version_history", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Publish contract v1 (requires published_by query param)
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        contract_resp = await client.post(
            f"/api/v1/assets/{asset_id}/contracts?published_by={team_id}",
            json={"version": "1.0.0", "schema": schema, "compatibility_mode": "backward"},
        )
        assert contract_resp.status_code == 201, f"Contract creation failed: {contract_resp.json()}"

        # Report audit against v1
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        history_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-history")
        assert history_resp.status_code == 200
        data = history_resp.json()
        assert len(data["runs"]) == 1
        assert data["runs"][0]["contract_version"] == "1.0.0"

    async def test_history_asset_not_found(self, client: AsyncClient):
        """Get history for non-existent asset."""
        fake_id = str(uuid4())
        history_resp = await client.get(f"/api/v1/assets/{fake_id}/audit-history")

        assert history_resp.status_code == 404

    async def test_combined_filters(self, client: AsyncClient):
        """Combine status and triggered_by filters."""
        team_resp = await client.post("/api/v1/teams", json={"name": "combo-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.combo_filter", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create diverse runs
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "guarantees_checked": 1,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "failed",
                "guarantees_checked": 1,
                "guarantees_passed": 0,
                "guarantees_failed": 1,
                "triggered_by": "dbt_test",
            },
        )
        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "failed",
                "guarantees_checked": 1,
                "guarantees_passed": 0,
                "guarantees_failed": 1,
                "triggered_by": "soda",
            },
        )

        # Filter for failed dbt_test runs only
        combo_resp = await client.get(
            f"/api/v1/assets/{asset_id}/audit-history?status=failed&triggered_by=dbt_test"
        )
        assert combo_resp.status_code == 200
        data = combo_resp.json()
        assert data["total_runs"] == 1
        assert data["runs"][0]["status"] == "failed"
        assert data["runs"][0]["triggered_by"] == "dbt_test"
