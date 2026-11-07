// Opens a Stripe Customer Portal session so a web Plus member can cancel
// online, update their card or see invoices (2026-11-07, California's
// automatic renewal law, Bus. & Prof. Code 17602(c), and the FTC's ROSCA:
// a subscription bought online must be cancellable online).
//
// Authorization: the caller's Supabase session says WHO; the Stripe customer
// comes ONLY from that user's own public.subscriptions row (written by the
// stripe-webhook with the service role). The request body can't name a
// customer, so nobody can open someone else's billing. App Store
// subscriptions are refused with provider "apple": those are managed in
// iOS Settings, not by us.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const STRIPE_SECRET = Deno.env.get("STRIPE_SECRET_KEY")!;
// The live portal configuration (subscription_cancel on, at period end),
// created by API on 2026-11-07. Not a secret; the env var can override it.
const PORTAL_CONFIG = Deno.env.get("STRIPE_PORTAL_CONFIG") ?? "bpc_1UZGCJLiz3X1poCpmdTyJsF2";

const ALLOWED = new Set([
  "https://findacrib.com",
  "https://www.findacrib.com",
]);
function corsFor(req: Request) {
  const origin = req.headers.get("Origin") || "";
  return {
    "Access-Control-Allow-Origin": ALLOWED.has(origin) ? origin : "https://findacrib.com",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

// Stripe sends the member back here when they leave the portal, so the
// same open-redirect guard as create-checkout: our origins only.
const DEFAULT_RETURN = "https://findacrib.com/";
function safeReturn(raw: unknown): string {
  if (typeof raw !== "string" || raw.length > 2048) return DEFAULT_RETURN;
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:" || !ALLOWED.has(u.origin)) return DEFAULT_RETURN;
    if (u.username || u.password) return DEFAULT_RETURN;
    u.hash = "";
    return u.toString();
  } catch {
    return DEFAULT_RETURN;
  }
}

// Best-effort per-user limit (per isolate): a member opens this a handful of
// times at most; anything faster is a script. Stripe's own limits sit behind.
const HITS = new Map<string, number[]>();
function limited(uid: string, max = 10, windowMs = 10 * 60_000): boolean {
  const now = Date.now();
  const recent = (HITS.get(uid) ?? []).filter((t) => now - t < windowMs);
  recent.push(now);
  HITS.set(uid, recent);
  if (HITS.size > 5000) for (const [k, v] of HITS) if (!v.length || now - v[v.length - 1] > windowMs) HITS.delete(k);
  return recent.length > max;
}

async function stripe(path: string, body?: Record<string, string>) {
  const r = await fetch(`https://api.stripe.com/v1/${path}`, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${STRIPE_SECRET}`,
      ...(body ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
    },
    body: body ? new URLSearchParams(body).toString() : undefined,
  });
  return { ok: r.ok, json: await r.json() };
}

Deno.serve(async (req) => {
  const cors = corsFor(req);
  const reply = (status: number, obj: unknown) =>
    new Response(JSON.stringify(obj), { status, headers: { ...cors, "Content-Type": "application/json" } });
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return reply(405, { error: "method not allowed" });
  try {
    const auth = req.headers.get("Authorization") || "";
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      (Deno.env.get("FAC_PUBLISHABLE_KEY") ?? Deno.env.get("SUPABASE_ANON_KEY")!),
      { global: { headers: { Authorization: auth } } },
    );
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return reply(401, { error: "not signed in" });
    if (limited(user.id)) return reply(429, { error: "too many requests" });

    // Service role for the read, so RLS can't be the reason a member is
    // refused — the filter is the verified user id, nothing from the body.
    const admin = createClient(
      Deno.env.get("SUPABASE_URL")!,
      (Deno.env.get("FAC_SECRET_KEY") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!),
    );
    const { data: row, error } = await admin.from("subscriptions")
      .select("provider,stripe_customer_id,stripe_subscription_id")
      .eq("user_id", user.id).maybeSingle();
    if (error) return reply(503, { error: "temporarily unavailable" });
    if (row?.provider === "apple") return reply(409, { error: "app store", provider: "apple" });
    const customer = row?.stripe_customer_id;
    if (!customer || !/^cus_[A-Za-z0-9]+$/.test(customer)) return reply(404, { error: "no web subscription" });

    // Defense in depth: the subscription on file must belong to this
    // customer and, when Stripe has it, to this user.
    if (row?.stripe_subscription_id) {
      const sub = await stripe(`subscriptions/${encodeURIComponent(row.stripe_subscription_id)}`);
      const owner = sub.json?.metadata?.user_id;
      if (!sub.ok || sub.json?.customer !== customer || (owner && owner !== user.id)) {
        return reply(403, { error: "subscription does not match this account" });
      }
    }

    const { return_url } = await req.json().catch(() => ({}));
    const s = await stripe("billing_portal/sessions", {
      customer,
      configuration: PORTAL_CONFIG,
      return_url: safeReturn(return_url),
    });
    if (!s.ok || !s.json?.url) return reply(502, { error: "stripe error" });
    return reply(200, { url: s.json.url });
  } catch (_e) {
    return reply(500, { error: "server error" });
  }
});
