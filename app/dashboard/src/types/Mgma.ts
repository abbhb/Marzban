export type SubscriptionMode = "legacy" | "dual" | "ephemeral";

export type SubscriptionSourceMode =
  | "any"
  | "china"
  | "custom"
  | "china_or_custom";

export type MgmaGrant = {
  url: string;
  issued_at: string;
  expires_at: string;
  ttl_seconds: number;
  // Set by the dashboard when the issuance request starts; never serialized.
  client_requested_at_ms?: number;
};

export type SubscriptionSecuritySettings = {
  mode: SubscriptionMode;
  ttl_seconds: number;
  single_use: boolean;
  source_mode: SubscriptionSourceMode;
  custom_cidrs: string[];
  pepper_configured: boolean;
  cn_cidr_version: string | null;
  cn_cidr_count: number;
};

export type SubscriptionSecuritySettingsUpdate = Pick<
  SubscriptionSecuritySettings,
  "mode" | "ttl_seconds" | "single_use" | "source_mode" | "custom_cidrs"
>;
