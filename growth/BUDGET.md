# Budget — don't blow it

**Standing rule: never blow the API budget.** The daily jobs run unattended, so
a cost mistake is not noticed when it is made — it is noticed days later, when
the account is capped and everything LLM-backed has silently stopped.

This is the file to update when the model, the token limits, or the rates
change. It is also the file to read before adding a new LLM-backed job.

## What actually happened (2026-07-28)

Worth writing down, because it is the failure mode this file exists to prevent:

1. Through 07-27 the Anthropic account had **no credit balance**. Every
   LLM-backed job across every project failed with HTTP 400. Nothing published
   for weeks.
2. On 07-28 credit was added. Find A Crib's 05:00 ET scout ran clean (3
   techniques, 25 keywords). NEMO's content writers published for the first
   time since that engine was built.
3. **Within the same day the account hit its usage cap** —
   *"You have reached your specified API usage limits. You will regain access
   on 2026-08-01 at 00:00 UTC."*

So the account went from empty, to funded, to capped in one day. The cap is a
**self-imposed spend limit set in the Anthropic console** — topping up does not
clear it. Only raising the cap or waiting for the reset does.

### The two failures look identical and are not

Both are HTTP 400. Read the message before reporting anything:

| Message contains | Meaning | Fix |
|---|---|---|
| `credit balance is too low` | Account is empty | Top up |
| `reached your specified API usage limits` | Self-imposed spend cap | Raise the cap, or wait for the reset date |

Reporting "no credit" when it is a usage cap sends someone to top up an account
that already has money. The daily report reads the real error text out of the
ledger rather than restating a remembered one.

## What the engine spends

`growth/scout.py` and `growth/outreach.py` are the only LLM callers here. Each
makes **one** API call per day. Both run on `claude-opus-5` with live web
search (`max_uses: 8`) and `max_tokens: 8000`.

Rates for that model, per million tokens: **$5 input, $25 output.**

The cost is dominated by **input**, not output, because every web-search result
is injected into the input side. A search-heavy call can pull far more input
tokens than the prompt itself suggests — this is the part that surprises people
and the reason 8000 output tokens is not a meaningful ceiling on cost.

Since 2026-07-28 each call prices itself from the response's own `usage` block
(`scout.price()` / `scout.record_spend()`), the running total is kept in ledger
state `api_spend`, and the daily report carries an **API spend (estimated)**
section with today, the last 7 days, and the daily average. It is an estimate —
cache reads bill at ~0.1x and writes at ~1.25x — and it exists to catch an
order-of-magnitude problem, not to reconcile an invoice.

**If that number moves by an order of magnitude, something changed. Find out
what before the cap does it for you.**

## The Opus 5 tension, stated plainly

There are two standing instructions here and they pull against each other:

- Daily automation runs on **Opus 5** — these agents act unreviewed, and the
  cost of a bad autonomous change exceeds the cost of the tokens.
- **Don't blow the budget.**

Both hold. The way they coexist is that **Opus 5 is for judgment, not for
volume**:

| Job | Model | Why |
|---|---|---|
| 6am review agent (cloud routine) | Opus 5 | Commits code to production unreviewed. Judgment. |
| Scout — proposes techniques and keywords | Opus 5 | One call/day; its output steers the roadmap. |
| Outreach — researches real organisations | Opus 5 | Names real third parties; being wrong is expensive. |
| Anything per-page, per-row, or per-request | **not Opus** | Volume work. Use Haiku, or no model at all. |

The rule of thumb: **a job that runs once a day can afford Opus. A job whose
call count scales with the size of the dataset cannot** — and should usually be
plain code, since most of what this engine does needs no model whatsoever.

## Before adding an LLM-backed job

1. **Does it need a model at all?** Most of this engine is deterministic code.
   The sitemap, the IndexNow ping, the hub pages, the direct-answer blocks — none
   of them call an API.
2. **How many calls per day, at what input size?** Multiply it out at the rates
   above. If the answer scales with the dataset, redesign it.
3. **Does it use web search?** Then input tokens are the cost, and `max_uses` is
   the real budget dial. Keep it low.
4. **Record its spend.** Call `scout.record_spend("<job>", resp)` so it shows up
   in the report. An unmeasured job is one that can only be discovered by a cap.
5. **Fail loudly.** Write `ok: False` and the real error text into a `*_last`
   ledger record, so the report can distinguish "ran, found nothing" from "could
   not run" (see `report.py` — that section reads `ok is False`).

## Related

- `reference_anthropic_credits_exhausted` in the operator's notes — the billing
  timeline and which keys sit on which account.
- The NEMO engine (`nemo-seamless-gutter`) shares this account and this rule;
  its page writers are the higher-volume caller of the two.
