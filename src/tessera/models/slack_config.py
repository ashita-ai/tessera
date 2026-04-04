"""Pydantic models for Slack configuration."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tessera.models.enums import SlackNotificationEventType

_VALID_EVENT_TYPES = {e.value for e in SlackNotificationEventType}
_CHANNEL_ID_RE = re.compile(r"^C[A-Z0-9]+$")


class SlackConfigCreate(BaseModel):
    """Fields for creating a Slack config."""

    team_id: UUID
    channel_id: str = Field(..., min_length=1, max_length=100)
    channel_name: str | None = Field(default=None, max_length=200)
    webhook_url: str | None = Field(default=None, max_length=500)
    bot_token: str | None = Field(default=None, max_length=500)
    notify_on: list[str] = Field(
        default=["proposal_created", "proposal_resolved", "force_publish"],
    )
    enabled: bool = True

    @model_validator(mode="after")
    def validate_auth_and_events(self) -> "SlackConfigCreate":
        """Validate that exactly one auth method is provided and event types are valid."""
        has_webhook = self.webhook_url is not None and self.webhook_url.strip() != ""
        has_token = self.bot_token is not None and self.bot_token.strip() != ""

        if not has_webhook and not has_token:
            raise ValueError("Either webhook_url or bot_token must be provided")
        if has_webhook and has_token:
            raise ValueError("Provide either webhook_url or bot_token, not both")

        if not _CHANNEL_ID_RE.match(self.channel_id):
            raise ValueError(
                f"channel_id must match Slack format (C followed by alphanumeric), "
                f"got: {self.channel_id}"
            )

        invalid = set(self.notify_on) - _VALID_EVENT_TYPES
        if invalid:
            raise ValueError(
                f"Invalid event types in notify_on: {sorted(invalid)}. "
                f"Valid types: {sorted(_VALID_EVENT_TYPES)}"
            )

        if len(self.notify_on) == 0:
            raise ValueError("notify_on must contain at least one event type")

        return self


class SlackConfigUpdate(BaseModel):
    """Fields for updating a Slack config. All fields optional."""

    channel_id: str | None = Field(default=None, min_length=1, max_length=100)
    channel_name: str | None = None
    webhook_url: str | None = Field(default=None, max_length=500)
    bot_token: str | None = Field(default=None, max_length=500)
    notify_on: list[str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_update_fields(self) -> "SlackConfigUpdate":
        """Validate update fields when provided."""
        if self.channel_id is not None and not _CHANNEL_ID_RE.match(self.channel_id):
            raise ValueError(
                f"channel_id must match Slack format (C followed by alphanumeric), "
                f"got: {self.channel_id}"
            )

        if self.notify_on is not None:
            invalid = set(self.notify_on) - _VALID_EVENT_TYPES
            if invalid:
                raise ValueError(
                    f"Invalid event types in notify_on: {sorted(invalid)}. "
                    f"Valid types: {sorted(_VALID_EVENT_TYPES)}"
                )
            if len(self.notify_on) == 0:
                raise ValueError("notify_on must contain at least one event type")

        return self


class SlackConfig(BaseModel):
    """Slack configuration entity (response model)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    channel_id: str
    channel_name: str | None = None
    webhook_url: str | None = None
    bot_token: str | None = None
    notify_on: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime | None = None


class SlackConfigResponse(BaseModel):
    """Slack config response that masks sensitive fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    channel_id: str
    channel_name: str | None = None
    has_webhook_url: bool = False
    has_bot_token: bool = False
    notify_on: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime | None = None

    @classmethod
    def from_db(cls, db: object) -> "SlackConfigResponse":
        """Create a response from a DB model, masking secrets."""
        return cls(
            id=db.id,  # type: ignore[attr-defined]
            team_id=db.team_id,  # type: ignore[attr-defined]
            channel_id=db.channel_id,  # type: ignore[attr-defined]
            channel_name=db.channel_name,  # type: ignore[attr-defined]
            has_webhook_url=db.webhook_url is not None,  # type: ignore[attr-defined]
            has_bot_token=db.bot_token is not None,  # type: ignore[attr-defined]
            notify_on=db.notify_on,  # type: ignore[attr-defined]
            enabled=db.enabled,  # type: ignore[attr-defined]
            created_at=db.created_at,  # type: ignore[attr-defined]
            updated_at=db.updated_at,  # type: ignore[attr-defined]
        )


class TestMessageResult(BaseModel):
    """Result of sending a test message."""

    success: bool
    error: str | None = None
