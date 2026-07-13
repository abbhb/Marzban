export type SubscriptionPlan = {
  id: number;
  name: string;
  description: string;
  price_minor: number;
  currency: "CNY";
  duration_days: number;
  data_limit: number;
  inbound_tags: string[];
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
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
  assigned_plan_id?: number | null;
  user_id?: number | null;
  created_at: string;
  assigned_plan?: SubscriptionPlan | null;
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
