# ADR-007: Async-First Architecture with Dual Database Support

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Tessera is a coordination service. Its workload is I/O-bound: database queries, webhook delivery, HTTP responses. CPU-bound work (schema diffing) is lightweight by comparison. An async architecture maximizes concurrency per worker for this workload profile.

Separately, development velocity depends on fast test cycles. PostgreSQL requires a running server and network I/O even for unit tests. SQLite in-memory eliminates both.

## Decision

### Async Throughout

- **Framework:** FastAPI with native async support.
- **Database:** SQLAlchemy 2.0 async (`AsyncSession`, `async_engine`).
- **PostgreSQL driver:** `asyncpg` — native async, highest performance.
- **HTTP client:** `httpx` with async support (for webhook delivery, external calls).
- **DNS resolution:** Async via `asyncio.get_event_loop().getaddrinfo()` (for webhook SSRF validation).

Every database operation uses `await`. No synchronous database calls exist in the codebase.

### Dual Database Support

- **Production:** PostgreSQL via `asyncpg`.
- **Testing:** SQLite via `aiosqlite` with in-memory databases (`sqlite+aiosqlite:///:memory:`).
- **Migrations:** Alembic migrations include `_is_sqlite()` checks for dialect-specific SQL (e.g., PostgreSQL enums vs SQLite text columns).

### Sequential Migration Numbering

Migrations use sequential numbers (001, 002, ..., 016) rather than Alembic's default hex revision IDs. This makes migration order obvious and simplifies debugging.

## Consequences

**Benefits:**
- High concurrency per worker. A single uvicorn process handles hundreds of concurrent requests without threads.
- Fast test cycles. SQLite in-memory tests run in seconds, not minutes.
- Sequential migration numbers are human-readable and make ordering unambiguous.

**Costs:**
- Async code is harder to debug. Stack traces include coroutine frames that obscure the call chain.
- Dialect divergence. SQLite and PostgreSQL handle enums, JSON, arrays, and locking differently. Every migration and some queries must account for this. Mitigated by the `_is_sqlite()` helper and integration tests.
- `AsyncSession` is not thread-safe. Sharing sessions across coroutines (e.g., via background tasks) requires careful lifecycle management.

## Alternatives Considered

**Synchronous with thread pool:** Use Flask/Django with a thread pool for concurrency. Rejected because thread overhead is higher and the Python GIL limits true parallelism for I/O-bound work.

**PostgreSQL for tests with Docker:** Spin up a PostgreSQL container for test runs. Rejected as too slow for local development iteration. Used in CI for integration tests only.
