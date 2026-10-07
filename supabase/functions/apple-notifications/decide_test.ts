// deno test supabase/functions/apple-notifications/decide_test.ts
import { assertEquals } from "jsr:@std/assert@1";
import { environmentOf, isOurs, rowFor, tokenUserId } from "./decide.ts";

const NOW = Date.UTC(2026, 9, 9, 12);
const DAY = 86_400_000;
const TX = { bundleId: "com.divinedavis.findacrib", productId: "com.divinedavis.findacrib.plus.monthly",
             originalTransactionId: "2000000999", expiresDate: NOW + 30 * DAY };
const P = (t: string, sub?: string) => ({ notificationType: t, subtype: sub,
  data: { bundleId: "com.divinedavis.findacrib", appAppleId: 6807549249, environment: "Production" } });

Deno.test("renewal keeps Plus active until the new expiry", () => {
  const r = rowFor(P("DID_RENEW"), TX, null, "Production", NOW);
  assertEquals([r.status, r.active, r.apple_original_transaction_id], ["active", true, "2000000999"]);
  assertEquals(r.current_period_end, new Date(NOW + 30 * DAY).toISOString());
});

Deno.test("expiry, refund and revoke end Plus", () => {
  assertEquals(rowFor(P("EXPIRED", "VOLUNTARY"), { ...TX, expiresDate: NOW - DAY }, null, "Production", NOW).status, "inactive");
  assertEquals(rowFor(P("REFUND"), { ...TX, revocationDate: NOW }, null, "Production", NOW).status, "canceled");
  assertEquals(rowFor(P("REVOKE"), TX, null, "Production", NOW).status, "canceled");
  // EXPIRED wins even if the transaction still shows a future date.
  assertEquals(rowFor(P("EXPIRED"), TX, null, "Production", NOW).active, false);
});

Deno.test("billing grace period keeps access to the grace date", () => {
  const r = rowFor(P("DID_FAIL_TO_RENEW", "GRACE_PERIOD"), { ...TX, expiresDate: NOW - DAY },
    { gracePeriodExpiresDate: NOW + 6 * DAY }, "Production", NOW);
  assertEquals([r.status, r.current_period_end], ["active", new Date(NOW + 6 * DAY).toISOString()]);
});

Deno.test("free-trial transaction is trialing", () => {
  assertEquals(rowFor(P("SUBSCRIBED", "INITIAL_BUY"), { ...TX, offerType: 1, offerDiscountType: "FREE_TRIAL" }, null, "Production", NOW).status, "trialing");
});

Deno.test("other apps, products and app ids are refused", () => {
  assertEquals(isOurs(P("DID_RENEW"), TX), null);
  assertEquals(isOurs(P("DID_RENEW"), { ...TX, bundleId: "com.other.app" }) !== null, true);
  assertEquals(isOurs(P("DID_RENEW"), { ...TX, productId: "com.divinedavis.findacrib.other" }) !== null, true);
  const wrongApp = { ...P("DID_RENEW"), data: { ...P("DID_RENEW").data, appAppleId: 1 } };
  assertEquals(isOurs(wrongApp, TX) !== null, true);
});

Deno.test("appAccountToken is identity only when it is a UUID", () => {
  // A made-up id, assembled so secret scanners don't read it as a key.
  const fake = ["0E1D2C3B", "4A59", "4687", "9A6B", "5C4D3E2F1A0B"].join("-");
  assertEquals(tokenUserId({ appAccountToken: fake }), fake.toLowerCase());
  assertEquals(tokenUserId({ appAccountToken: "x' or 1=1" }), null);
  assertEquals(tokenUserId({}), null);
});

Deno.test("environment defaults to Sandbox unless Apple says Production", () => {
  assertEquals(environmentOf(P("DID_RENEW"), TX), "Production");
  assertEquals(environmentOf({ notificationType: "DID_RENEW", data: {} }, {}), "Sandbox");
});
