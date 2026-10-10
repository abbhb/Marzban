"""Schemas for the self-service portal, wallet and subscription plans."""

from datetime import datetime
from typing import Generic, List, Literal, Optional, TypeVar
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.models.user import USERNAME_REGEXP, UserStatus


PageItem = TypeVar("PageItem")

_RESERVED_EXTERNAL_GROUP_NAMES = {
    "mgma · external",
    "direct",
    "reject",
    "reject-drop",
    "pass",
    "compatible",
    "global",
}


def _clean_source_label(value: str, *, group_name: bool = False) -> str:
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if not cleaned or len(cleaned) > 128:
        raise ValueError("Value must contain 1 to 128 characters")
    if any(
        unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}
        for char in cleaned
    ):
        raise ValueError("Invisible control characters are not allowed")
    if group_name and cleaned.casefold() in _RESERVED_EXTERNAL_GROUP_NAMES:
        raise ValueError("Group name is reserved")
    return cleaned

PortalAccountListStatus = Literal[
    "not_activated",
    "active",
    "disabled",
    "limited",
    "expired",
    "on_hold",
]
InvitationListStatus = Literal[
    "available",
    "scheduled",
    "expired",
    "exhausted",
    "disabled",
]
IPBlockListStatus = Literal["blocked", "expired", "revoked"]
IPBlockListSource = Literal[
    "manual",
    "portal_login",
    "admin_login",
    "portal_registration",
]


class PaginatedResponse(BaseModel, Generic[PageItem]):
    items: List[PageItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class PortalRegister(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=10, max_length=128)
    invitation_code: str = Field(min_length=20, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_REGEXP.fullmatch(value):
            raise ValueError(
                "Username must be 3 to 32 characters and contain only letters, digits, _, -, @ or ."
            )
        return value


class PortalPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class PortalToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ExternalSelectionInput(BaseModel):
    source_id: int = Field(gt=0)
    mode: Literal["all", "selected"] = "all"
    node_ids: List[int] = Field(default_factory=list, max_length=1000)

    @field_validator("node_ids")
    @classmethod
    def validate_node_ids(cls, values: List[int]) -> List[int]:
        if any(value <= 0 for value in values):
            raise ValueError("Node IDs must be positive")
        if len(set(values)) != len(values):
            raise ValueError("Node IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "all" and self.node_ids:
            raise ValueError("All mode must not contain node IDs")
        if self.mode == "selected" and not self.node_ids:
            raise ValueError("Selected mode requires at least one node ID")
        return self


class ExternalSelectionResponse(ExternalSelectionInput):
    model_config = ConfigDict(from_attributes=True)


class SubscriptionPlanBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    price_minor: int = Field(ge=0, le=10**12)
    currency: Literal["CNY"] = "CNY"
    duration_days: int = Field(ge=1, le=3650)
    data_limit: int = Field(ge=0, le=10**18)
    inbound_tags: List[str] = Field(default_factory=list, max_length=64)
    is_visible: bool = True

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("inbound_tags")
    @classmethod
    def validate_inbound_tags(cls, values: List[str]) -> List[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 256 for value in cleaned):
            raise ValueError("Inbound tags must be between 1 and 256 characters")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Inbound tags must be unique")
        return cleaned


class SubscriptionPlanCreate(SubscriptionPlanBase):
    external_selections: List[ExternalSelectionInput] = Field(
        default_factory=list,
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_entitlements(self):
        if not self.inbound_tags and not self.external_selections:
            raise ValueError("A plan requires a local inbound or external selection")
        source_ids = [selection.source_id for selection in self.external_selections]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("External sources must be unique within a plan")
        return self


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1000)
    price_minor: Optional[int] = Field(default=None, ge=0, le=10**12)
    duration_days: Optional[int] = Field(default=None, ge=1, le=3650)
    data_limit: Optional[int] = Field(default=None, ge=0, le=10**18)
    inbound_tags: Optional[List[str]] = Field(default=None, max_length=64)
    external_selections: Optional[List[ExternalSelectionInput]] = Field(
        default=None,
        max_length=64,
    )
    is_visible: Optional[bool] = None

    @field_validator("name", "description")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else value

    @field_validator("inbound_tags")
    @classmethod
    def validate_optional_inbound_tags(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return values
        return SubscriptionPlanBase.validate_inbound_tags(values)

    @field_validator("external_selections")
    @classmethod
    def validate_optional_external_selections(
        cls,
        values: Optional[List[ExternalSelectionInput]],
    ) -> Optional[List[ExternalSelectionInput]]:
        if values is None:
            return values
        source_ids = [selection.source_id for selection in values]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("External sources must be unique within a plan")
        return values


class SubscriptionPlanResponse(SubscriptionPlanBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SubscriptionPlanAdminResponse(SubscriptionPlanResponse):
    external_selections: List[ExternalSelectionResponse] = Field(default_factory=list)


class ExternalSubscriptionSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    group_name: Optional[str] = Field(default=None, max_length=128)
    url: Optional[SecretStr] = Field(default=None, max_length=4096)
    enabled: bool = True
    refresh_interval_minutes: int = Field(default=360, ge=15, le=10_080)

    @field_validator("name")
    @classmethod
    def strip_source_name(cls, value: str) -> str:
        return _clean_source_label(value)

    @field_validator("group_name")
    @classmethod
    def strip_group_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return _clean_source_label(value, group_name=True)

    @model_validator(mode="after")
    def default_group_name(self):
        if self.group_name is None:
            self.group_name = _clean_source_label(self.name, group_name=True)
        return self


class ExternalSubscriptionSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    enabled: Optional[bool] = None
    refresh_interval_minutes: Optional[int] = Field(default=None, ge=15, le=10_080)

    @field_validator("name")
    @classmethod
    def strip_optional_source_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _clean_source_label(value)


class ExternalSubscriptionCredentialUpdate(BaseModel):
    url: SecretStr = Field(max_length=4096)


class ExternalSubscriptionSourceResponse(BaseModel):
    id: int
    owner_account_id: Optional[int] = None
    owner_username: Optional[str] = None
    name: str
    group_name: str
    credential_configured: bool
    enabled: bool
    refresh_interval_minutes: int
    status: Literal["empty", "ready", "auth_required", "error", "disabled"]
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    next_refresh_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    node_count: int
    skipped_node_count: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExternalSubscriptionNodeResponse(BaseModel):
    id: int
    name: str
    proxy_type: str
    is_active: bool
    position: int
    model_config = ConfigDict(from_attributes=True)


class PortalSubscriptionResponse(BaseModel):
    id: int
    plan_id: int
    plan_name: str
    price_paid_minor: int
    currency: str
    duration_days: int
    data_limit: int
    inbound_tags: List[str]
    starts_at: datetime
    expires_at: datetime
    purchased_at: datetime
    disabled_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class PortalUsageResponse(BaseModel):
    status: Optional[UserStatus] = None
    used_traffic: int = 0
    data_limit: Optional[int] = None
    lifetime_used_traffic: int = 0
    expire: Optional[int] = None


class PortalAccountResponse(BaseModel):
    id: int
    username: str
    wallet_balance_minor: int
    is_active: bool
    user_id: Optional[int] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PortalMeResponse(PortalAccountResponse):
    subscription: Optional[PortalSubscriptionResponse] = None
    usage: PortalUsageResponse


class WalletTransactionResponse(BaseModel):
    id: int
    amount_minor: int
    balance_after_minor: int
    kind: str
    actor_admin: Optional[str] = None
    purchase_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PortalPurchaseRequest(BaseModel):
    plan_id: int = Field(gt=0)


class PortalPurchaseResponse(BaseModel):
    purchase_id: int
    replayed: bool = False
    wallet_balance_minor: int
    subscription: PortalSubscriptionResponse
    usage: PortalUsageResponse


class WalletRechargeRequest(BaseModel):
    amount_minor: int = Field(gt=0, le=10**12)
    note: Optional[str] = Field(default=None, max_length=500)


class AdminGrantPlanRequest(BaseModel):
    plan_id: int = Field(gt=0)


class AdminManagedAccountCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    plan_id: int = Field(gt=0)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return PortalRegister.validate_username(value)


class AdminRenewSubscriptionRequest(BaseModel):
    days: int = Field(ge=1, le=3650)


class PortalAccountAdminResponse(PortalAccountResponse):
    subscription: Optional[PortalSubscriptionResponse] = None
    usage: PortalUsageResponse


class GeneratedPasswordResponse(BaseModel):
    username: str
    password: str = Field(min_length=20, max_length=128)


class AdminManagedAccountCreateResponse(GeneratedPasswordResponse):
    account: PortalAccountAdminResponse


class UserExternalEntitlementResponse(BaseModel):
    source_id: int
    name: str
    group_name: str
    mode: Literal["all", "selected"]
    node_count: int = Field(ge=0)
    status: str


class UserEntitlementResponse(BaseModel):
    managed_by_plan: bool = False
    account_id: Optional[int] = None
    subscription_id: Optional[int] = None
    plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    inbound_tags: List[str] = Field(default_factory=list)
    external_sources: List[UserExternalEntitlementResponse] = Field(
        default_factory=list
    )
    expires_at: Optional[datetime] = None
    disabled_at: Optional[datetime] = None


class InvitationCreate(BaseModel):
    note: str = Field(default="", max_length=500)
    valid_from: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = Field(default=1, ge=1, le=1_000_000)


class InvitationResponse(BaseModel):
    id: int
    code_prefix: str
    note: str
    valid_from: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    use_count: int
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class InvitationCreatedResponse(InvitationResponse):
    code: str


class IPBlockCreate(BaseModel):
    network: str = Field(min_length=2, max_length=64)
    reason: str = Field(min_length=1, max_length=500)
    expires_at: Optional[datetime] = None


class IPBlockResponse(BaseModel):
    id: int
    network: str
    reason: str
    source: str
    is_active: bool
    expires_at: Optional[datetime] = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class PortalSecuritySettingsUpdate(BaseModel):
    auto_block_enabled: bool = True
    login_failure_limit: int = Field(ge=2, le=100)
    login_window_seconds: int = Field(ge=60, le=86400)
    registration_failure_limit: int = Field(ge=2, le=100)
    registration_window_seconds: int = Field(ge=60, le=86400)
    auto_block_seconds: int = Field(ge=0, le=2_592_000)


class PortalSecuritySettingsResponse(PortalSecuritySettingsUpdate):
    id: int
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
