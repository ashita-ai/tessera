# ADR-006: Multi-Format Schema Normalization to JSON Schema

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Real data ecosystems are polyglot. A single organization might have dbt models (JSON Schema from manifests), REST APIs (OpenAPI), event streams (Avro/Protobuf), and GraphQL services. A coordination tool that only supports one schema format forces teams to maintain parallel representations or ignores parts of the ecosystem entirely.

The alternative — writing separate diff engines for each format — creates an N×M complexity problem (N formats × M compatibility modes).

## Decision

All schema formats are normalized to JSON Schema internally. The diff engine, compatibility checker, and versioning logic operate exclusively on JSON Schema.

**Supported formats and their sync paths:**

| Format | Ingestion Path | Normalization |
|--------|---------------|---------------|
| JSON Schema | Direct (native format) | None needed |
| dbt manifest | `POST /sync/dbt` | Extract column types, descriptions, tests → JSON Schema |
| OpenAPI 2.0/3.0 | `POST /sync/openapi` | Extract request/response schemas → JSON Schema |
| GraphQL introspection | `POST /sync/graphql` | Extract types, fields, arguments → JSON Schema |
| Protocol Buffers | `POST /sync/grpc` | Parse .proto message types → JSON Schema |
| Apache Avro | Avro validation + conversion | Map Avro types to JSON Schema equivalents |

Contracts store the normalized JSON Schema. The original format is recorded as metadata (`schema_format` field) but is not preserved verbatim.

## Consequences

**Benefits:**
- Single diff engine handles all formats. Adding a new format requires only a converter, not new diff logic.
- Cross-format comparison is possible. A dbt model and an OpenAPI endpoint that describe the same data can be compared.
- JSON Schema is the most widely supported schema language, with mature tooling for validation, generation, and documentation.

**Costs:**
- **Information loss.** Avro logical types (e.g., `timestamp-millis`), OpenAPI-specific extensions (`x-` fields), and Protobuf service definitions don't have JSON Schema equivalents. These are dropped or approximated during normalization.
- **No round-trip.** You can't reconstruct the original Avro schema from the stored JSON Schema. If a team needs the original, they must store it separately.
- **Converter correctness is critical.** A bug in the OpenAPI → JSON Schema converter silently corrupts all diffs for API-sourced contracts. Mitigated by dedicated test suites per converter.

## Alternatives Considered

**Store original format, diff natively:** Write a diff engine per format. Rejected due to combinatorial complexity and the impossibility of cross-format comparison.

**Use Avro as the canonical format:** Avro has strong typing and schema evolution rules. Rejected because JSON Schema is more widely understood and doesn't carry Avro's serialization assumptions.

**Store both original and normalized:** Keep the raw schema alongside the JSON Schema. Considered viable but deferred — adds storage cost and schema for unclear immediate benefit.
