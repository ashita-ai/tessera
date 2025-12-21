"""BigQuery connector for schema validation.

This connector allows Tessera to fetch table schemas directly from BigQuery
for validation against registered contracts.

Install with: pip install tessera[bigquery]
"""

import logging
from typing import Any

from tessera.connectors import WarehouseConnector

logger = logging.getLogger(__name__)

# BigQuery type to JSON Schema type mapping
BQ_TYPE_MAPPING = {
    # Numeric types
    "INT64": "integer",
    "INTEGER": "integer",
    "SMALLINT": "integer",
    "INT": "integer",
    "BIGINT": "integer",
    "TINYINT": "integer",
    "BYTEINT": "integer",
    "FLOAT64": "number",
    "FLOAT": "number",
    "NUMERIC": "number",
    "BIGNUMERIC": "number",
    "DECIMAL": "number",
    # String types
    "STRING": "string",
    "BYTES": "string",
    # Boolean
    "BOOL": "boolean",
    "BOOLEAN": "boolean",
    # Date/time types
    "DATE": "string",
    "DATETIME": "string",
    "TIME": "string",
    "TIMESTAMP": "string",
    # Complex types
    "GEOGRAPHY": "object",
    "JSON": "object",
    "STRUCT": "object",
    "RECORD": "object",
    "ARRAY": "array",
}


def _bq_field_to_json_schema(field: Any) -> dict[str, Any]:
    """Convert a BigQuery SchemaField to JSON Schema property.

    Args:
        field: BigQuery SchemaField object

    Returns:
        JSON Schema property definition
    """
    field_type = field.field_type.upper()
    mode = field.mode.upper() if field.mode else "NULLABLE"

    # Handle RECORD/STRUCT types (nested fields)
    if field_type in ("RECORD", "STRUCT"):
        properties = {}
        required = []
        for subfield in field.fields or []:
            properties[subfield.name] = _bq_field_to_json_schema(subfield)
            if subfield.mode and subfield.mode.upper() == "REQUIRED":
                required.append(subfield.name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        # Handle REPEATED RECORD
        if mode == "REPEATED":
            return {"type": "array", "items": schema}
        return schema

    # Handle ARRAY types
    if mode == "REPEATED":
        json_type = BQ_TYPE_MAPPING.get(field_type, "string")
        return {
            "type": "array",
            "items": {"type": json_type},
        }

    # Simple types
    json_type = BQ_TYPE_MAPPING.get(field_type, "string")
    prop: dict[str, Any] = {"type": json_type}

    # Add format hints for date/time types
    if field_type == "DATE":
        prop["format"] = "date"
    elif field_type == "DATETIME":
        prop["format"] = "date-time"
    elif field_type == "TIME":
        prop["format"] = "time"
    elif field_type == "TIMESTAMP":
        prop["format"] = "date-time"

    # Add description if available
    if field.description:
        prop["description"] = field.description

    return prop


class BigQueryConnector(WarehouseConnector):
    """BigQuery connector for fetching table schemas.

    Usage:
        from tessera.connectors.bigquery import BigQueryConnector

        connector = BigQueryConnector(project="my-project")
        schema = await connector.get_table_schema("my-project.raw.all_crypto_history")
    """

    def __init__(
        self,
        project: str | None = None,
        credentials: Any = None,
        location: str = "US",
    ):
        """Initialize BigQuery connector.

        Args:
            project: Default GCP project ID
            credentials: GCP credentials (uses ADC if not provided)
            location: Default BigQuery location
        """
        self._project = project
        self._credentials = credentials
        self._location = location
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create BigQuery client."""
        if self._client is None:
            try:
                from google.cloud import bigquery
            except ImportError:
                raise ImportError(
                    "BigQuery connector requires google-cloud-bigquery. "
                    "Install with: pip install tessera[bigquery]"
                )

            self._client = bigquery.Client(
                project=self._project,
                credentials=self._credentials,
                location=self._location,
            )
        return self._client

    async def validate_connection(self) -> bool:
        """Test the connection to BigQuery."""
        try:
            client = self._get_client()
            # Simple query to test connection
            list(client.query("SELECT 1").result())
            return True
        except Exception as e:
            logger.error(f"BigQuery connection failed: {e}")
            return False

    async def get_table_schema(self, table_ref: str) -> dict[str, Any]:
        """Get JSON Schema representation of a BigQuery table.

        Args:
            table_ref: Fully qualified table reference (project.dataset.table)

        Returns:
            JSON Schema dict

        Example:
            schema = await connector.get_table_schema("new-life-400922.raw.all_crypto_history")
        """
        client = self._get_client()

        # Parse table reference
        parts = table_ref.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid table reference: {table_ref}. Expected format: project.dataset.table"
            )

        project, dataset, table = parts

        # Get table metadata
        table_id = f"{project}.{dataset}.{table}"
        bq_table = client.get_table(table_id)

        # Convert schema to JSON Schema
        properties = {}
        required = []

        for field in bq_table.schema:
            properties[field.name] = _bq_field_to_json_schema(field)
            if field.mode and field.mode.upper() == "REQUIRED":
                required.append(field.name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        # Add metadata
        schema["$comment"] = f"Schema for {table_ref}"
        if bq_table.description:
            schema["description"] = bq_table.description

        return schema

    async def list_tables(self, dataset_ref: str) -> list[str]:
        """List all tables in a dataset.

        Args:
            dataset_ref: Dataset reference (project.dataset)

        Returns:
            List of table names
        """
        client = self._get_client()

        parts = dataset_ref.split(".")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid dataset reference: {dataset_ref}. Expected format: project.dataset"
            )

        project, dataset = parts
        dataset_id = f"{project}.{dataset}"

        tables = client.list_tables(dataset_id)
        return [table.table_id for table in tables]

    async def compare_with_contract(
        self,
        table_ref: str,
        contract_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare a BigQuery table schema with a contract schema.

        Args:
            table_ref: Fully qualified table reference
            contract_schema: JSON Schema from the contract

        Returns:
            Comparison result with any differences
        """
        from tessera.models.enums import CompatibilityMode
        from tessera.services.schema_diff import check_compatibility

        table_schema = await self.get_table_schema(table_ref)

        is_compatible, breaking_changes = check_compatibility(
            old_schema=contract_schema,
            new_schema=table_schema,
            mode=CompatibilityMode.BACKWARD,
        )

        return {
            "table_ref": table_ref,
            "is_compatible": is_compatible,
            "breaking_changes": [
                {
                    "kind": bc.kind.value,
                    "path": bc.path,
                    "message": bc.message,
                }
                for bc in breaking_changes
            ],
            "table_schema": table_schema,
        }


async def validate_staging_table(
    staging_ref: str,
    contract_schema: dict[str, Any],
    project: str | None = None,
) -> dict[str, Any]:
    """Convenience function to validate a staging table against a contract.

    Args:
        staging_ref: Staging table reference (project.dataset.table)
        contract_schema: The expected JSON Schema from the contract
        project: GCP project (uses default if not specified)

    Returns:
        Validation result

    Example:
        result = await validate_staging_table(
            staging_ref="my-project.staging.users",
            contract_schema={"type": "object", "properties": {...}},
        )
        if result["is_compatible"]:
            print("Staging table matches contract!")
    """
    connector = BigQueryConnector(project=project)
    return await connector.compare_with_contract(staging_ref, contract_schema)
