// Creates a Stripe Checkout Session for the Find A Crib Plus ($1.99/mo)
// subscription. Requires a signed-in user (JWT verified by the platform).
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const STRIPE_SECRET = Deno.env.get("STRIPE_SECRET_KEY")!;
const PRICE_ID = Deno.env.get("STRIPE_PRICE_ID")!;

// Only our own origins may invoke checkout from a browser. The endpoint is
// already JWT-gated, so this is defense in depth against CSRF-style abuse.
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

function form(obj: Record<string, string>) {
  return new URLSearchParams(obj).toString();
}

Deno.serve(async (req) => {
  const cors = corsFor(req);
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const auth = req.headers.get("Authorization") || "";
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_ANON_KEY")!,
      { global: { headers: { Authorization: auth } } },
    );
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return new Response(JSON.stringify({ error: "not signed in" }), { status: 401, headers: { ...cors, "Content-Type": "application/json" } });

    const { return_url } = await req.json().catch(() => ({}));
    const base = return_url || "https://findacrib.com";
    const sep = base.includes("?") ? "&" : "?";

    const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${STRIPE_SECRET}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: form({
        mode: "subscription",
        "line_items[0][price]": PRICE_ID,
        "line_items[0][quantity]": "1",
        client_reference_id: user.id,
        customer_email: user.email ?? "",
        "subscription_data[metadata][user_id]": user.id,
        "metadata[user_id]": user.id,
        success_url: `${base}${sep}plus=success`,
        cancel_url: `${base}${sep}plus=cancel`,
        allow_promotion_codes: "true",
      }),
    });
    const session = await res.json();
    if (!res.ok) return new Response(JSON.stringify({ error: session?.error?.message || "stripe error" }), { status: 400, headers: { ...cors, "Content-Type": "application/json" } });
    return new Response(JSON.stringify({ url: session.url }), { headers: { ...cors, "Content-Type": "application/json" } });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), { status: 500, headers: { ...cors, "Content-Type": "application/json" } });
  }
});
