"""Schemas for the self-service portal, wallet and subscription plans."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import USERNAME_REGEXP, UserStatus


class PortalRegister(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_REGEXP.fullmatch(value):
            raise ValueError(
                "Username must be 3 to 32 characters and contain only letters, digits, _, -, @ or ."
            )
        return value


class PortalToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SubscriptionPlanBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    price_minor: int = Field(ge=0, le=10**12)
    currency: Literal["CNY"] = "CNY"
    duration_days: int = Field(ge=1, le=3650)
    data_limit: int = Field(ge=0, le=10**18)
    inbound_tags: List[str] = Field(min_length=1, max_length=64)
    is_active: bool = True
    is_default: bool = False

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
    pass


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1000)
    price_minor: Optional[int] = Field(default=None, ge=0, le=10**12)
    duration_days: Optional[int] = Field(default=None, ge=1, le=3650)
    data_limit: Optional[int] = Field(default=None, ge=0, le=10**18)
    inbound_tags: Optional[List[str]] = Field(default=None, min_length=1, max_length=64)
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None

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


class SubscriptionPlanResponse(SubscriptionPlanBase):
    id: int
    created_at: datetime
    updated_at: datetime
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
    assigned_plan_id: Optional[int] = None
    user_id: Optional[int] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PortalMeResponse(PortalAccountResponse):
    assigned_plan: Optional[SubscriptionPlanResponse] = None
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


class AssignPlanRequest(BaseModel):
    plan_id: Optional[int] = Field(default=None, gt=0)


class WalletRechargeRequest(BaseModel):
    amount_minor: int = Field(gt=0, le=10**12)
    note: Optional[str] = Field(default=None, max_length=500)


class AdminGrantPlanRequest(BaseModel):
    plan_id: Optional[int] = Field(default=None, gt=0)


class AdminRenewSubscriptionRequest(BaseModel):
    days: int = Field(ge=1, le=3650)


class PortalAccountAdminResponse(PortalAccountResponse):
    assigned_plan: Optional[SubscriptionPlanResponse] = None
    subscription: Optional[PortalSubscriptionResponse] = None
    usage: PortalUsageResponse
