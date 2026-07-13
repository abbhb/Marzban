"""API and service models for temporary (MGMA) subscription access."""

from datetime import datetime, timezone
from enum import Enum
from ipaddress import ip_network
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


class MgmaAccessMode(str, Enum):
    """How the legacy, permanent subscription routes are handled."""

    legacy = "legacy"
    dual = "dual"
    ephemeral = "ephemeral"


class MgmaSourceMode(str, Enum):
    """Source-address policy applied to all accepted subscription downloads."""

    any = "any"
    china = "china"
    custom = "custom"
    china_or_custom = "china_or_custom"


class MgmaSettingsBase(BaseModel):
    mode: MgmaAccessMode = MgmaAccessMode.legacy
    ttl_seconds: int = Field(default=180, ge=30, le=900)
    single_use: bool = False
    source_mode: MgmaSourceMode = MgmaSourceMode.any
    custom_cidrs: List[str] = Field(default_factory=list, max_length=512)

    @field_validator("custom_cidrs", mode="before")
    @classmethod
    def normalize_custom_cidrs(cls, value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("custom_cidrs must be a list of IPv4 or IPv6 CIDRs")

        normalized = []
        seen = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("custom_cidrs entries must be non-empty strings")
            try:
                network = str(ip_network(item.strip(), strict=False))
            except ValueError as exc:
                raise ValueError(f"invalid CIDR: {item}") from exc
            if network not in seen:
                normalized.append(network)
                seen.add(network)
        return normalized

    @model_validator(mode="after")
    def require_custom_cidrs(self):
        if self.source_mode == MgmaSourceMode.custom and not self.custom_cidrs:
            raise ValueError("custom source mode requires at least one CIDR")
        return self


class MgmaSettingsUpdate(MgmaSettingsBase):
    """Complete replacement payload for the singleton MGMA settings."""


class MgmaSettingsResponse(MgmaSettingsBase):
    pepper_configured: bool
    cn_cidr_version: Optional[str] = None
    cn_cidr_data_end_date: Optional[str] = None
    cn_cidr_count: int = 0
    cn_cidr_sha256: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


def _serialize_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class MgmaTokenIssue(BaseModel):
    """Internal result; ``token`` must only be used to build the one-time response."""

    token: str = Field(repr=False)
    issued_at: datetime
    expires_at: datetime
    ttl_seconds: int

    @field_serializer("issued_at", "expires_at")
    def serialize_datetimes(self, value: datetime) -> str:
        return _serialize_utc(value)


class MgmaIssueResponse(BaseModel):
    """Public response returned when an administrator requests an MGMA URL."""

    url: str
    issued_at: datetime
    expires_at: datetime
    ttl_seconds: int

    @field_serializer("issued_at", "expires_at")
    def serialize_datetimes(self, value: datetime) -> str:
        return _serialize_utc(value)
