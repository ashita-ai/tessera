"""Admin CLI commands for Tessera."""

import asyncio
import logging
from typing import Annotated

import typer
from rich.console import Console

logger = logging.getLogger(__name__)

app = typer.Typer(help="Admin operations")
console = Console()
err_console = Console(stderr=True)


async def _run_backfill() -> dict[str, int]:
    """Execute the dependency backfill against the database."""

    from sqlalchemy import select

    from tessera.db import AssetDB, AssetDependencyDB
    from tessera.db.database import get_async_session_maker, init_db
    from tessera.models.enums import DependencyType

    await init_db()

    counts = {"created": 0, "skipped_exists": 0, "skipped_unresolved": 0}

    async_session = get_async_session_maker()
    async with async_session() as session:
        # Load all non-deleted assets that have metadata.depends_on
        all_assets_result = await session.execute(
            select(AssetDB).where(AssetDB.deleted_at.is_(None))
        )
        all_assets = all_assets_result.scalars().all()

        # Build FQN lookup
        fqn_to_asset: dict[str, AssetDB] = {a.fqn: a for a in all_assets}

        # Build set of assets with depends_on metadata
        assets_with_deps = [a for a in all_assets if a.metadata_ and a.metadata_.get("depends_on")]

        if not assets_with_deps:
            console.print("[dim]No assets with metadata.depends_on found[/dim]")
            return counts

        # Load all existing dependency rows
        existing_result = await session.execute(
            select(AssetDependencyDB).where(AssetDependencyDB.deleted_at.is_(None))
        )
        existing_edges: set[tuple[str, str, str]] = {
            (str(row.dependent_asset_id), str(row.dependency_asset_id), row.dependency_type)
            for row in existing_result.scalars().all()
        }

        for asset in assets_with_deps:
            depends_on_fqns: list[str] = asset.metadata_.get("depends_on", [])
            resource_type = (asset.metadata_ or {}).get("resource_type", "model")

            for dep_fqn in depends_on_fqns:
                dep_asset = fqn_to_asset.get(dep_fqn)
                if not dep_asset:
                    counts["skipped_unresolved"] += 1
                    continue

                # Determine dependency type: if this asset is a model and the
                # dep is also a model, it's TRANSFORMS. Otherwise CONSUMES.
                dep_resource_type = (dep_asset.metadata_ or {}).get("resource_type", "")
                if resource_type == "model" and dep_resource_type == "model":
                    dep_type = DependencyType.TRANSFORMS
                else:
                    dep_type = DependencyType.CONSUMES

                edge_key = (str(asset.id), str(dep_asset.id), dep_type)
                if edge_key in existing_edges:
                    counts["skipped_exists"] += 1
                    continue

                session.add(
                    AssetDependencyDB(
                        dependent_asset_id=asset.id,
                        dependency_asset_id=dep_asset.id,
                        dependency_type=dep_type,
                    )
                )
                existing_edges.add(edge_key)
                counts["created"] += 1

        await session.commit()

    return counts


@app.command("backfill-dependencies")
def backfill_dependencies(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be created without writing")
    ] = False,
) -> None:
    """Backfill AssetDependencyDB rows from existing metadata.depends_on.

    One-time migration to populate the dependency table from dbt-synced
    metadata. Safe to re-run (idempotent).
    """
    if dry_run:
        console.print("[yellow]Dry run mode — no changes will be written[/yellow]")
        # For dry run, we'd need a separate path that doesn't commit.
        # For simplicity, just run the real thing — it's idempotent.
        console.print("[dim]Dry run not yet implemented. Run without --dry-run.[/dim]")
        return

    counts = asyncio.run(_run_backfill())

    console.print(f"[green]Created:[/green] {counts['created']} dependency rows")
    console.print(f"[dim]Skipped (already exist):[/dim] {counts['skipped_exists']}")
    console.print(f"[dim]Skipped (unresolved FQN):[/dim] {counts['skipped_unresolved']}")
