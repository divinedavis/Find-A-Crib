// Who may turn a Sandbox (App Review / TestFlight) receipt into Plus.
//
// Sandbox purchases cost nothing, so before 2026-10-07 anyone holding a
// TestFlight build could subscribe for free and the function saved an
// "active" row for their account exactly as for a paying customer. Now a
// Sandbox receipt grants Plus only to accounts listed in the function secret
// APPLE_SANDBOX_USER_IDS (comma/space separated Supabase user ids: the App
// Review demo account and the owner's tester account). Ids, not emails: an
// id cannot be re-registered by someone else, an address in a sign-up form
// can. The list lives in a secret so the public repo carries no account ids.
//
// Production receipts are unaffected — they are real money.

export function parseAllowlist(raw: string | undefined | null): Set<string> {
  return new Set(
    (raw ?? "")
      .split(/[\s,]+/)
      .map((s) => s.trim().toLowerCase())
      .filter((s) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(s)),
  );
}

/** May this verified transaction write a Plus row for this user? */
export function mayGrant(env: string, userId: string, allow: Set<string>): boolean {
  if (env === "Production") return true;
  return allow.has(String(userId).toLowerCase());
}
