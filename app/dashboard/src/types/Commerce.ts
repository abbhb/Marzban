export type SubscriptionPlan = {
  id: number;
  name: string;
  description: string;
  price_minor: number;
  currency: "CNY";
  duration_days: number;
  data_limit: number;
  inbound_tags: string[];
  /** Present only on sudo administrator plan responses. */
  external_selections?: PlanExternalSelection[];
  is_visible: boolean;
  created_at: string;
  updated_at: string;
};

export type ExternalSelectionMode = "all" | "selected";

export type PlanExternalSelection = {
  source_id: number;
  mode: ExternalSelectionMode;
  node_ids: number[];
};

export type ExternalSubscriptionStatus =
  | "empty"
  | "ready"
  | "auth_required"
  | "error"
  | "disabled"
  | string;

/**
 * Safe administrator-facing projection. The upstream URL and proxy
 * credentials deliberately do not exist on this type, so list/detail queries
 * cannot accidentally put them into React Query or the rendered DOM.
 */
export type ExternalSubscriptionSource = {
  id: number;
  name: string;
  group_name: string;
  enabled: boolean;
  refresh_interval_minutes: number;
  credential_configured: boolean;
  node_count: number;
  skipped_node_count: number;
  status: ExternalSubscriptionStatus;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  next_refresh_at?: string | null;
  last_error_code?: string | null;
  created_at?: string;
  updated_at?: string;
};

/** Credential-free node metadata used only for selection and status views. */
export type ExternalSubscriptionNode = {
  id: number;
  name: string;
  proxy_type: string;
  is_active: boolean;
  position: number;
};

export type PortalSubscription = {
  id: number;
  plan_id: number;
  plan_name: string;
  price_paid_minor: number;
  currency: string;
  duration_days: number;
  data_limit: number;
  inbound_tags: string[];
  starts_at: string;
  expires_at: string;
  purchased_at: string;
  disabled_at?: string | null;
};

export type PortalUsage = {
  status?: "active" | "disabled" | "limited" | "expired" | "on_hold" | null;
  used_traffic: number;
  data_limit?: number | null;
  lifetime_used_traffic: number;
  expire?: number | null;
};

export type PortalAccount = {
  id: number;
  username: string;
  wallet_balance_minor: number;
  is_active: boolean;
  user_id?: number | null;
  created_at: string;
  subscription?: PortalSubscription | null;
  usage: PortalUsage;
};

export type WalletTransaction = {
  id: number;
  amount_minor: number;
  balance_after_minor: number;
  kind: "admin_credit" | "purchase_debit";
  actor_admin?: string | null;
  purchase_id?: number | null;
  note?: string | null;
  created_at: string;
};

export type PortalPurchaseResult = {
  purchase_id: number;
  replayed: boolean;
  wallet_balance_minor: number;
  subscription: PortalSubscription;
  usage: PortalUsage;
};

export type MgmaIssue = {
  url: string;
  issued_at: string;
  expires_at: string;
  ttl_seconds: number;
};

export type Invitation = {
  id: number;
  code_prefix: string;
  note: string;
  valid_from?: string | null;
  expires_at?: string | null;
  max_uses?: number | null;
  use_count: number;
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  last_used_at?: string | null;
};

export type CreatedInvitation = Invitation & {
  code: string;
};

export type IPBlock = {
  id: number;
  network: string;
  reason: string;
  source: "manual" | "portal_login" | "admin_login" | "portal_registration";
  is_active: boolean;
  expires_at?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  revoked_at?: string | null;
  revoked_by?: string | null;
};

export type PortalSecuritySettings = {
  id: number;
  auto_block_enabled: boolean;
  login_failure_limit: number;
  login_window_seconds: number;
  registration_failure_limit: number;
  registration_window_seconds: number;
  auto_block_seconds: number;
  updated_at: string;
};

export type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};
