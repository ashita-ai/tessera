"""
Authentication Examples
=======================

Demonstrates how to use Tessera's API key authentication system.

Tessera supports two authentication methods:
1. Bootstrap API Key - For initial setup (set via BOOTSTRAP_API_KEY env var)
2. Team API Keys - For team-specific access with scoped permissions

Run with: uv run python examples/auth_example.py
"""

import httpx

BASE_URL = "http://localhost:8000/api/v1"


def example_1_bootstrap_key():
    """
    EXAMPLE 1: Using the Bootstrap API Key
    --------------------------------------
    The bootstrap key is set via environment variable and provides
    full admin access for initial setup.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Using the Bootstrap API Key")
    print("=" * 70)

    # The bootstrap key is configured in docker-compose.yml or .env
    # BOOTSTRAP_API_KEY=tessera-dev-key
    bootstrap_key = "tessera-dev-key"

    with httpx.Client() as client:
        # Use bootstrap key to create initial team
        resp = client.post(
            f"{BASE_URL}/teams",
            json={"name": "platform-team", "metadata": {"department": "engineering"}},
            headers={"Authorization": f"Bearer {bootstrap_key}"},
        )

        if resp.status_code == 201:
            team = resp.json()
            print(f"\nCreated team: {team['name']} ({team['id']})")
        elif resp.status_code == 400:
            print("\nTeam already exists (expected on re-run)")
            # Get existing team
            resp = client.get(
                f"{BASE_URL}/teams",
                headers={"Authorization": f"Bearer {bootstrap_key}"},
            )
            teams = resp.json().get("results", [])
            team = next((t for t in teams if t["name"] == "platform-team"), None)
            if team:
                print(f"Found existing team: {team['name']} ({team['id']})")

        print("""
The bootstrap key should only be used for initial setup:
- Creating the first team
- Creating the first admin API key

After setup, use team-specific API keys with limited scopes.
""")


def example_2_create_api_key():
    """
    EXAMPLE 2: Creating Team API Keys
    ---------------------------------
    Create API keys with specific scopes for team members.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Creating Team API Keys")
    print("=" * 70)

    bootstrap_key = "tessera-dev-key"

    with httpx.Client() as client:
        # First get a team
        resp = client.get(
            f"{BASE_URL}/teams",
            headers={"Authorization": f"Bearer {bootstrap_key}"},
        )
        teams = resp.json().get("results", [])

        if not teams:
            print("\nNo teams found. Run example 1 first.")
            return None

        team = teams[0]
        print(f"\nCreating API key for team: {team['name']}")

        # Create an API key with specific scopes
        resp = client.post(
            f"{BASE_URL}/teams/{team['id']}/api-keys",
            json={
                "name": "ci-cd-key",
                "scopes": ["read", "write"],  # No admin access
                "expires_in_days": 90,  # Optional: key expires in 90 days
            },
            headers={"Authorization": f"Bearer {bootstrap_key}"},
        )

        if resp.status_code == 201:
            key_response = resp.json()
            print(f"""
API Key created successfully!

    Key ID: {key_response.get('id', 'N/A')}
    Name: {key_response.get('name', 'ci-cd-key')}
    Scopes: {key_response.get('scopes', ['read', 'write'])}

    IMPORTANT: Save this key securely!
    Key: {key_response.get('key', '<key shown once>')}

This key can now be used for read/write operations but cannot:
- Create or delete teams
- Create other API keys
- Access other teams' resources
""")
            return key_response.get("key")
        else:
            print(f"\nFailed to create API key: {resp.text}")
            print("(This endpoint may not be implemented yet)")
            return None


def example_3_scoped_access():
    """
    EXAMPLE 3: Using Scoped API Keys
    --------------------------------
    Demonstrates how different scopes limit what operations are allowed.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Using Scoped API Keys")
    print("=" * 70)

    print("""
Available scopes:

    read    - View teams, assets, contracts, registrations
    write   - Create/update assets, publish contracts, create registrations
    admin   - All operations including team management and API key creation

Example: A CI/CD pipeline key should have 'read' and 'write' scopes:

    # Check impact of changes (read)
    curl -X POST "$TESSERA_URL/api/v1/assets/{id}/impact" \\
        -H "Authorization: Bearer $CI_API_KEY" \\
        -H "Content-Type: application/json" \\
        -d '{"type": "object", "properties": {...}}'

    # Publish a contract (write)
    curl -X POST "$TESSERA_URL/api/v1/assets/{id}/contracts" \\
        -H "Authorization: Bearer $CI_API_KEY" \\
        -H "Content-Type: application/json" \\
        -d '{"version": "1.0.0", "schema": {...}}'

    # This would FAIL with 403 Forbidden (requires admin):
    curl -X POST "$TESSERA_URL/api/v1/teams" \\
        -H "Authorization: Bearer $CI_API_KEY" \\
        -H "Content-Type: application/json" \\
        -d '{"name": "new-team"}'
""")


def example_4_environment_variables():
    """
    EXAMPLE 4: Configuring Auth via Environment Variables
    -----------------------------------------------------
    Best practices for configuring authentication in different environments.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Environment Variable Configuration")
    print("=" * 70)

    print("""
For Development (docker-compose.yml):

    environment:
      BOOTSTRAP_API_KEY: tessera-dev-key  # Simple dev key

For Production:

    # Generate a strong random key
    BOOTSTRAP_API_KEY=$(openssl rand -base64 32)

    # Or use a secrets manager
    BOOTSTRAP_API_KEY=${VAULT_TESSERA_BOOTSTRAP_KEY}

For CI/CD Pipelines (GitHub Actions):

    env:
      TESSERA_API_KEY: ${{ secrets.TESSERA_API_KEY }}
      TESSERA_URL: ${{ vars.TESSERA_URL }}

Using the Python SDK with auth:

    from tessera_sdk import TesseraClient
    import os

    client = TesseraClient(
        base_url=os.environ["TESSERA_URL"],
        headers={"Authorization": f"Bearer {os.environ['TESSERA_API_KEY']}"}
    )

Using the CLI with auth:

    export TESSERA_URL=https://tessera.example.com
    export TESSERA_API_KEY=tsr_abc123...

    tessera team list
    tessera contract list --asset users
""")


def example_5_key_rotation():
    """
    EXAMPLE 5: API Key Rotation
    ---------------------------
    Best practices for rotating API keys without downtime.
    """
    print("\n" + "=" * 70)
    print("EXAMPLE 5: API Key Rotation")
    print("=" * 70)

    print("""
To rotate an API key without downtime:

1. Create a new key with the same scopes:

    curl -X POST "$TESSERA_URL/api/v1/teams/{team_id}/api-keys" \\
        -H "Authorization: Bearer $OLD_KEY" \\
        -d '{"name": "ci-cd-key-v2", "scopes": ["read", "write"]}'

2. Update your secrets manager / CI/CD with the new key

3. Verify the new key works:

    curl "$TESSERA_URL/api/v1/teams" \\
        -H "Authorization: Bearer $NEW_KEY"

4. Revoke the old key:

    curl -X DELETE "$TESSERA_URL/api/v1/api-keys/{old_key_id}" \\
        -H "Authorization: Bearer $NEW_KEY"

Recommended rotation schedule:
    - Development keys: Every 90 days
    - CI/CD keys: Every 90 days
    - Service account keys: Every 180 days
    - Bootstrap key: Immediately after initial setup (create admin API key, then unset)
""")


def main():
    """Run all authentication examples."""
    print("\n" + "=" * 70)
    print("  TESSERA AUTHENTICATION EXAMPLES")
    print("=" * 70)

    try:
        # Check server is running
        with httpx.Client() as client:
            client.get(f"{BASE_URL.replace('/api/v1', '')}/health")
    except httpx.ConnectError:
        print("\nServer not running. Start it with: docker compose up -d")
        return

    example_1_bootstrap_key()
    example_2_create_api_key()
    example_3_scoped_access()
    example_4_environment_variables()
    example_5_key_rotation()

    print("\n" + "=" * 70)
    print("Authentication examples complete!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
