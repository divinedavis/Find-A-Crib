// Copied from Baseball-Stat-Tracker supabase/functions/storekit-webhook/appleJWS.ts
// (hardened 2026-10-07: App Store leaf/WWDR OIDs, exact 3-cert chain, stale
// signedDate rejection). Keep the two in step.
//
// Apple App Store Server Notifications V2 — JWS verification.
//
// Apple signs the outer `signedPayload` and the nested `signedTransactionInfo`
// / `signedRenewalInfo` as JWS (ES256) whose protected header carries an `x5c`
// certificate chain: [leaf, intermediate, Apple App Store CA / root...].
//
// To trust ANY field we MUST, before reading it:
//   1. Parse the protected header and read the x5c chain.
//   2. Verify the chain links cryptographically (each cert signed by the next).
//   3. Verify the chain terminates at Apple's pinned Root CA - G3.
//   4. Verify every cert in the chain is within its validity window.
//   5. Verify the leaf and intermediate carry Apple's App Store marker OIDs
//      (leaf 1.2.840.113635.100.6.11.1 = App Store receipt signing,
//      intermediate 1.2.840.113635.100.6.2.1 = Apple WWDR CA). Apple Root CA
//      - G3 anchors MANY Apple PKIs (Apple Pay, Wallet, developer certs...);
//      without the OID checks any cert Apple ever issued under G3 — including
//      ones whose private key sits with a third party — could sign a payload
//      we would accept. Apple's app-store-server-library enforces both.
//   6. Verify the JWS signature itself with the *leaf* cert's public key.
//   7. (Outer notification only) reject a stale or future signedDate so an
//      old captured notification cannot be replayed to re-grant a tier.
//
// Only the leaf public key (validated by the chain) is allowed to sign the
// payload, so a forged/self-signed payload is rejected before any DB write.
//
// We use `@peculiar/x509` for X.509 parsing + chain signature verification and
// `jose` for the ES256 JWS verification. Both run on the Supabase edge runtime.

import * as x509 from "https://esm.sh/@peculiar/x509@1.12.3";
import {
  importX509,
  compactVerify,
  decodeProtectedHeader,
} from "https://esm.sh/jose@5.9.6";

x509.cryptoProvider.set(crypto);

// Apple Root CA - G3 (the App Store Server Notifications signing chain anchors
// here). Pinned by value — fetched from
// https://www.apple.com/certificateauthority/AppleRootCA-G3.cer
// SHA-256 fingerprint:
//   63:34:3A:BF:B8:9A:6A:03:EB:B5:7E:9B:3F:5F:A7:BE:7C:4F:5C:75:6F:30:17:B3:A8:C4:88:C3:65:3E:91:79
const APPLE_ROOT_CA_G3_DER_B64 =
  "MIICQzCCAcmgAwIBAgIILcX8iNLFS5UwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwS" +
  "QXBwbGUgUm9vdCBDQSAtIEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9u" +
  "IEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcN" +
  "MTQwNDMwMTgxOTA2WhcNMzkwNDMwMTgxOTA2WjBnMRswGQYDVQQDDBJBcHBsZSBS" +
  "b290IENBIC0gRzMxJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9y" +
  "aXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUzB2MBAGByqGSM49" +
  "AgEGBSuBBAAiA2IABJjpLz1AcqTtkyJygRMc3RCV8cWjTnHcFBbZDuWmBSp3ZHtf" +
  "TjjTuxxEtX/1H7YyYl3J6YRbTzBPEVoA/VhYDKX1DyxNB0cTddqXl5dvMVztK517" +
  "IDvYuVTZXpmkOlEKMaNCMEAwHQYDVR0OBBYEFLuw3qFYM4iapIqZ3r6966/ayySr" +
  "MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMDA2gA" +
  "MGUCMQCD6cHEFl4aXTQY2e3v9GwOAEZLuN+yRhHFD/3meoyhpmvOwgPUnPWTxnS4" +
  "at+qIxUCMG1mihDK1A3UT82NQz60imOlM27jbdoXt2QfyFMm+YhidDkLF1vLUagM" +
  "6BgD56KyKA==";

const APPLE_ROOT_CA_G3 = new x509.X509Certificate(
  Uint8Array.from(atob(APPLE_ROOT_CA_G3_DER_B64), (c) => c.charCodeAt(0)),
);

// Marker OIDs from Apple's app-store-server-library (ChainVerifier).
export const APP_STORE_LEAF_OID = "1.2.840.113635.100.6.11.1";
export const APPLE_WWDR_INTERMEDIATE_OID = "1.2.840.113635.100.6.2.1";

export class JWSVerificationError extends Error {}

export type VerifyOptions = {
  /** Clock used for cert validity + signedDate checks (tests pin it). */
  now?: Date;
  /** Trust anchor; defaults to the pinned Apple Root CA - G3 (tests swap it). */
  root?: x509.X509Certificate;
  /**
   * When set, the verified payload must carry a numeric `signedDate` (ms)
   * no older than this and no more than CLOCK_SKEW_MS in the future.
   */
  maxAgeMs?: number;
};

const CLOCK_SKEW_MS = 5 * 60 * 1000;

function hasExtension(cert: x509.X509Certificate, oid: string): boolean {
  return cert.extensions.some((e) => e.type === oid);
}

function derToPem(certB64: string): string {
  const lines = certB64.match(/.{1,64}/g)?.join("\n") ?? certB64;
  return `-----BEGIN CERTIFICATE-----\n${lines}\n-----END CERTIFICATE-----`;
}

// Validate the x5c chain: every cert in date range, each link signed by the
// next, and the final cert signed by (or equal to) the pinned Apple root.
async function validateChain(
  x5c: string[],
  now: Date,
  root: x509.X509Certificate,
): Promise<x509.X509Certificate> {
  // Apple always sends exactly [leaf, intermediate, root]; the library
  // rejects any other length, so do we.
  if (!Array.isArray(x5c) || x5c.length !== 3) {
    throw new JWSVerificationError("x5c chain must have exactly 3 certificates");
  }

  // Parsing untrusted DER can throw low-level ASN.1 errors; normalise them to
  // JWSVerificationError so the caller returns 400 (reject) rather than 500.
  let chain: x509.X509Certificate[];
  try {
    chain = x5c.map(
      (b64) =>
        new x509.X509Certificate(
          Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)),
        ),
    );
  } catch {
    throw new JWSVerificationError("unparseable x5c certificate");
  }

  // Validity window for every cert in the chain.
  for (const cert of chain) {
    if (now < cert.notBefore || now > cert.notAfter) {
      throw new JWSVerificationError("certificate outside validity window");
    }
  }

  // App Store marker OIDs: a G3-anchored chain from any other Apple PKI
  // (or a non-App-Store leaf under the WWDR intermediate) is refused.
  if (!hasExtension(chain[0], APP_STORE_LEAF_OID)) {
    throw new JWSVerificationError("leaf certificate is not an App Store signing cert");
  }
  if (!hasExtension(chain[1], APPLE_WWDR_INTERMEDIATE_OID)) {
    throw new JWSVerificationError("intermediate certificate is not Apple WWDR");
  }

  // Each cert must be signed by the next one up the chain.
  for (let i = 0; i < chain.length - 1; i++) {
    let ok = false;
    try {
      ok = await chain[i].verify({ publicKey: chain[i + 1].publicKey }, crypto);
    } catch {
      ok = false;
    }
    if (!ok) throw new JWSVerificationError("broken certificate chain link");
  }

  // The top of the presented chain must chain to the pinned Apple root.
  const top = chain[chain.length - 1];
  const rootPublicKey = root.publicKey;
  if (now < root.notBefore || now > root.notAfter) {
    throw new JWSVerificationError("pinned Apple root outside validity window");
  }
  // If the chain explicitly includes the Apple root as its top cert, the
  // per-link check above already proved the chain anchors to it. Otherwise the
  // top cert must itself be signed by the pinned root.
  const topIsPinnedRoot = top.equal(root);
  if (!topIsPinnedRoot) {
    let anchored = false;
    try {
      anchored = await top.verify({ publicKey: rootPublicKey }, crypto);
    } catch {
      anchored = false;
    }
    if (!anchored) {
      throw new JWSVerificationError("chain does not anchor to Apple Root CA - G3");
    }
  }

  return chain[0]; // leaf
}

// Verify a single Apple JWS and return its decoded payload object. Throws
// JWSVerificationError on any failure (forged signature, untrusted/expired
// cert, missing x5c, algorithm mismatch, etc.).
export async function verifyAppleJWS<T>(
  jws: string,
  opts: VerifyOptions = {},
): Promise<T> {
  if (typeof jws !== "string" || jws.split(".").length !== 3) {
    throw new JWSVerificationError("malformed JWS");
  }

  let header: { alg?: string; x5c?: string[] };
  try {
    header = decodeProtectedHeader(jws) as { alg?: string; x5c?: string[] };
  } catch {
    throw new JWSVerificationError("unreadable JWS header");
  }

  if (header.alg !== "ES256") {
    throw new JWSVerificationError(`unexpected JWS alg: ${header.alg}`);
  }
  if (!header.x5c || header.x5c.length === 0) {
    throw new JWSVerificationError("JWS header missing x5c chain");
  }

  const now = opts.now ?? new Date();
  // validateChain throws unless the presented x5c links cryptographically,
  // carries the App Store OIDs, and anchors to the pinned Apple Root CA - G3,
  // so the leaf key is trusted.
  await validateChain(header.x5c, now, opts.root ?? APPLE_ROOT_CA_G3);

  // Verify the JWS signature with the (now-trusted) leaf certificate key.
  // Apple's signed payloads are bare JWS over a JSON body (not RFC 7519 JWTs
  // and frequently without exp/nbf), so verify the signature only with
  // compactVerify and JSON-parse the bytes ourselves.
  const leafKey = await importX509(derToPem(header.x5c[0]), "ES256");

  let plaintext: Uint8Array;
  try {
    const verified = await compactVerify(jws, leafKey, { algorithms: ["ES256"] });
    plaintext = verified.payload;
  } catch (e) {
    throw new JWSVerificationError(
      `JWS signature verification failed: ${(e as Error).message}`,
    );
  }

  let body: T;
  try {
    body = JSON.parse(new TextDecoder().decode(plaintext)) as T;
  } catch {
    throw new JWSVerificationError("verified JWS body is not valid JSON");
  }

  if (opts.maxAgeMs !== undefined) {
    const signedDate = (body as { signedDate?: unknown })?.signedDate;
    if (typeof signedDate !== "number" || !Number.isFinite(signedDate)) {
      throw new JWSVerificationError("payload missing signedDate");
    }
    const age = now.getTime() - signedDate;
    if (age > opts.maxAgeMs) {
      throw new JWSVerificationError("signedDate too old (possible replay)");
    }
    if (age < -CLOCK_SKEW_MS) {
      throw new JWSVerificationError("signedDate is in the future");
    }
  }

  return body;
}
