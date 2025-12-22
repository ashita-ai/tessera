"""Generate sample Parquet files for testing staging table validation.

Run with: uv run python examples/data/generate_sample_data.py
"""

import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, date
from pathlib import Path

DATA_DIR = Path(__file__).parent


def generate_customers_v1():
    """Generate customers table matching the v1.0.0 contract."""
    data = {
        "customer_id": [1, 2, 3, 4, 5],
        "email": [
            "alice@example.com",
            "bob@example.com",
            "charlie@example.com",
            "diana@example.com",
            "eve@example.com",
        ],
        "name": ["Alice Smith", "Bob Jones", "Charlie Brown", "Diana Ross", "Eve Wilson"],
        "created_at": [
            datetime(2024, 1, 15, 10, 30, 0),
            datetime(2024, 2, 20, 14, 45, 0),
            datetime(2024, 3, 10, 9, 0, 0),
            datetime(2024, 4, 5, 16, 20, 0),
            datetime(2024, 5, 1, 11, 15, 0),
        ],
    }

    table = pa.table(data)
    pq.write_table(table, DATA_DIR / "customers_v1.parquet")
    print(f"Generated customers_v1.parquet with {len(data['customer_id'])} rows")


def generate_customers_v2_compatible():
    """Generate customers with backward-compatible changes (new optional field)."""
    data = {
        "customer_id": [1, 2, 3, 4, 5],
        "email": [
            "alice@example.com",
            "bob@example.com",
            "charlie@example.com",
            "diana@example.com",
            "eve@example.com",
        ],
        "name": ["Alice Smith", "Bob Jones", "Charlie Brown", "Diana Ross", "Eve Wilson"],
        "created_at": [
            datetime(2024, 1, 15, 10, 30, 0),
            datetime(2024, 2, 20, 14, 45, 0),
            datetime(2024, 3, 10, 9, 0, 0),
            datetime(2024, 4, 5, 16, 20, 0),
            datetime(2024, 5, 1, 11, 15, 0),
        ],
        # New optional field - backward compatible
        "loyalty_tier": ["gold", "silver", "bronze", "platinum", "silver"],
    }

    table = pa.table(data)
    pq.write_table(table, DATA_DIR / "customers_v2_compatible.parquet")
    print(f"Generated customers_v2_compatible.parquet with {len(data['customer_id'])} rows")


def generate_customers_v2_breaking():
    """Generate customers with breaking changes (removed email, changed types)."""
    data = {
        "customer_id": ["C001", "C002", "C003", "C004", "C005"],  # Changed from int to string!
        # email removed - breaking change!
        "full_name": [
            "Alice Smith",
            "Bob Jones",
            "Charlie Brown",
            "Diana Ross",
            "Eve Wilson",
        ],  # renamed
        "created_at": [
            datetime(2024, 1, 15, 10, 30, 0),
            datetime(2024, 2, 20, 14, 45, 0),
            datetime(2024, 3, 10, 9, 0, 0),
            datetime(2024, 4, 5, 16, 20, 0),
            datetime(2024, 5, 1, 11, 15, 0),
        ],
    }

    table = pa.table(data)
    pq.write_table(table, DATA_DIR / "customers_v2_breaking.parquet")
    print(f"Generated customers_v2_breaking.parquet with {len(data['customer_id'])} rows")


def generate_orders():
    """Generate orders table."""
    data = {
        "order_id": [101, 102, 103, 104, 105, 106, 107, 108],
        "customer_id": [1, 2, 1, 3, 4, 2, 5, 1],
        "order_total": [99.99, 149.50, 25.00, 350.00, 75.25, 199.99, 45.00, 599.99],
        "order_date": [
            date(2024, 6, 1),
            date(2024, 6, 2),
            date(2024, 6, 3),
            date(2024, 6, 5),
            date(2024, 6, 7),
            date(2024, 6, 10),
            date(2024, 6, 12),
            date(2024, 6, 15),
        ],
        "status": [
            "shipped",
            "delivered",
            "delivered",
            "processing",
            "shipped",
            "delivered",
            "shipped",
            "processing",
        ],
    }

    table = pa.table(data)
    pq.write_table(table, DATA_DIR / "orders.parquet")
    print(f"Generated orders.parquet with {len(data['order_id'])} rows")


def main():
    """Generate all sample data files."""
    print("Generating sample Parquet files...")
    print()

    generate_customers_v1()
    generate_customers_v2_compatible()
    generate_customers_v2_breaking()
    generate_orders()

    print()
    print("Done! Files created in examples/data/")


if __name__ == "__main__":
    main()
