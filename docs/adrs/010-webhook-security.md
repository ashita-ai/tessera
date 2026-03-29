# ADR-010: Webhook Security — HMAC Signing, SSRF Protection, Circuit Breaker

**Status:** Accepted
**Date:** 2026-03 (retroactive)
**Author:** Evan Volgas

## Context

Webhooks are the primary notification mechanism for proposals, acknowledgments, and contract publications. They deliver payloads to team-configured URLs. This creates three security and reliability concerns:

1. **Authenticity:** Receivers need to verify payloads came from Tessera, not an attacker.
2. **SSRF:** A malicious team could configure a webhook URL pointing to an internal service (e.g., `http://169.254.169.254/` for cloud metadata).
3. **Reliability:** A downed webhook endpoint shouldn't cause Tessera to spend resources retrying indefinitely.

## Decision

### HMAC-SHA256 Signing

Every webhook payload is signed with a per-webhook secret using HMAC-SHA256. The signature is included in the `X-Tessera-Signature` header. Receivers verify the signature before processing.

### SSRF Protection

Webhook URLs are validated before registration and before delivery:
1. **DNS resolution:** The URL's hostname is resolved asynchronously.
2. **IP validation:** Resolved IPs are checked against blocked ranges (private: `10.x`, `172.16-31.x`, `192.168.x`; loopback: `127.x`; link-local: `169.254.x`; cloud metadata endpoints).
3. **Allowlist:** An optional allowlist restricts URLs to approved domains.

### Circuit Breaker with Dead Letter Queue

An in-memory circuit breaker per webhook endpoint:
- **Closed** (normal): Deliveries proceed. Failures increment a counter.
- **Open** (after 5 consecutive failures): Deliveries fail fast for 60 seconds. Events are queued in a bounded dead letter queue (max 100 events).
- **Half-open** (after cooldown): One probe request is sent. Success closes the circuit; failure reopens it.

Dead-lettered events are also persisted to the `webhook_deliveries` table for later replay.

## Consequences

**Benefits:**
- HMAC prevents payload forgery. Receivers can trust the content.
- SSRF protection prevents webhooks from becoming a proxy to internal infrastructure.
- Circuit breaker prevents resource exhaustion from downed endpoints and provides graceful degradation.

**Costs:**
- **Circuit breaker is per-process and in-memory.** In a multi-worker deployment, each worker has independent state. Events queued in one worker's DLQ are lost if that worker crashes. The database persistence of dead-lettered events partially mitigates this.
- **DLQ replay is not automatic.** Dead-lettered events must be manually replayed or picked up by a background job (not yet implemented).
- **Allowlist maintenance** is an operational burden. If not configured, SSRF protection relies solely on IP blocking, which can be bypassed via DNS rebinding in some configurations.

## Alternatives Considered

**Redis-backed circuit breaker:** Share circuit state across workers. Deferred because Redis is optional in Tessera.

**Async webhook queue (e.g., Celery):** Offload delivery to a background task queue. Rejected as too heavy a dependency for the current scale. The in-process delivery model is simpler and sufficient.

**mTLS for webhooks:** Mutual TLS instead of HMAC. Rejected because it requires receivers to manage certificates, which is a high barrier for adoption.
