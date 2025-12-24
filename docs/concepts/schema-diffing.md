# Schema Diffing

Tessera automatically compares schemas to detect breaking vs non-breaking changes.

## How It Works

When you publish a new contract, Tessera:

1. Fetches the current active contract
2. Compares the schemas using JSON Schema rules
3. Classifies each change as breaking or non-breaking
4. Creates a proposal if any breaking changes are detected

## Change Types

### Property Changes

| Change | Backward | Forward |
|--------|----------|---------|
| Add optional property | Safe | Breaking |
| Add required property | Breaking | Safe |
| Remove property | Breaking | Safe |
| Rename property | Breaking | Breaking |

### Type Changes

| Change | Backward | Forward |
|--------|----------|---------|
| Widen type (int → number) | Safe | Breaking |
| Narrow type (number → int) | Breaking | Safe |
| Change type (string → int) | Breaking | Breaking |

### Required Changes

| Change | Backward | Forward |
|--------|----------|---------|
| Make optional → required | Breaking | Safe |
| Make required → optional | Safe | Breaking |

### Enum Changes

| Change | Backward | Forward |
|--------|----------|---------|
| Add enum value | Safe | Breaking |
| Remove enum value | Breaking | Safe |

## Examples

### Safe Change (Backward Compatible)

```json
// Before
{
  "properties": {
    "id": {"type": "integer"},
    "name": {"type": "string"}
  }
}

// After - adding optional field
{
  "properties": {
    "id": {"type": "integer"},
    "name": {"type": "string"},
    "email": {"type": "string"}  // New optional field
  }
}
```

Result: Auto-published as minor version bump.

### Breaking Change

```json
// Before
{
  "properties": {
    "id": {"type": "integer"},
    "name": {"type": "string"},
    "email": {"type": "string"}
  },
  "required": ["id", "name", "email"]
}

// After - removing required field
{
  "properties": {
    "id": {"type": "integer"},
    "name": {"type": "string"}
  },
  "required": ["id", "name"]
}
```

Result: Proposal created, consumers must acknowledge.

## Compatibility Modes

### Backward (Default)

Consumers using the old schema can read new data.

**Breaking changes:**
- Remove property
- Add required property
- Narrow type
- Remove enum value

### Forward

Producers using the old schema produce valid new data.

**Breaking changes:**
- Add property (even optional)
- Widen type
- Add enum value

### Full

Both backward and forward compatible.

**Breaking changes:**
- Any schema change

### None

No compatibility checking - all changes are non-breaking.

## API Response

When publishing, the response indicates what happened:

```json
{
  "action": "published",
  "contract": { ... },
  "changes": []
}
```

Or for breaking changes:

```json
{
  "action": "proposal_created",
  "proposal": {
    "id": "proposal-uuid",
    "breaking_changes": [
      {
        "path": "$.properties.email",
        "type": "property_removed",
        "description": "Property 'email' was removed"
      }
    ]
  }
}
```
