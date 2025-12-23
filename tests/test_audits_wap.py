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


class TestGuaranteeResults:
    """Tests for per-guarantee result tracking."""

    async def test_report_audit_with_guarantee_results(self, client: AsyncClient):
        """Report audit with per-guarantee results."""
        team_resp = await client.post("/api/v1/teams", json={"name": "guarantee-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.guarantee_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "failed",
                "triggered_by": "dbt_test",
                "guarantee_results": [
                    {
                        "guarantee_id": "not_null_user_id",
                        "passed": True,
                        "rows_checked": 1000,
                        "rows_failed": 0,
                    },
                    {
                        "guarantee_id": "unique_order_id",
                        "passed": False,
                        "error_message": "Found 5 duplicates",
                        "rows_checked": 1000,
                        "rows_failed": 5,
                    },
                    {
                        "guarantee_id": "accepted_values_status",
                        "passed": False,
                        "error_message": "Invalid value 'unknown'",
                        "rows_checked": 1000,
                        "rows_failed": 3,
                    },
                ],
            },
        )

        assert audit_resp.status_code == 200
        data = audit_resp.json()
        # Auto-calculated from guarantee_results
        assert data["guarantees_checked"] == 3
        assert data["guarantees_passed"] == 1
        assert data["guarantees_failed"] == 2
        assert len(data["guarantee_results"]) == 3

    async def test_guarantee_results_auto_counts(self, client: AsyncClient):
        """Guarantee counts auto-calculated when not provided."""
        team_resp = await client.post("/api/v1/teams", json={"name": "auto-count"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.auto_count_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Send with guarantee_results but no explicit counts
        audit_resp = await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "passed",
                "triggered_by": "dbt_test",
                "guarantee_results": [
                    {"guarantee_id": "test1", "passed": True},
                    {"guarantee_id": "test2", "passed": True},
                ],
            },
        )

        assert audit_resp.status_code == 200
        data = audit_resp.json()
        assert data["guarantees_checked"] == 2
        assert data["guarantees_passed"] == 2
        assert data["guarantees_failed"] == 0

    async def test_history_includes_failed_guarantees(self, client: AsyncClient):
        """Audit history includes names of failed guarantees."""
        team_resp = await client.post("/api/v1/teams", json={"name": "failed-guar"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.failed_guarantees", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "failed",
                "triggered_by": "dbt_test",
                "guarantee_results": [
                    {"guarantee_id": "test_passed", "passed": True},
                    {"guarantee_id": "test_failed_1", "passed": False},
                    {"guarantee_id": "test_failed_2", "passed": False},
                ],
            },
        )

        history_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-history")
        assert history_resp.status_code == 200
        data = history_resp.json()
        assert len(data["runs"]) == 1
        run = data["runs"][0]
        assert "test_failed_1" in run["failed_guarantees"]
        assert "test_failed_2" in run["failed_guarantees"]
        assert "test_passed" not in run["failed_guarantees"]


class TestAuditTrends:
    """Tests for GET /api/v1/assets/{asset_id}/audit-trends endpoint."""

    async def test_get_trends_no_runs(self, client: AsyncClient):
        """Get trends for asset with no audit runs."""
        team_resp = await client.post("/api/v1/teams", json={"name": "no-runs"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.no_runs_trends", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        trends_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-trends")

        assert trends_resp.status_code == 200
        data = trends_resp.json()
        assert data["asset_id"] == asset_id
        assert data["asset_fqn"] == "db.schema.no_runs_trends"
        assert data["last_run"] is None
        assert data["last_24h"]["total_runs"] == 0
        assert data["last_7d"]["total_runs"] == 0
        assert data["last_30d"]["total_runs"] == 0
        assert data["last_24h"]["failure_rate"] == 0.0

    async def test_get_trends_with_runs(self, client: AsyncClient):
        """Get trends with audit runs."""
        team_resp = await client.post("/api/v1/teams", json={"name": "trends-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.trends_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create 3 passed and 2 failed runs
        for status in ["passed", "passed", "passed", "failed", "failed"]:
            await client.post(
                f"/api/v1/assets/{asset_id}/audit-results",
                json={
                    "status": status,
                    "guarantees_checked": 5,
                    "guarantees_passed": 5 if status == "passed" else 0,
                    "guarantees_failed": 0 if status == "passed" else 5,
                    "triggered_by": "dbt_test",
                },
            )

        trends_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-trends")

        assert trends_resp.status_code == 200
        data = trends_resp.json()
        assert data["last_24h"]["total_runs"] == 5
        assert data["last_24h"]["passed"] == 3
        assert data["last_24h"]["failed"] == 2
        assert data["last_24h"]["failure_rate"] == 0.4  # 2/5

    async def test_trends_last_run_summary(self, client: AsyncClient):
        """Last run is included in trends."""
        team_resp = await client.post("/api/v1/teams", json={"name": "lastrun-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.lastrun_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        await client.post(
            f"/api/v1/assets/{asset_id}/audit-results",
            json={
                "status": "failed",
                "guarantees_checked": 3,
                "guarantees_passed": 1,
                "guarantees_failed": 2,
                "triggered_by": "soda",
            },
        )

        trends_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-trends")

        assert trends_resp.status_code == 200
        data = trends_resp.json()
        assert data["last_run"] is not None
        assert data["last_run"]["status"] == "failed"
        assert data["last_run"]["triggered_by"] == "soda"
        assert data["last_run"]["guarantees_failed"] == 2

    async def test_trends_most_failed_guarantees(self, client: AsyncClient):
        """Trends include most frequently failing guarantees."""
        team_resp = await client.post("/api/v1/teams", json={"name": "mostfailed"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.mostfailed_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create runs with recurring guarantee failures
        for i in range(3):
            await client.post(
                f"/api/v1/assets/{asset_id}/audit-results",
                json={
                    "status": "failed",
                    "triggered_by": "dbt_test",
                    "guarantee_results": [
                        {"guarantee_id": "recurring_failure", "passed": False},
                        {"guarantee_id": f"one_time_failure_{i}", "passed": False},
                        {"guarantee_id": "always_passes", "passed": True},
                    ],
                },
            )

        trends_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-trends")

        assert trends_resp.status_code == 200
        data = trends_resp.json()
        most_failed = data["last_7d"]["most_failed_guarantees"]
        assert len(most_failed) > 0
        # recurring_failure should be at the top
        assert most_failed[0]["guarantee_id"] == "recurring_failure"
        assert most_failed[0]["failure_count"] == 3

    async def test_trends_alerts_high_failure_rate(self, client: AsyncClient):
        """Alert generated for high failure rate."""
        team_resp = await client.post("/api/v1/teams", json={"name": "alert-team"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.alert_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Create 4 runs: 1 passed, 3 failed (75% failure rate, >50% threshold)
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
        for _ in range(3):
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

        trends_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-trends")

        assert trends_resp.status_code == 200
        data = trends_resp.json()
        # Should have alert for high failure rate
        assert any("failure rate" in alert.lower() for alert in data["alerts"])

    async def test_trends_alerts_last_run_failed(self, client: AsyncClient):
        """Alert generated when most recent run failed."""
        team_resp = await client.post("/api/v1/teams", json={"name": "lastfail"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.lastfail_test", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # Pass first, then fail
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

        trends_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-trends")

        assert trends_resp.status_code == 200
        data = trends_resp.json()
        assert any(
            "recent" in alert.lower() and "failed" in alert.lower() for alert in data["alerts"]
        )

    async def test_trends_asset_not_found(self, client: AsyncClient):
        """Get trends for non-existent asset."""
        fake_id = str(uuid4())
        trends_resp = await client.get(f"/api/v1/assets/{fake_id}/audit-trends")

        assert trends_resp.status_code == 404

    async def test_trends_partial_counts_as_failure(self, client: AsyncClient):
        """Partial status counts towards failure rate."""
        team_resp = await client.post("/api/v1/teams", json={"name": "partial-fr"})
        team_id = team_resp.json()["id"]

        asset_resp = await client.post(
            "/api/v1/assets",
            json={"fqn": "db.schema.partial_rate", "owner_team_id": team_id},
        )
        asset_id = asset_resp.json()["id"]

        # 1 passed, 1 partial
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
                "status": "partial",
                "guarantees_checked": 2,
                "guarantees_passed": 1,
                "guarantees_failed": 0,
                "triggered_by": "dbt_test",
            },
        )

        trends_resp = await client.get(f"/api/v1/assets/{asset_id}/audit-trends")

        assert trends_resp.status_code == 200
        data = trends_resp.json()
        assert data["last_24h"]["passed"] == 1
        assert data["last_24h"]["partial"] == 1
        assert data["last_24h"]["failed"] == 0
        # Partial counts toward failure rate: 1/2 = 0.5
        assert data["last_24h"]["failure_rate"] == 0.5
