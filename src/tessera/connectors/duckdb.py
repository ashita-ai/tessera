"""DuckDB connector for local schema validation.

This connector allows Tessera to fetch table schemas from DuckDB
for validation against registered contracts. Useful for:
- Local development and testing
- CI/CD pipelines without cloud credentials
- Validating Parquet/CSV files as "staging tables"
"""

import logging
from pathlib import Path
from typing import Any

from tessera.connectors import WarehouseConnector

logger = logging.getLogger(__name__)

# DuckDB type to JSON Schema type mapping
DUCKDB_TYPE_MAPPING = {
    # Integer types
    "TINYINT": "integer",
    "SMALLINT": "integer",
    "INTEGER": "integer",
    "BIGINT": "integer",
    "HUGEINT": "integer",
    "UTINYINT": "integer",
    "USMALLINT": "integer",
    "UINTEGER": "integer",
    "UBIGINT": "integer",
    "INT": "integer",
    "INT1": "integer",
    "INT2": "integer",
    "INT4": "integer",
    "INT8": "integer",
    # Float types
    "FLOAT": "number",
    "DOUBLE": "number",
    "REAL": "number",
    "DECIMAL": "number",
    "NUMERIC": "number",
    # String types
    "VARCHAR": "string",
    "CHAR": "string",
    "BPCHAR": "string",
    "TEXT": "string",
    "STRING": "string",
    "BLOB": "string",
    "BYTEA": "string",
    # Boolean
    "BOOLEAN": "boolean",
    "BOOL": "boolean",
    # Date/time types
    "DATE": "string",
    "TIME": "string",
    "TIMESTAMP": "string",
    "TIMESTAMPTZ": "string",
    "TIMESTAMP WITH TIME ZONE": "string",
    "INTERVAL": "string",
    # Complex types
    "JSON": "object",
    "MAP": "object",
    "STRUCT": "object",
    "LIST": "array",
    "ARRAY": "array",
    # UUID
    "UUID": "string",
}


def _normalize_duckdb_type(type_str: str) -> tuple[str, str | None]:
    """Normalize DuckDB type string to base type and format.

    Returns:
        Tuple of (json_type, format_hint)
    """
    type_upper = type_str.upper().strip()

    # Handle parameterized types like VARCHAR(255), DECIMAL(10,2)
    base_type = type_upper.split("(")[0].strip()

    # Handle array types like INTEGER[]
    if type_upper.endswith("[]"):
        return "array", None

    json_type = DUCKDB_TYPE_MAPPING.get(base_type, "string")

    # Add format hints
    format_hint = None
    if base_type == "DATE":
        format_hint = "date"
    elif base_type in ("TIMESTAMP", "TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"):
        format_hint = "date-time"
    elif base_type == "TIME":
        format_hint = "time"
    elif base_type == "UUID":
        format_hint = "uuid"

    return json_type, format_hint


class DuckDBConnector(WarehouseConnector):
    """DuckDB connector for fetching table schemas from local files.

    Usage:
        from tessera.connectors.duckdb import DuckDBConnector

        connector = DuckDBConnector()

        # From Parquet file
        schema = await connector.get_table_schema("examples/data/customers.parquet")

        # From CSV file
        schema = await connector.get_table_schema("examples/data/orders.csv")

        # From in-memory table
        connector.execute("CREATE TABLE users (id INT, name VARCHAR)")
        schema = await connector.get_table_schema("users")
    """

    def __init__(self, database: str = ":memory:"):
        """Initialize DuckDB connector.

        Args:
            database: Path to database file or ":memory:" for in-memory
        """
        self._database = database
        self._conn: Any = None

    def _get_connection(self) -> Any:
        """Get or create DuckDB connection."""
        if self._conn is None:
            try:
                import duckdb
            except ImportError:
                raise ImportError(
                    "DuckDB connector requires duckdb. Install with: pip install duckdb"
                )
            self._conn = duckdb.connect(self._database)
        return self._conn

    def execute(self, sql: str) -> Any:
        """Execute SQL statement.

        Args:
            sql: SQL statement to execute

        Returns:
            Query result
        """
        conn = self._get_connection()
        return conn.execute(sql)

    async def validate_connection(self) -> bool:
        """Test the connection to DuckDB."""
        try:
            conn = self._get_connection()
            conn.execute("SELECT 1").fetchone()
            return True
        except Exception as e:
            logger.error(f"DuckDB connection failed: {e}")
            return False

    async def get_table_schema(self, table_ref: str) -> dict[str, Any]:
        """Get JSON Schema representation of a table or file.

        Args:
            table_ref: Table name, or path to Parquet/CSV file

        Returns:
            JSON Schema dict

        Example:
            # From file
            schema = await connector.get_table_schema("data/customers.parquet")

            # From table
            schema = await connector.get_table_schema("my_table")
        """
        conn = self._get_connection()

        # Determine if this is a file path or table name
        path = Path(table_ref)
        if path.suffix.lower() in (".parquet", ".csv", ".json"):
            # It's a file - create a temporary view
            if path.suffix.lower() == ".parquet":
                query = f"SELECT * FROM read_parquet('{table_ref}') LIMIT 0"
            elif path.suffix.lower() == ".csv":
                query = f"SELECT * FROM read_csv_auto('{table_ref}') LIMIT 0"
            else:
                query = f"SELECT * FROM read_json_auto('{table_ref}') LIMIT 0"

            # Get schema by describing the query
            result = conn.execute(f"DESCRIBE {query}").fetchall()
        else:
            # It's a table name
            result = conn.execute(f"DESCRIBE {table_ref}").fetchall()

        # Build JSON Schema from column definitions
        properties: dict[str, Any] = {}
        required: list[str] = []

        for row in result:
            col_name = row[0]
            col_type = row[1]
            nullable = row[2] == "YES" if len(row) > 2 else True

            json_type, format_hint = _normalize_duckdb_type(col_type)

            prop: dict[str, Any] = {"type": json_type}
            if format_hint:
                prop["format"] = format_hint

            # Handle array types
            if col_type.upper().endswith("[]"):
                inner_type = col_type[:-2]
                inner_json_type, _ = _normalize_duckdb_type(inner_type)
                prop = {"type": "array", "items": {"type": inner_json_type}}

            properties[col_name] = prop

            if not nullable:
                required.append(col_name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        schema["$comment"] = f"Schema for {table_ref}"

        return schema

    async def list_tables(self, schema_name: str = "main") -> list[str]:
        """List all tables in a schema.

        Args:
            schema_name: Schema name (default: main)

        Returns:
            List of table names
        """
        conn = self._get_connection()
        result = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?", [schema_name]
        ).fetchall()
        return [row[0] for row in result]

    async def compare_with_contract(
        self,
        table_ref: str,
        contract_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare a table/file schema with a contract schema.

        Args:
            table_ref: Table name or file path
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


async def validate_local_file(
    file_path: str,
    contract_schema: dict[str, Any],
) -> dict[str, Any]:
    """Convenience function to validate a local file against a contract.

    Args:
        file_path: Path to Parquet/CSV file
        contract_schema: The expected JSON Schema from the contract

    Returns:
        Validation result

    Example:
        result = await validate_local_file(
            file_path="staging/customers.parquet",
            contract_schema={"type": "object", "properties": {...}},
        )
        if result["is_compatible"]:
            print("File matches contract!")
    """
    connector = DuckDBConnector()
    return await connector.compare_with_contract(file_path, contract_schema)
