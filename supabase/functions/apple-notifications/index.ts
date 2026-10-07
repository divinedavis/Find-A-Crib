// POST /functions/v1/apple-notifications — App Store Server Notifications V2.
//
// Why (security audit 2026-10-07, L13): Find A Crib Plus bought in the iPhone
// app reached the server ONLY when the app later synced the receipt
// (apple-subscription). Two real subscribers from 9/9-9/10 never opened a
// fixed build signed in, so public.subscriptions had no App Store rows at all,
// and renewals, refunds and expiries were invisible. Apple now tells us.
//
// Trust: this endpoint is public (verify_jwt = false — Apple sends no Supabase
// JWT). Nothing is read until the outer signedPayload AND the nested
// signedTransactionInfo / signedRenewalInfo verify against the pinned Apple
// Root CA - G3 with the App Store leaf + WWDR intermediate OIDs (appleJWS.ts),
// and a stale signedDate is refused as a replay. Then bundle id, app id and
// product are pinned.
//
// Identity, in order: an existing row with the same original transaction id
// (written when the app synced); else appAccountToken when it is the id of a
// real account. Otherwise the notification is only logged
// (public.apple_notifications, service-role only) so an unmatched paying
// subscriber is visible on the next look rather than silently dropped.
// Sandbox notifications change rows only for APPLE_SANDBOX_USER_IDS (the same
// allowlist apple-subscription uses).
import { createClient } from "npm:@supabase/supabase-js@2";
import { JWSVerificationError, verifyAppleJWS } from "./appleJWS.ts";
import {
  environmentOf, isOurs, MAX_NOTIFICATION_AGE_MS, type NotificationPayload,
  type RenewalInfo, rowFor, tokenUserId, type TransactionInfo,
} from "./decide.ts";
import { mayGrant, parseAllowlist } from "../apple-subscription/sandbox.ts";

const SANDBOX_ALLOW = parseAllowlist(Deno.env.get("APPLE_SANDBOX_USER_IDS"));
const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  { auth: { persistSession: false } });

async function log(p: NotificationPayload, tx: TransactionInfo | null, env: string, outcome: string, userId: string | null) {
  const { error } = await admin.from("apple_notifications").upsert({
    notification_uuid: p.notificationUUID ?? crypto.randomUUID(),
    notification_type: p.notificationType,
    subtype: p.subtype ?? null,
    environment: env,
    original_transaction_id: tx?.originalTransactionId != null ? String(tx.originalTransactionId) : null,
    product_id: tx?.productId ?? null,
    expires_at: tx?.expiresDate ? new Date(tx.expiresDate).toISOString() : null,
    signed_at: p.signedDate ? new Date(p.signedDate).toISOString() : null,
    user_id: userId,
    outcome,
  }, { onConflict: "notification_uuid" });
  if (error) console.error("apple-notifications log failed:", error.message);
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("method", { status: 405 });
  const raw = await req.text();
  if (raw.length > 100_000) return new Response("too large", { status: 413 });
  let body: { signedPayload?: unknown };
  try { body = JSON.parse(raw); } catch { return new Response("bad json", { status: 400 }); }
  if (typeof body?.signedPayload !== "string") return new Response("missing signedPayload", { status: 400 });

  let p: NotificationPayload;
  let tx: TransactionInfo | null = null;
  let renewal: RenewalInfo | null = null;
  try {
    p = await verifyAppleJWS<NotificationPayload>(body.signedPayload, { maxAgeMs: MAX_NOTIFICATION_AGE_MS });
    if (p.data?.signedTransactionInfo) tx = await verifyAppleJWS<TransactionInfo>(p.data.signedTransactionInfo);
    if (p.data?.signedRenewalInfo) renewal = await verifyAppleJWS<RenewalInfo>(p.data.signedRenewalInfo);
  } catch (e) {
    if (e instanceof JWSVerificationError) {
      console.warn("apple-notifications: rejected:", e.message);
      return new Response("invalid signature", { status: 400 });
    }
    throw e;
  }

  const env = environmentOf(p, tx);
  if (p.notificationType === "TEST") {
    if (p.data?.bundleId !== undefined && p.data.bundleId !== "com.divinedavis.findacrib") {
      return new Response("bundle mismatch", { status: 400 });
    }
    await log(p, null, env, "test", null);
    return new Response("ok");
  }
  const notOurs = isOurs(p, tx);
  if (notOurs) {
    console.warn("apple-notifications: not ours:", notOurs);
    return new Response("not ours", { status: 400 });
  }
  if (!tx) { await log(p, null, env, "no-transaction", null); return new Response("ok"); }

  const otid = String(tx.originalTransactionId ?? "");
  let userId: string | null = null;
  if (otid) {
    const { data } = await admin.from("subscriptions").select("user_id")
      .eq("apple_original_transaction_id", otid).maybeSingle();
    userId = data?.user_id ?? null;
  }
  if (!userId) {
    const t = tokenUserId(tx);
    if (t) {
      const { data } = await admin.auth.admin.getUserById(t);
      if (data?.user) userId = data.user.id;
    }
  }
  if (!userId) { await log(p, tx, env, "unmatched", null); return new Response("ok"); }
  if (!mayGrant(env, userId, SANDBOX_ALLOW)) { await log(p, tx, env, "sandbox-not-allowlisted", userId); return new Response("ok"); }

  const { active, ...row } = rowFor(p, tx, renewal, env);
  // Never let an Apple notification overwrite a live Stripe subscription.
  const { data: mine } = await admin.from("subscriptions").select("provider,status")
    .eq("user_id", userId).maybeSingle();
  if (mine && mine.provider === "stripe" && mine.status === "active" && !active) {
    await log(p, tx, env, "kept-stripe", userId);
    return new Response("ok");
  }
  const { error } = await admin.from("subscriptions").upsert({ user_id: userId, ...row }, { onConflict: "user_id" });
  if (error) {
    console.error("apple-notifications upsert failed:", error.message);
    return new Response("db", { status: 500 });   // Apple retries
  }
  await log(p, tx, env, `updated:${row.status}`, userId);
  return new Response("ok");
});
