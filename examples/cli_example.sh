#!/bin/bash
# Tessera CLI Examples
# ====================
# Demonstrates using the Tessera CLI for data contract management.
#
# Prerequisites:
#   1. Start the server: tessera serve
#   2. Or use Docker: docker compose up -d
#
# Run this script: chmod +x examples/cli_example.sh && ./examples/cli_example.sh

set -e

echo "======================================"
echo "  TESSERA CLI EXAMPLES"
echo "======================================"
echo

# Check if server is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "Error: Tessera server not running."
    echo "Start it with: tessera serve"
    exit 1
fi

echo "Step 1: Create Teams"
echo "--------------------"
PRODUCER_OUTPUT=$(tessera team create "data-platform" 2>/dev/null || true)
if echo "$PRODUCER_OUTPUT" | grep -q "Created team"; then
    echo "$PRODUCER_OUTPUT"
else
    echo "Team 'data-platform' already exists"
fi

CONSUMER_OUTPUT=$(tessera team create "analytics-team" 2>/dev/null || true)
if echo "$CONSUMER_OUTPUT" | grep -q "Created team"; then
    echo "$CONSUMER_OUTPUT"
else
    echo "Team 'analytics-team' already exists"
fi

echo
echo "Step 2: List Teams"
echo "------------------"
tessera team list

# Get team IDs for subsequent commands
PRODUCER_ID=$(tessera team list 2>/dev/null | grep "data-platform" | awk '{print $2}' | head -1)
CONSUMER_ID=$(tessera team list 2>/dev/null | grep "analytics-team" | awk '{print $2}' | head -1)

echo
echo "Step 3: Create an Asset"
echo "-----------------------"
ASSET_OUTPUT=$(tessera asset create "warehouse.analytics.orders" --team "$PRODUCER_ID" 2>/dev/null || true)
if echo "$ASSET_OUTPUT" | grep -q "Created asset"; then
    echo "$ASSET_OUTPUT"
else
    echo "Asset 'warehouse.analytics.orders' already exists"
fi

echo
echo "Step 4: Search Assets"
echo "---------------------"
tessera asset search "orders"

# Get asset ID
ASSET_ID=$(tessera asset search "orders" 2>/dev/null | grep "orders" | awk '{print $2}' | head -1)

echo
echo "Step 5: Publish a Contract"
echo "--------------------------"

# Create a schema file
cat > /tmp/orders_schema_v1.json << 'EOF'
{
    "type": "object",
    "properties": {
        "order_id": {"type": "integer"},
        "customer_id": {"type": "integer"},
        "total_amount": {"type": "number"},
        "status": {"type": "string", "enum": ["pending", "shipped", "delivered"]},
        "created_at": {"type": "string", "format": "date-time"}
    },
    "required": ["order_id", "customer_id", "total_amount"]
}
EOF

tessera contract publish \
    --asset "$ASSET_ID" \
    --version "1.0.0" \
    --schema /tmp/orders_schema_v1.json \
    --team "$PRODUCER_ID" \
    --compat backward 2>/dev/null || echo "Contract v1.0.0 may already exist"

echo
echo "Step 6: List Contracts"
echo "----------------------"
tessera contract list "$ASSET_ID"

echo
echo "Step 7: Register as Consumer"
echo "----------------------------"
tessera register --asset "$ASSET_ID" --team "$CONSUMER_ID" 2>/dev/null || echo "Already registered"

echo
echo "Step 8: Check Impact of Proposed Change"
echo "---------------------------------------"

# Create a breaking schema (removes 'status' field)
cat > /tmp/orders_schema_breaking.json << 'EOF'
{
    "type": "object",
    "properties": {
        "order_id": {"type": "integer"},
        "customer_id": {"type": "integer"},
        "total_amount": {"type": "number"},
        "created_at": {"type": "string", "format": "date-time"}
    },
    "required": ["order_id", "customer_id", "total_amount"]
}
EOF

tessera contract impact "$ASSET_ID" --schema /tmp/orders_schema_breaking.json

echo
echo "Step 9: Publish Compatible Change (Auto-publishes)"
echo "---------------------------------------------------"

# Create a compatible schema (adds optional field)
cat > /tmp/orders_schema_v1_1.json << 'EOF'
{
    "type": "object",
    "properties": {
        "order_id": {"type": "integer"},
        "customer_id": {"type": "integer"},
        "total_amount": {"type": "number"},
        "status": {"type": "string", "enum": ["pending", "shipped", "delivered"]},
        "created_at": {"type": "string", "format": "date-time"},
        "shipping_address": {"type": "string"}
    },
    "required": ["order_id", "customer_id", "total_amount"]
}
EOF

tessera contract publish \
    --asset "$ASSET_ID" \
    --version "1.1.0" \
    --schema /tmp/orders_schema_v1_1.json \
    --team "$PRODUCER_ID" \
    --compat backward 2>/dev/null || echo "Contract v1.1.0 may already exist"

echo
echo "Step 10: View Contract Diff"
echo "---------------------------"
tessera contract diff "$ASSET_ID" --from "1.0.0" --to "1.1.0" 2>/dev/null || echo "Diff not available"

echo
echo "Step 11: List Proposals"
echo "-----------------------"
tessera proposal list

echo
echo "======================================"
echo "  CLI EXAMPLES COMPLETE"
echo "======================================"

# Cleanup
rm -f /tmp/orders_schema_*.json
