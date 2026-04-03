# Spec-008: Slack Notifications

**Related ADR:** ADR-014 (Service Contract Pivot), Phase 3
**Depends on:** Spec-006 (Repo and Service Registry), existing webhook infrastructure
**Status:** Draft
**Date:** 2026-04-02

## Overview

When a breaking change is detected, a proposal is created, or a proposal is resolved, notify the affected team's Slack channel. This replaces the current webhook-only notification model with a first-class Slack integration for the most common notification path.

## Why Slack specifically

Webhooks are general-purpose but require each team to build their own receiver. Slack is where most engineering teams already coordinate — a breaking change notification that lands in the team's channel gets seen and discussed immediately. The goal is zero-config notifications for the common case.

## Architecture

```
Tessera Event (proposal created, ack received, etc.)
    │
    ▼
WebhookDispatcher (existing)
    │
    ├─── Generic webhooks (existing behavior, unchanged)
    │
    └─── SlackFormatter → Slack Web API (new)
```

The Slack integration is a specialized webhook target, not a separate system. It reuses the webhook delivery infrastructure (outbox pattern from #397 when implemented, retry logic, circuit breaker) but formats messages as Slack Block Kit payloads instead of raw JSON.

## Data Model

### New table: `slack_configs`

```sql
CREATE TABLE slack_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         UUID NOT NULL REFERENCES teams(id),
    channel_id      VARCHAR(100) NOT NULL,     -- Slack channel ID (C0123456789)
    channel_name    VARCHAR(200),               -- display name, for UI only
    webhook_url     VARCHAR(500),               -- incoming webhook URL (option A)
    bot_token       VARCHAR(500),               -- bot token (option B, enables richer messages)
    notify_on       JSONB NOT NULL DEFAULT '["proposal_created", "proposal_resolved", "force_publish"]',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_slack_configs_team_channel
    ON slack_configs(team_id, channel_id);
```

`notify_on` is an array of event types. Supported values:
- `proposal_created` — a breaking change proposal was created that affects this team
- `proposal_resolved` — a proposal this team was tracking was approved/rejected/expired
- `force_publish` — someone force-published a breaking change affecting this team
- `contract_published` — any contract was published for an asset this team consumes
- `repo_sync_failed` — a repo owned by this team failed to sync

### Auth approach

Two options, team chooses one:
- **Incoming Webhook URL** — simplest setup, team creates a webhook in Slack and pastes the URL. Limited to posting messages.
- **Bot Token** — richer: can post, update messages, add reactions, thread replies. Requires Slack app installation.

## API Endpoints

### `POST /api/v1/slack/configs`

Configure Slack for a team.

```json
{
    "team_id": "uuid",
    "channel_id": "C0123456789",
    "channel_name": "#platform-alerts",
    "webhook_url": "https://hooks.slack.com/services/T.../B.../xxx",
    "notify_on": ["proposal_created", "force_publish"]
}
```

Validation:
- Either `webhook_url` or `bot_token` must be provided (not both)
- `channel_id` must match Slack's format (`^C[A-Z0-9]+$`)
- `notify_on` values must be from the supported set

### `GET /api/v1/slack/configs`

List Slack configs. Supports `?team_id=uuid` filter.

### `PATCH /api/v1/slack/configs/{id}`

Update notify_on, channel, or enabled flag.

### `DELETE /api/v1/slack/configs/{id}`

Remove Slack config for a team/channel.

### `POST /api/v1/slack/configs/{id}/test`

Send a test message to verify the configuration works. Returns `200` with delivery status.

## Message Formats

### Proposal Created

Sent to each affected consumer team's configured channel.

```
┌─────────────────────────────────────────────────┐
│ ⚠️  Breaking Change Proposal                    │
│                                                  │
│ *order-service* → `POST /orders` (v2.1.0 → v3) │
│                                                  │
│ 3 breaking changes:                              │
│ • Removed field `user_id`                        │
│ • Added required field `customer_id`             │
│ • Changed `amount` type: integer → number        │
│                                                  │
│ Proposed by: *commerce-team*                     │
│ Your team's response: ⏳ Awaiting                │
│ 2 of 4 consumers acknowledged                   │
│                                                  │
│ [View Proposal]  [Approve]  [Block]              │
└─────────────────────────────────────────────────┘
```

Block Kit structure:
- Header block with warning emoji and title
- Section block with service/asset info
- Section block with breaking changes (bulleted, max 5, "+ N more" if truncated)
- Context block with proposer and status
- Actions block with buttons (deep links to Tessera UI, not Slack actions — keeps it simple)

### Proposal Resolved

```
┌─────────────────────────────────────────────────┐
│ ✅  Proposal Approved                            │
│                                                  │
│ *order-service* → `POST /orders` v3.0.0          │
│ All 4 consumers acknowledged. Publishing.        │
│                                                  │
│ [View Contract]                                  │
└─────────────────────────────────────────────────┘
```

Or for rejected:

```
┌─────────────────────────────────────────────────┐
│ 🚫  Proposal Blocked                            │
│                                                  │
│ *order-service* → `POST /orders` v3.0.0          │
│ Blocked by: *analytics-team*                     │
│ Reason: "Migration to customer_id not complete"  │
│                                                  │
│ [View Proposal]                                  │
└─────────────────────────────────────────────────┘
```

### Force Publish

```
┌─────────────────────────────────────────────────┐
│ 🔴  Force Publish (Breaking Change)             │
│                                                  │
│ *order-service* → `POST /orders` v3.0.0          │
│ Published without full consumer acknowledgment.  │
│                                                  │
│ Reason: "Hotfix for payment processing bug"      │
│ Published by: *jane.doe* (commerce-team)         │
│                                                  │
│ [View Contract]  [View Audit Log]                │
└─────────────────────────────────────────────────┘
```

### Repo Sync Failed

```
┌─────────────────────────────────────────────────┐
│ ❌  Repo Sync Failed                             │
│                                                  │
│ *acme/order-service* failed to sync from git     │
│ Error: "Could not parse api/openapi.yaml"        │
│ Last successful sync: 2h ago                     │
│                                                  │
│ [View Repo]                                      │
└─────────────────────────────────────────────────┘
```

## Implementation

### SlackFormatter (`services/slack_formatter.py`)

Pure function: takes a Tessera event and produces a Slack Block Kit payload.

```python
def format_proposal_created(
    proposal: Proposal,
    asset: Asset,
    service: Service | None,
    repo: Repo | None,
    breaking_changes: list[BreakingChange],
    affected_team: Team,
    tessera_base_url: str,
) -> dict:
    """Returns a Slack Block Kit message payload."""
```

One function per event type. No side effects, no HTTP calls — just data transformation.

### SlackDelivery (`services/slack_delivery.py`)

Sends formatted messages via Slack API.

```python
async def deliver_slack_message(
    config: SlackConfig,
    payload: dict,
) -> DeliveryResult:
```

- If `webhook_url`: POST to the URL with the payload
- If `bot_token`: POST to `https://slack.com/api/chat.postMessage` with Bearer token
- Reuses existing SSRF protection from webhook delivery
- Reuses retry/circuit-breaker logic

### Event Hooks

In the existing event dispatch path (wherever webhooks are triggered today), add Slack dispatch:

```python
# In contract_publisher.py, after proposal creation:
await dispatch_slack_notifications(
    session=session,
    event_type="proposal_created",
    affected_team_ids=affected_team_ids,
    context={"proposal": proposal, "asset": asset, "breaking_changes": changes},
)
```

`dispatch_slack_notifications` looks up Slack configs for the affected teams, filters by `notify_on`, formats the message, and queues delivery.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TESSERA_SLACK_ENABLED` | `false` | Enable Slack notifications globally |
| `TESSERA_BASE_URL` | `http://localhost:3000` | Base URL for deep links in messages |
| `TESSERA_SLACK_RATE_LIMIT` | `1/sec` | Max Slack API calls per second (Slack's limit is 1/sec per channel) |

## Security

- Webhook URLs and bot tokens stored encrypted at rest (use existing credential storage pattern)
- SSRF protection on webhook URLs (reuse from webhook delivery)
- Bot tokens validated against Slack API on creation (`auth.test` call)
- No message content from user input is rendered without escaping (Slack's mrkdwn is limited, but still escape `<`, `>`, `&`)

## Acceptance Criteria

- [ ] `SlackConfigDB` model and migration
- [ ] CRUD endpoints for Slack configs
- [ ] Test message endpoint
- [ ] SlackFormatter: proposal_created message
- [ ] SlackFormatter: proposal_resolved message
- [ ] SlackFormatter: force_publish message
- [ ] SlackFormatter: repo_sync_failed message
- [ ] Delivery via incoming webhook URL
- [ ] Delivery via bot token
- [ ] Event hook integration: proposals trigger Slack
- [ ] Event hook integration: force publish triggers Slack
- [ ] Respects `notify_on` filter (doesn't send unwanted events)
- [ ] Rate limiting (1/sec per channel)
- [ ] SSRF protection on webhook URLs
- [ ] Test: proposal created → message sent to affected team's channel
- [ ] Test: team with no Slack config → no error, silently skipped
- [ ] Test: disabled config → skipped
- [ ] Test: delivery failure → retried (via existing webhook retry logic)
- [ ] Test: test message endpoint works
