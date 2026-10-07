// deno test supabase/functions/apple-subscription/sandbox_test.ts
import { mayGrant, parseAllowlist } from "./sandbox.ts";

const REVIEW = "0f0e0d0c-0b0a-4908-8706-050403020100";
const OTHER = "00000000-0000-4000-8000-000000000001";

function eq(a: unknown, b: unknown, msg: string) {
  if (a !== b) throw new Error(`${msg}: expected ${b}, got ${a}`);
}

Deno.test("production always grants", () => {
  eq(mayGrant("Production", OTHER, new Set()), true, "prod");
});

Deno.test("sandbox grants only allowlisted ids", () => {
  const allow = parseAllowlist(`${REVIEW.toUpperCase()}, junk  not-an-id`);
  eq(allow.size, 1, "only the uuid parses");
  eq(mayGrant("Sandbox", REVIEW, allow), true, "allowlisted");
  eq(mayGrant("Sandbox", OTHER, allow), false, "stranger");
});

Deno.test("empty or missing secret grants no sandbox", () => {
  eq(mayGrant("Sandbox", OTHER, parseAllowlist(undefined)), false, "undefined");
  eq(mayGrant("Sandbox", OTHER, parseAllowlist("")), false, "empty");
});

Deno.test("an email in the secret is ignored", () => {
  eq(parseAllowlist("appreview@findacrib.com").size, 0, "emails never match");
});
