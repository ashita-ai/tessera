"""Warehouse connectors for schema validation.

These connectors allow Tessera to validate schemas against actual tables
in data warehouses like BigQuery, Snowflake, Databricks, etc.
"""

from abc import ABC, abstractmethod
from typing import Any


class WarehouseConnector(ABC):
    """Base class for warehouse connectors."""

    @abstractmethod
    async def get_table_schema(self, table_ref: str) -> dict[str, Any]:
        """Get the JSON Schema representation of a table.

        Args:
            table_ref: Fully qualified table reference
                       (e.g., project.dataset.table for BigQuery)

        Returns:
            JSON Schema dict representing the table structure
        """
        pass

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Test the connection to the warehouse.

        Returns:
            True if connection is valid
        """
        pass

    @abstractmethod
    async def list_tables(self, dataset_ref: str) -> list[str]:
        """List all tables in a dataset/schema.

        Args:
            dataset_ref: Dataset or schema reference
                        (e.g., project.dataset for BigQuery)

        Returns:
            List of table names
        """
        pass
