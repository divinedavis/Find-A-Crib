// Stripe webhook for Find A Crib Plus. Verifies the signature, then upserts the
// user's subscription row (service role) so has_plus()/get_agent_phone() unlock.
// Deploy with --no-verify-jwt (Stripe calls this directly, no Supabase JWT).
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const STRIPE_SECRET = Deno.env.get("STRIPE_SECRET_KEY")!;
const WEBHOOK_SECRET = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

const admin = createClient(
  Deno.env.get("SUPABASE_URL")!,
  (Deno.env.get("FAC_SECRET_KEY") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!),
);

// Verify the Stripe-Signature header against the raw body (HMAC-SHA256).
async function verify(body: string, header: string): Promise<boolean> {
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  const t = parts["t"], sig = parts["v1"];
  if (!t || !sig) return false;
  // Reject stale/replayed events: the signed timestamp must be within 5 minutes,
  // matching Stripe's own default tolerance.
  const ts = Number(t);
  if (!Number.isFinite(ts) || Math.abs(Date.now() / 1000 - ts) > 300) return false;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(WEBHOOK_SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${t}.${body}`));
  const expected = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  // constant-time-ish compare
  if (expected.length !== sig.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ sig.charCodeAt(i);
  return diff === 0;
}

async function stripeGet(path: string) {
  const r = await fetch(`https://api.stripe.com/v1/${path}`, {
    headers: { Authorization: `Bearer ${STRIPE_SECRET}` },
  });
  return r.json();
}

async function upsert(sub: any, userId: string | null) {
  const uid = userId || sub?.metadata?.user_id;
  if (!uid) return;
  await admin.from("subscriptions").upsert({
    user_id: uid,
    stripe_customer_id: sub.customer,
    stripe_subscription_id: sub.id,
    status: sub.status,
    plan: "plus",
    current_period_end: sub.current_period_end ? new Date(sub.current_period_end * 1000).toISOString() : null,
    updated_at: new Date().toISOString(),
  }, { onConflict: "user_id" });
}

// What the first charge after the trial will be, in the smallest currency
// unit. Stripe's invoice preview knows about promotion codes and quantity;
// the price on the item is the fallback if the preview call fails.
async function nextCharge(sub: any): Promise<{ amount: number; currency: string; interval: string }> {
  const item = sub?.items?.data?.[0];
  const price = item?.price ?? {};
  const fallback = {
    amount: Number(price.unit_amount ?? 0) * Number(item?.quantity ?? 1),
    currency: String(price.currency ?? "usd"),
    interval: String(price.recurring?.interval ?? "month"),
  };
  try {
    const r = await fetch("https://api.stripe.com/v1/invoices/create_preview", {
      method: "POST",
      headers: { Authorization: `Bearer ${STRIPE_SECRET}`, "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ subscription: sub.id }).toString(),
    });
    const inv = await r.json();
    if (r.ok && Number.isFinite(inv?.amount_due)) {
      return { ...fallback, amount: Number(inv.amount_due), currency: String(inv.currency ?? fallback.currency) };
    }
  } catch { /* fall back to the price */ }
  return fallback;
}

// The trial-ending reminder (CA Bus. & Prof. Code 17602, FTC ROSCA;
// 2026-11-07). Stripe fires customer.subscription.trial_will_end three days
// before a trial converts. Record it in billing_notices; billing_notices.py
// on the droplet mails it within ten minutes through growth/emailkit (the
// house look + the postal footer) and stamps sent_at. A resent event is a
// no-op: the table is unique on (subscription, trial_end, kind).
async function recordTrialEnding(event: any) {
  const sub = event.data.object;
  // Already set to cancel: nothing will be charged, so nothing to warn about.
  if (!sub?.trial_end || sub.status !== "trialing" || sub.cancel_at_period_end || sub.cancel_at) return;
  const uid: string | null = sub?.metadata?.user_id ?? null;
  let email = "";
  if (uid) {
    const { data } = await admin.auth.admin.getUserById(uid);
    email = data?.user?.email ?? "";
  }
  if (!email && sub.customer) {
    const cust = await stripeGet(`customers/${sub.customer}`);
    email = cust?.email ?? "";
  }
  if (!email) throw new Error(`trial_will_end ${sub.id}: no email on the account or the customer`);
  const charge = await nextCharge(sub);
  const { error } = await admin.from("billing_notices").upsert({
    kind: "trial_will_end",
    stripe_event_id: event.id,
    stripe_subscription_id: sub.id,
    stripe_customer_id: sub.customer ?? null,
    user_id: uid,
    email,
    amount_cents: charge.amount,
    currency: charge.currency,
    interval: charge.interval,
    trial_end: new Date(sub.trial_end * 1000).toISOString(),
  }, { onConflict: "stripe_subscription_id,trial_end,kind", ignoreDuplicates: true });
  if (error) throw new Error(`billing_notices: ${error.message}`);
}

// Keys (2026-10-25 rotation): the dedicated publishable/secret keys, set
// as function secrets; the legacy JWT keys only as a fallback until the
// legacy anon/service_role keys are disabled.
Deno.serve(async (req) => {
  const body = await req.text();
  const sig = req.headers.get("stripe-signature") || "";
  if (!(await verify(body, sig))) return new Response("bad signature", { status: 400 });

  const event = JSON.parse(body);
  try {
    if (event.type === "checkout.session.completed") {
      const s = event.data.object;
      // One-time purchases (the $9 building report) also fire this event, and
      // they carry no subscription. Without this guard we'd fetch
      // `subscriptions/null`, throw, and hand Stripe a 500 on every report
      // sale — and Stripe disables endpoints that keep failing, which would
      // take real Plus subscriptions down with it. Not our event: ack and stop.
      if (s.mode !== "subscription" || !s.subscription) {
        return new Response(JSON.stringify({ received: true, ignored: "not a subscription" }),
                            { headers: { "Content-Type": "application/json" } });
      }
      const sub = await stripeGet(`subscriptions/${s.subscription}`);
      await upsert(sub, s.client_reference_id || s.metadata?.user_id);
    } else if (event.type.startsWith("customer.subscription.")) {
      if (event.type === "customer.subscription.trial_will_end") await recordTrialEnding(event);
      await upsert(event.data.object, event.data.object?.metadata?.user_id || null);
    }
  } catch (e) {
    return new Response(`handler error: ${e}`, { status: 500 });
  }
  return new Response(JSON.stringify({ received: true }), { headers: { "Content-Type": "application/json" } });
});
