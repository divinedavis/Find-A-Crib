// Pure decision logic for App Store Server Notifications V2 (no I/O), so the
// rules are unit-tested without Apple, Supabase or the network.

export const BUNDLE_ID = "com.divinedavis.findacrib";
export const APP_APPLE_ID = 6807549249;
export const PRODUCT_IDS = new Set(["com.divinedavis.findacrib.plus.monthly"]);

// Apple retries a failed delivery at 1, 12, 24, 48 and 72 h (~6.5 days). A
// payload signed longer ago than this is not a genuine (re)delivery.
export const MAX_NOTIFICATION_AGE_MS = 8 * 24 * 60 * 60 * 1000;

export type NotificationPayload = {
  notificationType: string;
  subtype?: string;
  notificationUUID?: string;
  signedDate?: number;
  data?: {
    environment?: string;
    appAppleId?: number;
    bundleId?: string;
    signedTransactionInfo?: string;
    signedRenewalInfo?: string;
  };
};

export type TransactionInfo = {
  bundleId?: string;
  productId?: string;
  originalTransactionId?: string | number;
  appAccountToken?: string;
  expiresDate?: number;
  revocationDate?: number;
  offerType?: number;
  offerDiscountType?: string;
  price?: number;
  environment?: string;
};

export type RenewalInfo = {
  gracePeriodExpiresDate?: number;
  autoRenewStatus?: number;
};

/** Is this notification for our app at all? (checked on verified fields) */
export function isOurs(p: NotificationPayload, tx: TransactionInfo | null): string | null {
  const bundle = tx?.bundleId ?? p.data?.bundleId;
  if (bundle !== BUNDLE_ID) return `bundle ${bundle}`;
  if (p.data?.appAppleId !== undefined && p.data.appAppleId !== APP_APPLE_ID && p.data.environment === "Production") {
    return `appAppleId ${p.data.appAppleId}`;
  }
  if (tx && (!tx.productId || !PRODUCT_IDS.has(tx.productId))) return `product ${tx.productId}`;
  return null;
}

export function environmentOf(p: NotificationPayload, tx: TransactionInfo | null): "Production" | "Sandbox" {
  return (p.data?.environment ?? tx?.environment) === "Production" ? "Production" : "Sandbox";
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** appAccountToken is only an identity when it is a well-formed UUID. */
export function tokenUserId(tx: TransactionInfo): string | null {
  const t = (tx.appAccountToken ?? "").trim();
  return UUID.test(t) ? t.toLowerCase() : null;
}

/**
 * The subscriptions row fields a verified notification implies — the same
 * status vocabulary apple-subscription writes when the app syncs.
 */
export function rowFor(
  p: NotificationPayload,
  tx: TransactionInfo,
  renewal: RenewalInfo | null,
  env: string,
  now = Date.now(),
) {
  let end = tx.expiresDate ?? null;
  // Billing retry with a grace period: Apple keeps access until the grace
  // date, so do we.
  const grace = renewal?.gracePeriodExpiresDate;
  if (grace && (!end || grace > end)) end = grace;
  const revoked = !!tx.revocationDate || p.notificationType === "REVOKE" || p.notificationType === "REFUND";
  const expired = p.notificationType === "EXPIRED" || p.notificationType === "GRACE_PERIOD_EXPIRED";
  const active = !!end && end > now && !revoked && !expired;
  const trial = tx.offerType === 1 && (tx.offerDiscountType === "FREE_TRIAL" || tx.price === 0);
  return {
    provider: "apple",
    plan: "plus",
    status: revoked ? "canceled" : !active ? "inactive" : trial ? "trialing" : "active",
    current_period_end: end ? new Date(end).toISOString() : null,
    apple_original_transaction_id: String(tx.originalTransactionId ?? ""),
    apple_product_id: tx.productId ?? null,
    apple_environment: env,
    updated_at: new Date(now).toISOString(),
    active,
  };
}
