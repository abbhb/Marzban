import os
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import select, text

from app import xray
from app.db.base import Base
from app.models.node import NodeStatus
from app.models.proxy import (
    ProxyHostALPN,
    ProxyHostFingerprint,
    ProxyHostSecurity,
    ProxyTypes,
)
from app.models.user import ReminderType, UserDataLimitResetStrategy, UserStatus


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    username = Column(String(34), unique=True, index=True)
    hashed_password = Column(String(128))
    users = relationship("User", back_populates="admin")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_sudo = Column(Boolean, default=False)
    password_reset_at = Column(DateTime, nullable=True)
    telegram_id = Column(BigInteger, nullable=True, default=None)
    discord_webhook = Column(String(1024), nullable=True, default=None)
    users_usage = Column(BigInteger, nullable=False, default=0)
    usage_logs = relationship("AdminUsageLogs", back_populates="admin")


class AdminUsageLogs(Base):
    __tablename__ = "admin_usage_logs"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(34, collation='NOCASE'), unique=True, index=True)
    proxies = relationship("Proxy", back_populates="user", cascade="all, delete-orphan")
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.active)
    used_traffic = Column(BigInteger, default=0)
    node_usages = relationship("NodeUserUsage", back_populates="user", cascade="all, delete-orphan")
    notification_reminders = relationship("NotificationReminder", back_populates="user", cascade="all, delete-orphan")
    data_limit = Column(BigInteger, nullable=True)
    data_limit_reset_strategy = Column(
        Enum(UserDataLimitResetStrategy),
        nullable=False,
        default=UserDataLimitResetStrategy.no_reset,
    )
    usage_logs = relationship("UserUsageResetLogs", back_populates="user")  # maybe rename it to reset_usage_logs?
    expire = Column(Integer, nullable=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="users")
    sub_revoked_at = Column(DateTime, nullable=True, default=None)
    sub_updated_at = Column(DateTime, nullable=True, default=None)
    sub_last_user_agent = Column(String(512), nullable=True, default=None)
    # MGMA subscription access tokens are deliberately stored as keyed digests.
    # The clear-text token is returned once by the issuance endpoint and must
    # never be persisted.
    sub_access_token_digest = Column(String(64), nullable=True, unique=True, index=True)
    sub_access_issued_at = Column(DateTime, nullable=True, default=None)
    sub_access_expires_at = Column(DateTime, nullable=True, default=None)
    sub_access_consumed_at = Column(DateTime, nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(500), nullable=True, default=None)
    online_at = Column(DateTime, nullable=True, default=None)
    on_hold_expire_duration = Column(BigInteger, nullable=True, default=None)
    on_hold_timeout = Column(DateTime, nullable=True, default=None)

    # * Positive values: User will be deleted after the value of this field in days automatically.
    # * Negative values: User won't be deleted automatically at all.
    # * NULL: Uses global settings.
    auto_delete_in_days = Column(Integer, nullable=True, default=None)

    edit_at = Column(DateTime, nullable=True, default=None)
    last_status_change = Column(DateTime, default=datetime.utcnow, nullable=True)

    next_plan = relationship(
        "NextPlan",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan"
    )

    @hybrid_property
    def reseted_usage(self) -> int:
        return int(sum([log.used_traffic_at_reset for log in self.usage_logs]))

    @reseted_usage.expression
    def reseted_usage(cls):
        return (
            select(func.sum(UserUsageResetLogs.used_traffic_at_reset)).
            where(UserUsageResetLogs.user_id == cls.id).
            label('reseted_usage')
        )

    @property
    def lifetime_used_traffic(self) -> int:
        return int(
            sum([log.used_traffic_at_reset for log in self.usage_logs])
            + self.used_traffic
        )

    @property
    def last_traffic_reset_time(self):
        return self.usage_logs[-1].reset_at if self.usage_logs else self.created_at

    @property
    def excluded_inbounds(self):
        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = [i.tag for i in proxy.excluded_inbounds]
        return _

    @property
    def inbounds(self):
        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = []
            excluded_tags = [i.tag for i in proxy.excluded_inbounds]
            for inbound in xray.config.inbounds_by_protocol.get(proxy.type, []):
                if inbound["tag"] not in excluded_tags:
                    _[proxy.type].append(inbound["tag"])

        return _


excluded_inbounds_association = Table(
    "exclude_inbounds_association",
    Base.metadata,
    Column("proxy_id", ForeignKey("proxies.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)

template_inbounds_association = Table(
    "template_inbounds_association",
    Base.metadata,
    Column("user_template_id", ForeignKey("user_templates.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)


class NextPlan(Base):
    __tablename__ = 'next_plans'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    data_limit = Column(BigInteger, nullable=False)
    expire = Column(Integer, nullable=True)
    add_remaining_traffic = Column(Boolean, nullable=False, default=False, server_default='0')
    fire_on_either = Column(Boolean, nullable=False, default=True, server_default='0')

    user = relationship("User", back_populates="next_plan")


class UserTemplate(Base):
    __tablename__ = "user_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    data_limit = Column(BigInteger, default=0)
    expire_duration = Column(BigInteger, default=0)  # in seconds
    username_prefix = Column(String(20), nullable=True)
    username_suffix = Column(String(20), nullable=True)

    inbounds = relationship(
        "ProxyInbound", secondary=template_inbounds_association
    )


class UserUsageResetLogs(Base):
    __tablename__ = "user_usage_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="proxies")
    type = Column(Enum(ProxyTypes), nullable=False)
    settings = Column(JSON, nullable=False)
    excluded_inbounds = relationship(
        "ProxyInbound", secondary=excluded_inbounds_association
    )


class ProxyInbound(Base):
    __tablename__ = "inbounds"

    id = Column(Integer, primary_key=True)
    tag = Column(String(256), unique=True, nullable=False, index=True)
    hosts = relationship(
        "ProxyHost", back_populates="inbound", cascade="all, delete-orphan"
    )


class ProxyHost(Base):
    __tablename__ = "hosts"
    # __table_args__ = (
    #     UniqueConstraint('inbound_tag', 'remark'),
    # )

    id = Column(Integer, primary_key=True)
    remark = Column(String(256), unique=False, nullable=False)
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, nullable=True)
    path = Column(String(256), unique=False, nullable=True)
    sni = Column(String(1000), unique=False, nullable=True)
    host = Column(String(1000), unique=False, nullable=True)
    security = Column(
        Enum(ProxyHostSecurity),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.inbound_default,
    )
    alpn = Column(
        Enum(ProxyHostALPN),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name
    )
    fingerprint = Column(
        Enum(ProxyHostFingerprint),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name
    )

    inbound_tag = Column(String(256), ForeignKey("inbounds.tag"), nullable=False)
    inbound = relationship("ProxyInbound", back_populates="hosts")
    allowinsecure = Column(Boolean, nullable=True)
    is_disabled = Column(Boolean, nullable=True, default=False)
    mux_enable = Column(Boolean, nullable=False, default=False, server_default='0')
    fragment_setting = Column(String(100), nullable=True)
    noise_setting = Column(String(2000), nullable=True)
    random_user_agent = Column(Boolean, nullable=False, default=False, server_default='0')
    use_sni_as_host = Column(Boolean, nullable=False, default=False, server_default="0")


class System(Base):
    __tablename__ = "system"

    id = Column(Integer, primary_key=True)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class MgmaSettings(Base):
    """Singleton settings for temporary subscription access."""

    __tablename__ = "mgma_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_mgma_settings_singleton"),
        CheckConstraint(
            "mode IN ('legacy', 'dual', 'ephemeral')",
            name="ck_mgma_settings_mode",
        ),
        CheckConstraint(
            "ttl_seconds BETWEEN 30 AND 900",
            name="ck_mgma_settings_ttl_seconds",
        ),
        CheckConstraint(
            "source_mode IN ('any', 'china', 'custom', 'china_or_custom')",
            name="ck_mgma_settings_source_mode",
        ),
    )

    id = Column(Integer, primary_key=True, default=1)
    mode = Column(String(16), nullable=False, default="legacy", server_default="legacy")
    ttl_seconds = Column(Integer, nullable=False, default=180, server_default="180")
    single_use = Column(Boolean, nullable=False, default=False, server_default="0")
    source_mode = Column(String(32), nullable=False, default="any", server_default="any")
    custom_cidrs = Column(JSON, nullable=False, default=list)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class SubscriptionPlan(Base):
    """A VLESS plan globally visible to portal accounts when enabled."""

    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="ck_subscription_plans_price"),
        CheckConstraint("duration_days > 0", name="ck_subscription_plans_duration"),
        CheckConstraint("data_limit >= 0", name="ck_subscription_plans_data_limit"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(String(1000), nullable=False, default="", server_default="")
    price_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default="CNY", server_default="CNY")
    duration_days = Column(Integer, nullable=False)
    data_limit = Column(BigInteger, nullable=False, default=0, server_default="0")
    inbound_tags = Column(JSON, nullable=False, default=list)
    is_visible = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    subscriptions = relationship("PortalSubscription", back_populates="plan")
    purchases = relationship("PortalPurchase", back_populates="plan")


class PortalAccount(Base):
    """A self-service login, kept separate from privileged administrators."""

    __tablename__ = "portal_accounts"
    __table_args__ = (
        CheckConstraint("wallet_balance_minor >= 0", name="ck_portal_accounts_balance"),
    )

    id = Column(Integer, primary_key=True)
    username = Column(String(34, collation="NOCASE"), nullable=False, unique=True, index=True)
    hashed_password = Column(String(128), nullable=False)
    wallet_balance_minor = Column(BigInteger, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    password_reset_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    proxy_user = relationship("User", foreign_keys=[user_id])
    subscription = relationship(
        "PortalSubscription",
        uselist=False,
        back_populates="account",
        cascade="all, delete-orphan",
    )
    purchases = relationship("PortalPurchase", back_populates="account")
    wallet_transactions = relationship("WalletTransaction", back_populates="account")


class PortalInvitationCode(Base):
    """Hashed invitation capability; plaintext is returned only at creation."""

    __tablename__ = "portal_invitation_codes"
    __table_args__ = (
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_portal_invites_max_uses"),
        CheckConstraint("use_count >= 0", name="ck_portal_invites_use_count"),
    )

    id = Column(Integer, primary_key=True)
    code_digest = Column(String(64), nullable=False, unique=True, index=True)
    code_prefix = Column(String(16), nullable=False)
    note = Column(String(500), nullable=False, default="", server_default="")
    valid_from = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    max_uses = Column(Integer, nullable=True)
    use_count = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_by = Column(String(34), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    last_used_at = Column(DateTime, nullable=True)

    uses = relationship("PortalInvitationUse", back_populates="invitation")


class PortalInvitationUse(Base):
    """Immutable audit record linking an invitation to the created account."""

    __tablename__ = "portal_invitation_uses"

    id = Column(Integer, primary_key=True)
    invitation_id = Column(
        Integer,
        ForeignKey("portal_invitation_codes.id"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        Integer,
        ForeignKey("portal_accounts.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    source_ip = Column(String(45), nullable=False)
    used_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    invitation = relationship("PortalInvitationCode", back_populates="uses")
    account = relationship("PortalAccount")


class PortalIPBlock(Base):
    """Persistent exact-IP or CIDR deny entry with an operator-readable reason."""

    __tablename__ = "portal_ip_blocks"

    id = Column(Integer, primary_key=True)
    network = Column(String(64), nullable=False, unique=True, index=True)
    reason = Column(String(500), nullable=False)
    source = Column(String(32), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(String(34), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(34), nullable=True)


class PortalSecurityAttempt(Base):
    """Bounded persistent failure counter for one source IP and auth flow."""

    __tablename__ = "portal_security_attempts"
    __table_args__ = (
        UniqueConstraint("source_ip", "kind", name="uq_portal_security_attempt_ip_kind"),
        CheckConstraint("failure_count > 0", name="ck_portal_security_attempt_count"),
    )

    id = Column(Integer, primary_key=True)
    source_ip = Column(String(45), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
    failure_count = Column(Integer, nullable=False, default=1, server_default="1")
    window_started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_failed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PortalSecuritySettings(Base):
    """Singleton policy for automatic IP blocking."""

    __tablename__ = "portal_security_settings"
    __table_args__ = (
        CheckConstraint("login_failure_limit BETWEEN 2 AND 100", name="ck_portal_security_login_limit"),
        CheckConstraint("registration_failure_limit BETWEEN 2 AND 100", name="ck_portal_security_register_limit"),
        CheckConstraint("login_window_seconds BETWEEN 60 AND 86400", name="ck_portal_security_login_window"),
        CheckConstraint("registration_window_seconds BETWEEN 60 AND 86400", name="ck_portal_security_register_window"),
        CheckConstraint("auto_block_seconds BETWEEN 0 AND 2592000", name="ck_portal_security_block_seconds"),
    )

    id = Column(Integer, primary_key=True)
    auto_block_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    login_failure_limit = Column(Integer, nullable=False, default=8, server_default="8")
    login_window_seconds = Column(Integer, nullable=False, default=900, server_default="900")
    registration_failure_limit = Column(Integer, nullable=False, default=5, server_default="5")
    registration_window_seconds = Column(Integer, nullable=False, default=600, server_default="600")
    auto_block_seconds = Column(Integer, nullable=False, default=86400, server_default="86400")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class PortalPurchase(Base):
    """Immutable purchase/grant/renewal history and idempotency record."""

    __tablename__ = "portal_purchases"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_portal_purchase_idempotency"),
        CheckConstraint("amount_minor >= 0", name="ck_portal_purchases_amount"),
        CheckConstraint(
            "kind IN ('self_purchase', 'admin_grant', 'admin_renewal')",
            name="ck_portal_purchases_kind",
        ),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("portal_accounts.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    kind = Column(String(24), nullable=False)
    idempotency_key = Column(String(128), nullable=True)
    actor_admin = Column(String(34), nullable=True)
    plan_name = Column(String(128), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False)
    duration_days = Column(Integer, nullable=False)
    data_limit = Column(BigInteger, nullable=False)
    inbound_tags = Column(JSON, nullable=False)
    balance_before_minor = Column(BigInteger, nullable=False)
    balance_after_minor = Column(BigInteger, nullable=False)
    effective_expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    account = relationship("PortalAccount", back_populates="purchases")
    plan = relationship("SubscriptionPlan", back_populates="purchases")


class PortalSubscription(Base):
    """The single current subscription snapshot for a portal account."""

    __tablename__ = "portal_subscriptions"
    __table_args__ = (
        CheckConstraint("data_limit >= 0", name="ck_portal_subscriptions_data_limit"),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(
        Integer,
        ForeignKey("portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    plan_name = Column(String(128), nullable=False)
    price_paid_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False)
    duration_days = Column(Integer, nullable=False)
    data_limit = Column(BigInteger, nullable=False)
    inbound_tags = Column(JSON, nullable=False)
    starts_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    purchased_at = Column(DateTime, nullable=False)
    disabled_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    account = relationship("PortalAccount", back_populates="subscription")
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")


class WalletTransaction(Base):
    """Append-only wallet ledger. Amounts are signed integer minor units."""

    __tablename__ = "wallet_transactions"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "kind",
            "idempotency_key",
            name="uq_wallet_transaction_idempotency",
        ),
        CheckConstraint("amount_minor != 0", name="ck_wallet_transactions_amount"),
        CheckConstraint("balance_after_minor >= 0", name="ck_wallet_transactions_balance"),
        CheckConstraint(
            "kind IN ('admin_credit', 'purchase_debit')",
            name="ck_wallet_transactions_kind",
        ),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("portal_accounts.id"), nullable=False, index=True)
    amount_minor = Column(BigInteger, nullable=False)
    balance_after_minor = Column(BigInteger, nullable=False)
    kind = Column(String(24), nullable=False)
    idempotency_key = Column(String(128), nullable=True)
    actor_admin = Column(String(34), nullable=True)
    purchase_id = Column(Integer, ForeignKey("portal_purchases.id"), nullable=True, index=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    account = relationship("PortalAccount", back_populates="wallet_transactions")
    purchase = relationship("PortalPurchase")


class JWT(Base):
    __tablename__ = "jwt"

    id = Column(Integer, primary_key=True)
    secret_key = Column(
        String(64), nullable=False, default=lambda: os.urandom(32).hex()
    )


class TLS(Base):
    __tablename__ = "tls"

    id = Column(Integer, primary_key=True)
    key = Column(String(4096), nullable=False)
    certificate = Column(String(2048), nullable=False)


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True)
    name = Column(String(256, collation='NOCASE'), unique=True)
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, unique=False, nullable=False)
    api_port = Column(Integer, unique=False, nullable=False)
    xray_version = Column(String(32), nullable=True)
    status = Column(Enum(NodeStatus), nullable=False, default=NodeStatus.connecting)
    last_status_change = Column(DateTime, default=datetime.utcnow)
    message = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)
    user_usages = relationship("NodeUserUsage", back_populates="node", cascade="all, delete-orphan")
    usages = relationship("NodeUsage", back_populates="node", cascade="all, delete-orphan")
    usage_coefficient = Column(Float, nullable=False, server_default=text("1.0"), default=1)


class NodeUserUsage(Base):
    __tablename__ = "node_user_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'user_id', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="node_usages")
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="user_usages")
    used_traffic = Column(BigInteger, default=0)


class NodeUsage(Base):
    __tablename__ = "node_usages"
    __table_args__ = (
        UniqueConstraint('created_at', 'node_id'),
    )

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="usages")
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class NotificationReminder(Base):
    __tablename__ = "notification_reminders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="notification_reminders")
    type = Column(Enum(ReminderType), nullable=False)
    threshold = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
