#!/bin/bash
set -e

# Wait for the API to be ready
echo "Waiting for API to be ready..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "API is ready!"
        break
    fi
    attempt=$((attempt + 1))
    echo "Attempt $attempt/$max_attempts - API not ready yet..."
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    echo "Warning: API did not become ready, continuing anyway..."
fi

# Import dbt manifest if it exists
if [ -f /app/examples/data/manifest.json ]; then
    echo "Importing dbt manifest..."

    # First create the default team if it doesn't exist
    TEAM_RESP=$(curl -s -X POST http://localhost:8000/api/v1/teams \
        -H "Content-Type: application/json" \
        -d '{"name": "data-platform"}' 2>/dev/null || echo '{}')

    TEAM_ID=$(echo "$TEAM_RESP" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('id', ''))" 2>/dev/null || echo "")

    if [ -z "$TEAM_ID" ]; then
        # Team might already exist, get it
        TEAM_ID=$(curl -s http://localhost:8000/api/v1/teams?name=data-platform | \
            python3 -c "import sys, json; d=json.load(sys.stdin); r=d.get('results',[]); print(r[0]['id'] if r else '')" 2>/dev/null || echo "")
    fi

    if [ -n "$TEAM_ID" ]; then
        echo "Using team ID: $TEAM_ID"

        # Import the manifest using the sync API
        SYNC_RESP=$(curl -s -X POST "http://localhost:8000/api/v1/sync/dbt?team_id=$TEAM_ID" \
            -H "Content-Type: application/json" \
            -d @/app/examples/data/manifest.json 2>/dev/null || echo '{}')

        echo "Sync response: $SYNC_RESP"
        echo "dbt manifest import complete!"
    else
        echo "Warning: Could not find or create team, skipping manifest import"
    fi
else
    echo "No manifest.json found, skipping import"
fi

echo "Startup complete!"
