"""Broker fee checker (Find A Crib Plus, owner 2026-10-11).

Rules only, no model: a renter answers a few questions about how they found
the apartment and what they were asked to pay, and gets back which charges
NYC and New York State law likely forbid, each with the rule it comes from,
plus where to complain. Deterministic on purpose: a wrong "that's legal" here
costs a renter a month's rent, so no model is allowed to improvise the law.

Sources (read 2026-10-11):
  FARE Act — Local Law 119 of 2024, NYC Admin Code §§ 20-699.21–.24, in
    effect June 11, 2025. DCWP FAQ "Broker Fees" (08/12/2025):
    https://www.nyc.gov/assets/dca/downloads/pdf/about/FAQ-Broker-Fees.pdf
    - a landlord's agent, INCLUDING a listing agent, may not charge the
      tenant; an agent who publishes a listing is presumed to have the
      landlord's permission (§ 20-699.21(b),(e));
    - no one may require a tenant to hire a broker, or a particular / dual
      agent, to see or rent an apartment (§ 20-699.21(c));
    - every fee must be in the listing and on an itemized written disclosure
      the tenant signs before the lease (§ 20-699.21(d), § 20-699.22);
    - tenants may still choose to hire and pay their OWN broker;
    - complaints: DCWP portal or 311; private right to sue (§ 20-699.24).
  NY Real Property Law § 238-a: no application/processing fees; background +
    credit check at most actual cost or $20, waived with a check from the
    last 30 days; late fee only after 5 days, at most $50 or 5% of the
    monthly rent, whichever is less.
  NY General Obligations Law § 7-108(1-a): deposit or advance at most one
    month's rent.
Not legal advice; the UI says so.
"""
import re

FARE_START = "2025-06-11"
DCWP_URL = "https://www.nyc.gov/site/dca/consumers/file-complaint.page"

LAW = {
    "fare_agent": "NYC FARE Act — Admin Code § 20-699.21(b)",
    "fare_condition": "NYC FARE Act — Admin Code § 20-699.21(c)",
    "fare_disclose": "NYC FARE Act — Admin Code §§ 20-699.21(d), 20-699.22",
    "rpl_238a_app": "NY Real Property Law § 238-a(1)",
    "rpl_238a_late": "NY Real Property Law § 238-a(2)",
    "gol_7108": "NY General Obligations Law § 7-108(1-a)",
}

# How the renter found the apartment.
FOUND = {"listing_agent", "own_broker", "landlord_direct", "unsure"}

# Words in a pasted listing that mean the tenant is being asked for a broker fee.
_FEE_RE = re.compile(r"\b(broker(?:'s|age)?\s*fee|fee\s*:\s*\d|(?:one|1)\s*month(?:'s)?\s*fee|\d{1,2}(?:\.\d+)?\s*%\s*(?:broker\s*)?fee|tenant\s*pays\s*(?:the\s*)?(?:broker|fee))\b", re.I)
_NO_FEE_RE = re.compile(r"\b(no[\s-]*fee|owner\s*pays|landlord\s*pays|op\b)", re.I)


def _money(v):
    """A dollar amount from a form field: None when blank or not a number."""
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None
    return n if 0 <= n < 1_000_000 else None


def _yes(v):
    return v is True or str(v).lower() in ("yes", "true", "1")


def listing_signals(text):
    """What a pasted listing says about fees: ('fee'|'no_fee'|None, snippet)."""
    text = (text or "")[:20000]
    m = _FEE_RE.search(text)
    if m and not _NO_FEE_RE.search(text[max(0, m.start() - 40):m.end() + 40]):
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
        return "fee", " ".join(text[a:b].split())
    m = _NO_FEE_RE.search(text)
    if m:
        return "no_fee", None
    return None, None


def check(a):
    """`a` is the form: found, hired_in_writing, required_broker, broker_fee,
    rent, app_fee, deposit, late_fee, fees_disclosed, lease_before_fare,
    listing_text. Returns {verdict, findings[], next_steps[]}; each finding is
    {level: 'illegal'|'warn'|'ok', title, why, law}."""
    found = a.get("found") if a.get("found") in FOUND else "unsure"
    rent = _money(a.get("rent"))
    broker = _money(a.get("broker_fee"))
    app_fee = _money(a.get("app_fee"))
    deposit = _money(a.get("deposit"))
    late = _money(a.get("late_fee"))
    out = []

    def add(level, title, why, law):
        out.append({"level": level, "title": title, "why": why, "law": LAW[law] if law else None})

    sig, snippet = listing_signals(a.get("listing_text"))
    if _yes(a.get("lease_before_fare")):
        add("warn", "Your lease was signed before June 11, 2025",
            "The FARE Act's broker-fee ban started June 11, 2025. A fee you agreed to before then may still be owed, "
            "depending on how the agreement came about.", "fare_agent")

    if broker:
        if found == "own_broker" and _yes(a.get("hired_in_writing")):
            add("ok", "You hired this broker yourself",
                "You can still choose to hire your own broker to search for you, and pay them. "
                "That fee is allowed as long as the landlord didn't require you to use a broker.", None)
        elif found == "landlord_direct":
            add("illegal", "A broker fee on an apartment you found through the landlord",
                "The landlord's agent can't charge you. If the landlord or its office sent you to this broker, "
                "the broker is working for the landlord.", "fare_agent")
        elif found == "listing_agent":
            add("illegal", "A broker fee from the agent who posted the listing",
                "Since June 11, 2025, the agent who lists an apartment is presumed to work for the landlord, "
                "and the landlord's agent can't charge you a fee. The landlord pays.", "fare_agent")
        else:
            add("warn", "A broker fee — it depends on who hired the broker",
                "You only owe a broker you hired yourself to search for you. If the broker came with the listing "
                "or the landlord, the fee is likely illegal. An agent who posted the listing is presumed to work "
                "for the landlord.", "fare_agent")
        if found == "own_broker" and not _yes(a.get("hired_in_writing")):
            add("warn", "No written agreement hiring the broker",
                "If you never agreed to hire this broker before they showed you apartments, they are likely the "
                "listing agent — who can't charge you.", "fare_agent")
    if _yes(a.get("required_broker")):
        add("illegal", "Being told you must use or pay a broker to see or rent it",
            "No one can make renting an apartment depend on you hiring a broker, a particular agent, or a dual "
            "agent — even if the broker says it's their policy.", "fare_condition")
    if sig == "fee" and found != "own_broker":
        add("illegal" if found == "listing_agent" else "warn", "The listing itself asks the tenant for a broker fee",
            f"A listing can't include an unlawful broker fee. It says: “{snippet}”", "fare_agent")
    if a.get("fees_disclosed") in ("no", False):
        add("illegal", "Fees you weren't told about up front",
            "Every fee you must pay has to be in the listing and on an itemized written list you sign before the "
            "lease. You get a copy.", "fare_disclose")

    if app_fee is not None:
        if app_fee > 20:
            add("illegal", f"An application fee of ${app_fee:,.0f}",
                "New York allows only a background and credit check fee, at most the actual cost or $20, whichever is "
                "less. Any other application or processing fee is banned.", "rpl_238a_app")
        elif app_fee > 0:
            add("ok", f"An application fee of ${app_fee:,.0f}",
                "Allowed only as a background and credit check fee of $20 or less. They must give you a copy of the "
                "check and the receipt, and must waive it if you bring a check from the last 30 days.", "rpl_238a_app")
    if deposit is not None and rent:
        if deposit > rent + 0.5:
            add("illegal", f"A ${deposit:,.0f} security deposit on ${rent:,.0f} rent",
                "A deposit or advance can't be more than one month's rent.", "gol_7108")
        else:
            add("ok", "Security deposit is one month's rent or less", "That's within the limit.", "gol_7108")
    elif deposit is not None and not rent:
        add("warn", "Add the monthly rent to check the deposit", "A deposit can't be more than one month's rent.", "gol_7108")
    if late is not None and late > 0:
        cap = min(50.0, 0.05 * rent) if rent else 50.0
        if late > cap + 0.5:
            add("illegal", f"A ${late:,.0f} late fee",
                f"A late fee can be at most $50 or 5% of the monthly rent, whichever is less"
                f"{f' — ${cap:,.0f} on your rent' if rent else ''}, and only after rent is 5 days late.", "rpl_238a_late")
        else:
            add("ok", f"A ${late:,.0f} late fee", "Within the cap, as long as it only applies after rent is 5 days late.",
                "rpl_238a_late")

    levels = {f["level"] for f in out}
    verdict = "likely_illegal" if "illegal" in levels else "check" if "warn" in levels else "looks_ok" if out else "nothing_to_check"
    steps = []
    if verdict in ("likely_illegal", "check"):
        steps = [
            "Don't pay a fee you think is illegal. Ask for every fee in writing, itemized.",
            "Already paid? Ask the landlord and broker in writing for the money back, naming the law above.",
            "File a complaint with the NYC Department of Consumer and Worker Protection (DCWP) online or by calling 311. "
            "DCWP can order the fee refunded.",
            "You can also sue in civil court — the FARE Act lets tenants bring their own case.",
        ]
    return {"verdict": verdict, "findings": out, "next_steps": steps, "complaint_url": DCWP_URL}
