"""The one door every Find A Crib AI feature goes through (2026-10-03).

Owner's rules: AI features are Find A Crib Plus ($4.99), and every model call
together stays under $20 a month. So before a feature calls a model it asks
`allow()`, and after it calls one it reports `record()`:

  allow(user, feature)  -> None when the call may go ahead, else an error code:
      "sign_in_required"  no verified session
      "plus_required"     the account does not pay (has_plus)
      "daily_limit"       this user hit the feature's per-day ceiling
      "budget"            the month's spend is within SAFETY of the cap
  record(...)           one ai_usage row: tokens and the cost in micro-dollars

Costs come from published per-million-token prices below; a model missing
from PRICES is refused rather than guessed at (`allow` cannot price it).
Anthropic's own workspace spend limit is the backstop if this ever drifts.
"""
import json, os, urllib.request

CAP_MICROS = int(os.environ.get("AI_MONTHLY_CAP_MICROS", 20_000_000))   # $20
SAFETY = 0.95          # stop new calls at 95% of the cap

# USD per million tokens: (input, output). Jev bills input only. Claude cache
# writes cost 1.25x input (5-minute TTL) and cache reads 0.1x (claude-api skill,
# prices cached 2026-09-25). A refusal fallback can answer on another model;
# an unknown model is priced at FALLBACK_PRICE (the most expensive), never free.
PRICES = {
    "rules": (0.0, 0.0),           # answered by code, no model: free, but counts toward the daily limit
    "jev-1.13.0": (0.042, 0.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-8": (5.0, 25.0),
}
FALLBACK_PRICE = (10.0, 50.0)

# Calls per user per feature per New York day (cached answers are free).
DAILY_LIMITS = {
    "search": 60,
    "report_card": 30,
    "apply_help": 10,
    "ask": 20,
}


def cost_micros(model, input_tokens, output_tokens, cache_write_tokens=0, cache_read_tokens=0):
    pin, pout = PRICES.get(model) or next((v for k, v in PRICES.items() if model and model.startswith(k)), FALLBACK_PRICE)
    return int(round(input_tokens * pin + output_tokens * pout
                     + cache_write_tokens * pin * 1.25 + cache_read_tokens * pin * 0.1))   # $/M tokens == micro$/token


class Gateway:
    def __init__(self, rpc, supabase_url, service_key):
        self.rpc, self.url, self.key = rpc, supabase_url, service_key

    def allow(self, user, feature, model=None):
        if not user:
            return "sign_in_required"
        if model and model not in PRICES:
            return "budget"
        try:
            if not self.rpc("has_plus", {"uid": user["id"]}):
                return "plus_required"
            if self.rpc("ai_user_calls_today", {"p_user": user["id"], "p_feature": feature}) >= DAILY_LIMITS.get(feature, 20):
                return "daily_limit"
            if (self.rpc("ai_spend_month", {}) or 0) >= CAP_MICROS * SAFETY:
                return "budget"
        except Exception:
            return "budget"        # cannot check the ledger: do not spend
        return None

    def record(self, user, feature, model, input_tokens=0, output_tokens=0, cached=False, ok=True,
               cache_write_tokens=0, cache_read_tokens=0):
        row = {"user_id": user["id"] if user else None, "feature": feature, "model": model,
               "input_tokens": int(input_tokens + cache_write_tokens + cache_read_tokens), "output_tokens": int(output_tokens),
               "cost_micros": 0 if cached else cost_micros(model, input_tokens, output_tokens,
                                                           cache_write_tokens, cache_read_tokens),
               "cached": bool(cached), "ok": bool(ok)}
        try:
            req = urllib.request.Request(
                f"{self.url}/rest/v1/ai_usage", data=json.dumps(row).encode(), method="POST",
                headers={"apikey": self.key, "Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json", "Prefer": "return=minimal"})
            urllib.request.urlopen(req, timeout=8).read()
        except Exception:
            pass                   # the ledger write failing must not fail the answer
        return row["cost_micros"]
