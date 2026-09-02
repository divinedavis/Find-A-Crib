// Find A Crib Plus bought in the iOS app. The app sends the signed transaction
// (JWS) StoreKit 2 hands it; this verifies Apple's signature and certificate
// chain with Apple's own library, checks it is OUR subscription, and upserts
// the caller's row in public.subscriptions — the same row has_plus() reads for
// Stripe subscribers, so the web and the app agree.
//
// Trust boundary: the caller's Supabase JWT says WHO; Apple's signature says
// WHAT was bought. The app cannot forge either. One Apple subscription can
// only ever belong to one account (unique index on the original transaction
// id) — a second account presenting the same token is refused.
//
// Deploy: supabase functions deploy apple-subscription --project-ref dbaifotzwlxjvsxjohjt
import { createClient } from "npm:@supabase/supabase-js@2";
import { SignedDataVerifier, Environment } from "npm:@apple/app-store-server-library@1";

const BUNDLE_ID = "com.divinedavis.findacrib";
const PRODUCT_IDS = new Set(["com.divinedavis.findacrib.plus.monthly"]);
// Apple Root CA - G3 (DER, base64). Public certificate; pinned so a verifier
// cannot be talked into trusting anything else.
const APPLE_ROOT_G3_B64 = "MIICQzCCAcmgAwIBAgIILcX8iNLFS5UwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwSQXBwbGUgUm9vdCBDQSAtIEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcNMTQwNDMwMTgxOTA2WhcNMzkwNDMwMTgxOTA2WjBnMRswGQYDVQQDDBJBcHBsZSBSb290IENBIC0gRzMxJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUzB2MBAGByqGSM49AgEGBSuBBAAiA2IABJjpLz1AcqTtkyJygRMc3RCV8cWjTnHcFBbZDuWmBSp3ZHtfTjjTuxxEtX/1H7YyYl3J6YRbTzBPEVoA/VhYDKX1DyxNB0cTddqXl5dvMVztK517IDvYuVTZXpmkOlEKMaNCMEAwHQYDVR0OBBYEFLuw3qFYM4iapIqZ3r6966/ayySrMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMDA2gAMGUCMQCD6cHEFl4aXTQY2e3v9GwOAEZLuN+yRhHFD/3meoyhpmvOwgPUnPWTxnS4at+qIxUCMG1mihDK1A3UT82NQz60imOlM27jbdoXt2QfyFMm+YhidDkLF1vLUagM6BgD56KyKA==";
const ROOTS = [Uint8Array.from(atob(APPLE_ROOT_G3_B64), (c) => c.charCodeAt(0))];

const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

async function verifyEither(jws: string) {
  // App Review and TestFlight run in the Sandbox; customers in Production.
  // Try Production first, fall back to Sandbox; report which one signed it.
  for (const env of [Environment.PRODUCTION, Environment.SANDBOX]) {
    try {
      const v = new SignedDataVerifier(ROOTS, true, env, BUNDLE_ID);
      const tx = await v.verifyAndDecodeTransaction(jws);
      return { tx, env: env === Environment.PRODUCTION ? "Production" : "Sandbox" };
    } catch (_e) { /* try the other environment */ }
  }
  return null;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("method", { status: 405 });
  const auth = req.headers.get("Authorization") ?? "";
  const userClient = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!,
    { global: { headers: { Authorization: auth } } });
  const { data: { user }, error: uerr } = await userClient.auth.getUser();
  if (uerr || !user) return new Response("not signed in", { status: 401 });

  let body: { jws?: string };
  try { body = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
  if (!body.jws || typeof body.jws !== "string" || body.jws.length > 20000) return new Response("missing jws", { status: 400 });

  const verified = await verifyEither(body.jws);
  if (!verified) return new Response("transaction did not verify", { status: 400 });
  const { tx, env } = verified;
  if (tx.bundleId !== BUNDLE_ID || !tx.productId || !PRODUCT_IDS.has(tx.productId)) {
    return new Response("not a Find A Crib Plus transaction", { status: 400 });
  }
  const expires = tx.expiresDate ? new Date(tx.expiresDate) : null;
  const revoked = !!tx.revocationDate;
  const active = !!expires && expires.getTime() > Date.now() && !revoked;
  const row = {
    user_id: user.id,
    provider: "apple",
    plan: "plus",
    status: revoked ? "canceled" : active ? "active" : "inactive",
    current_period_end: expires ? expires.toISOString() : null,
    apple_original_transaction_id: String(tx.originalTransactionId),
    apple_product_id: tx.productId,
    apple_environment: env,
    updated_at: new Date().toISOString(),
  };
  // Another account already owns this Apple subscription? Refuse rather than
  // move it — moving would let a shared Apple ID hand Plus around.
  const { data: owner } = await admin.from("subscriptions").select("user_id")
    .eq("apple_original_transaction_id", row.apple_original_transaction_id).maybeSingle();
  if (owner && owner.user_id !== user.id) return new Response("subscription belongs to another account", { status: 409 });
  // Don't let an expired Apple token overwrite a live Stripe subscription.
  const { data: mine } = await admin.from("subscriptions").select("provider,status,current_period_end").eq("user_id", user.id).maybeSingle();
  if (mine && mine.provider === "stripe" && mine.status === "active" && !active) {
    return Response.json({ has_plus: true, provider: "stripe" });
  }
  const { error } = await admin.from("subscriptions").upsert(row, { onConflict: "user_id" });
  if (error) return new Response("db: " + error.message, { status: 500 });
  return Response.json({ has_plus: active, provider: "apple", expires: row.current_period_end, environment: env });
});
