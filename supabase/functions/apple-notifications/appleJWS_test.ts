// deno test --allow-net --allow-read supabase/functions/apple-notifications/
// (copied from Baseball-Stat-Tracker supabase/tests/appleJWS.test.ts)
//
// Verifies the App Store JWS checks in storekit-webhook/appleJWS.ts:
//  - a REAL Apple-signed notification (captured fixture) passes, pinned root
//  - forged chains fail: wrong root, missing leaf OID, missing intermediate
//    OID, wrong chain length
//  - a chain WITH both OIDs under a test root passes (proves the OID check,
//    not something else, is what rejects the forged ones)
//  - stale / future signedDate rejected when maxAgeMs is set

import { assertEquals, assertRejects } from "jsr:@std/assert@1";
import * as x509 from "https://esm.sh/@peculiar/x509@1.12.3";
import { CompactSign } from "https://esm.sh/jose@5.9.6";
import {
  APP_STORE_LEAF_OID,
  APPLE_WWDR_INTERMEDIATE_OID,
  JWSVerificationError,
  verifyAppleJWS,
} from "./appleJWS.ts";

x509.cryptoProvider.set(crypto);

const fixture = JSON.parse(
  await Deno.readTextFile(new URL("./fixtures/apple_test_notification.json", import.meta.url)),
);

function payloadOf(jws: string): Record<string, unknown> {
  const b = jws.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(atob(b + "=".repeat((4 - (b.length % 4)) % 4)));
}

const realSignedDate = payloadOf(fixture.signedPayload).signedDate as number;
const atSigning = new Date(realSignedDate + 60_000);
const DAY = 24 * 60 * 60 * 1000;

Deno.test("real Apple-signed notification verifies against pinned G3 root", async () => {
  const p = await verifyAppleJWS<{ notificationType: string; data: { bundleId: string } }>(
    fixture.signedPayload,
    { now: atSigning, maxAgeMs: 8 * DAY },
  );
  assertEquals(p.notificationType, "TEST");
  assertEquals(p.data.bundleId, "com.divinedavis.BaseballStatTracker");
});

Deno.test("real notification replayed after the retry window is rejected", async () => {
  await assertRejects(
    () => verifyAppleJWS(fixture.signedPayload, {
      now: new Date(realSignedDate + 9 * DAY),
      maxAgeMs: 8 * DAY,
    }),
    JWSVerificationError,
    "too old",
  );
});

Deno.test("signedDate in the future is rejected", async () => {
  await assertRejects(
    () => verifyAppleJWS(fixture.signedPayload, {
      now: new Date(realSignedDate - 10 * 60_000),
      maxAgeMs: 8 * DAY,
    }),
    JWSVerificationError,
  );
});

// ---- forged chains -------------------------------------------------------

const alg = { name: "ECDSA", namedCurve: "P-256", hash: "SHA-256" } as const;
const NULL_DER = new Uint8Array([0x05, 0x00]);

async function makeCert(opts: {
  name: string;
  issuer?: { name: string; keys: CryptoKeyPair };
  ca: boolean;
  oids?: string[];
}) {
  const keys = await crypto.subtle.generateKey(alg, true, ["sign", "verify"]) as CryptoKeyPair;
  const now = Date.now();
  const cert = await x509.X509CertificateGenerator.create({
    serialNumber: crypto.randomUUID().replace(/-/g, "").slice(0, 16),
    subject: `CN=${opts.name}`,
    issuer: `CN=${opts.issuer?.name ?? opts.name}`,
    notBefore: new Date(now - DAY),
    notAfter: new Date(now + 365 * DAY),
    signingAlgorithm: alg,
    publicKey: keys.publicKey,
    signingKey: (opts.issuer?.keys ?? keys).privateKey,
    extensions: [
      new x509.BasicConstraintsExtension(opts.ca, undefined, true),
      ...(opts.oids ?? []).map((oid) => new x509.Extension(oid, false, NULL_DER)),
    ],
  });
  return { name: opts.name, keys, cert };
}

async function forge(opts: { leafOid: boolean; interOid: boolean; chainLen?: number }) {
  const root = await makeCert({ name: "Forged Root", ca: true });
  const inter = await makeCert({
    name: "Forged Intermediate",
    issuer: root,
    ca: true,
    oids: opts.interOid ? [APPLE_WWDR_INTERMEDIATE_OID] : [],
  });
  const leaf = await makeCert({
    name: "Forged Leaf",
    issuer: inter,
    ca: false,
    oids: opts.leafOid ? [APP_STORE_LEAF_OID] : [],
  });
  const b64 = (c: x509.X509Certificate) => btoa(String.fromCharCode(...new Uint8Array(c.rawData)));
  let x5c = [b64(leaf.cert), b64(inter.cert), b64(root.cert)];
  if (opts.chainLen === 2) x5c = x5c.slice(0, 2);
  const body = {
    notificationType: "SUBSCRIBED",
    signedDate: Date.now(),
    data: { bundleId: "com.divinedavis.BaseballStatTracker" },
  };
  const jws = await new CompactSign(new TextEncoder().encode(JSON.stringify(body)))
    .setProtectedHeader({ alg: "ES256", x5c })
    .sign(leaf.keys.privateKey);
  return { jws, root: root.cert };
}

Deno.test("forged chain (both OIDs) is rejected against the pinned Apple root", async () => {
  const { jws } = await forge({ leafOid: true, interOid: true });
  await assertRejects(() => verifyAppleJWS(jws), JWSVerificationError, "Apple Root");
});

Deno.test("chain with both OIDs passes when its own root is trusted (control)", async () => {
  const { jws, root } = await forge({ leafOid: true, interOid: true });
  const p = await verifyAppleJWS<{ notificationType: string }>(jws, { root, maxAgeMs: DAY });
  assertEquals(p.notificationType, "SUBSCRIBED");
});

Deno.test("trusted-root chain WITHOUT the App Store leaf OID is rejected", async () => {
  const { jws, root } = await forge({ leafOid: false, interOid: true });
  await assertRejects(() => verifyAppleJWS(jws, { root }), JWSVerificationError, "App Store signing");
});

Deno.test("trusted-root chain WITHOUT the WWDR intermediate OID is rejected", async () => {
  const { jws, root } = await forge({ leafOid: true, interOid: false });
  await assertRejects(() => verifyAppleJWS(jws, { root }), JWSVerificationError, "WWDR");
});

Deno.test("trusted-root chain with no OIDs at all is rejected", async () => {
  const { jws, root } = await forge({ leafOid: false, interOid: false });
  await assertRejects(() => verifyAppleJWS(jws, { root }), JWSVerificationError);
});

Deno.test("2-cert chain is rejected", async () => {
  const { jws, root } = await forge({ leafOid: true, interOid: true, chainLen: 2 });
  await assertRejects(() => verifyAppleJWS(jws, { root }), JWSVerificationError, "exactly 3");
});

Deno.test("tampered real payload fails signature check", async () => {
  const [h, p, s] = fixture.signedPayload.split(".");
  const forgedBody = btoa(JSON.stringify({ ...payloadOf(fixture.signedPayload), notificationType: "SUBSCRIBED" }))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  await assertRejects(
    () => verifyAppleJWS(`${h}.${forgedBody}.${s}`, { now: atSigning }),
    JWSVerificationError,
    "signature",
  );
  void p;
});
