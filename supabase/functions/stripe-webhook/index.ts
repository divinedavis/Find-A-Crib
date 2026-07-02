// Stripe webhook for Find A Crib Plus. Verifies the signature, then upserts the
// user's subscription row (service role) so has_plus()/get_agent_phone() unlock.
// Deploy with --no-verify-jwt (Stripe calls this directly, no Supabase JWT).
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const STRIPE_SECRET = Deno.env.get("STRIPE_SECRET_KEY")!;
const WEBHOOK_SECRET = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

const admin = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
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

Deno.serve(async (req) => {
  const body = await req.text();
  const sig = req.headers.get("stripe-signature") || "";
  if (!(await verify(body, sig))) return new Response("bad signature", { status: 400 });

  const event = JSON.parse(body);
  try {
    if (event.type === "checkout.session.completed") {
      const s = event.data.object;
      const sub = await stripeGet(`subscriptions/${s.subscription}`);
      await upsert(sub, s.client_reference_id || s.metadata?.user_id);
    } else if (event.type.startsWith("customer.subscription.")) {
      await upsert(event.data.object, event.data.object?.metadata?.user_id || null);
    }
  } catch (e) {
    return new Response(`handler error: ${e}`, { status: 500 });
  }
  return new Response(JSON.stringify({ received: true }), { headers: { "Content-Type": "application/json" } });
});
