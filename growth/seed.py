#!/usr/bin/env python3
"""The starting ledger: five techniques running today, and the backlog behind them.

Everything here is idempotent by slug, so this runs on every boot and only ever
adds what is missing. Candidates are real proposals with a stated hypothesis —
they are not running yet, either because they need code or because they need a
decision or an account only the owner can open.

The goals at the bottom are what the whole loop is steering toward. They are
deliberately written as numbers so review.py and the daily report can say how
far off we are rather than "growing nicely".
"""
from . import ledger

GOALS = {
    "search_share_pct": {
        "target": 90,
        "what": "Share of the tracked query universe (growth/keywords.json) where we rank "
                "in the top 10, across NYC / SF / LA / DC.",
        "measured_by": "Google Search Console — blocked until a service account is wired up. "
                       "Until then keyword COVERAGE is the honest stand-in.",
    },
    "signups": {
        "target": 10_000,
        "what": "Registered accounts.",
        "measured_by": "Supabase auth users; reported daily.",
    },
    "mrr_usd": {
        "target": 10_000,
        "what": "Monthly recurring revenue from all sources.",
        "measured_by": "Stripe subscriptions + any B2B contracts recorded in the ledger.",
        "note": "At $4.99/mo consumer pricing this is ~2,000 paying subscribers, which at a "
                "normal 1-3% free-to-paid rate implies ~70k-200k engaged users. B2B data "
                "licensing reaches the same number with a few dozen customers, which is why "
                "the revenue candidates below lean that way.",
    },
}

SEEDS = [
    # ---------------------------------------------------------------- ACTIVE
    dict(slug="fresh_section8", status="active", kind="content",
         name="Daily voucher-listing pages (/section8/)",
         prefixes=["/section8/"], metric="owned_visitors",
         hypothesis="The voucher feed is the only data on the site that genuinely changes "
                    "daily, and 'section 8 apartments <city>' is high-volume, high-intent, "
                    "commercial search. Pages that are both rebuilt daily and uniquely "
                    "cross-referenced against rent-stabilized status should earn rankings "
                    "that a static list cannot.",
         evidence="Nightly AffordableHousing.com feed already runs at 04:15 UTC; ~250 live "
                  "listings match known stabilized buildings."),
    dict(slug="daily_brief", status="active", kind="content",
         name="Dated daily market briefs (/brief/)",
         prefixes=["/brief/"], metric="owned_visitors",
         hypothesis="A dated series of real market snapshots creates a genuine archive, gives "
                    "crawlers a new URL every day, and is the kind of primary source that "
                    "journalists and AI answer engines cite.",
         evidence="Publishes only when listings actually moved, so the archive stays a data "
                  "series rather than filler."),
    dict(slug="llms_txt", status="active", kind="distribution",
         name="llms.txt + explicit AI-crawler permissions",
         prefixes=[], metric="ai_visitors",
         hypothesis="AI answer engines already refer traffic (visits carry "
                    "utm_source=chatgpt.com). Handing them a parseable map of the dataset, "
                    "with the caveats spelled out, should increase how often we are the cited "
                    "source for rent-stabilization questions.",
         evidence="Observed chatgpt.com referrals in the visits table before any GEO work."),
    dict(slug="sitemap_daily", status="active", kind="indexing",
         name="Daily sitemap for daily-changing pages",
         prefixes=[], metric="organic_visitors",
         hypothesis="The main sitemap is rebuilt monthly and would never mention today's "
                    "pages. A separate daily sitemap with honest lastmod is how Google learns "
                    "to re-crawl this section on a daily rhythm.",
         evidence="Google does not consume IndexNow; sitemap lastmod is its re-crawl signal."),
    dict(slug="indexnow", status="active", kind="indexing",
         name="IndexNow submission of new/changed URLs",
         prefixes=[], metric="organic_visitors",
         hypothesis="47k pages produce only ~30 organic visitors/week, which points at an "
                    "indexing problem rather than a content problem. Same-day submission to "
                    "Bing/Yandex/Seznam/Naver should raise the share of the corpus that is "
                    "actually indexed and serving.",
         evidence="IndexNow key already hosted at the docroot; the existing submitter only "
                  "ran on the monthly SEO rebuild, so it fired ~once a month."),

    # ------------------------------------------------------------- CANDIDATE
    dict(slug="adsense_activation", status="candidate", kind="conversion",
         name="Turn on ad inventory (AdSense)",
         prefixes=[], metric="mrr_usd",
         hypothesis="Display ads across 47k pages is the lowest-effort revenue on the site, "
                    "and it is currently earning exactly $0 because no ad unit is configured.",
         evidence="index.html sets ADSENSE_CLIENT but leaves ADSENSE_SLOT empty, and ADS_ON() "
                  "requires both — so no ad script loads and no ad renders anywhere.",
         notes="Needs: confirm the AdSense account cleared review, create an in-feed unit, "
               "paste its slot id. One field, and inventory goes live."),
    dict(slug="b2b_api_licensing", status="candidate", kind="conversion",
         name="Productize the Developer API for B2B data licensing",
         prefixes=["/developers/"], metric="mrr_usd",
         hypothesis="Reaching $10k/mo through $4.99 consumer subs needs ~2,000 subscribers; "
                    "the same number needs roughly 10-30 B2B customers at $300-1,000/mo. "
                    "Proptech, brokerages, appraisers, tenant-side law firms and housing "
                    "nonprofits all need property-level rent-regulation data and mostly "
                    "cannot get it anywhere else.",
         evidence="findacrib-api already runs with per-key metering and issue_api_key.py; the "
                  "missing pieces are public pricing, self-serve checkout, and outreach.",
         notes="Needs: pricing tiers, a Stripe product, self-serve key issuance on payment."),
    dict(slug="b2b_outreach", status="candidate", kind="distribution",
         name="Daily qualified B2B prospect research + drafted outreach",
         prefixes=[], metric="mrr_usd",
         hypothesis="Nobody discovers a data API by accident. A steady, small, genuinely "
                    "researched outreach list converts far better than volume, and B2B is the "
                    "fastest credible path to the revenue goal.",
         evidence="Standard motion for data businesses at this stage.",
         notes="Deliberately drafts-for-approval rather than auto-sending: bulk cold mail from "
               "findacrib.com would put the deliverability of the product's own alert emails "
               "at risk, and that is not a trade worth making silently."),
    dict(slug="data_pr_outreach", status="candidate", kind="distribution",
         name="Pitch data stories to housing reporters (earns links)",
         prefixes=[], metric="organic_visitors",
         hypothesis="Domain authority is the ceiling on the 90% search-share goal, and links "
                    "from housing/city desks are the highest-quality way to raise it. The "
                    "daily briefs are a standing supply of original, citable findings.",
         evidence="Original data is the one thing reporters reliably link back to."),
    dict(slug="gsc_integration", status="candidate", kind="indexing",
         name="Search Console integration (measures the 90% goal)",
         prefixes=[], metric="organic_visitors",
         hypothesis="We cannot steer toward 90% search share without knowing our actual "
                    "positions and impressions. Search Console also exposes page-2 queries, "
                    "which are the cheapest rankings to win.",
         evidence="seo_search_console.py is already written and working — it just has no "
                  "service-account key, so it has never run.",
         notes="Needs: a Google Cloud service account with the Search Console API enabled, "
               "added as a user on the findacrib.com property, key stored in keychain "
               "rent-map-gsc-service-account."),
    dict(slug="lifecycle_email", status="candidate", kind="lifecycle",
         name="Onboarding + re-engagement email",
         prefixes=[], metric="visitors",
         hypothesis="Saved-building alerts already bring people back; a short onboarding "
                    "sequence and a lapsed-user nudge should raise return rate and give the "
                    "Plus upgrade a natural moment to appear.",
         evidence="Week-over-week retention is 6% — most first visits never come back."),
    dict(slug="listings_freshness", status="candidate", kind="content",
         name="Refresh the 'recently advertised' feed more than monthly",
         prefixes=["/available/"], metric="owned_visitors",
         hypothesis="The rental-activity signal is the site's most commercial content, and it "
                    "currently decays for a month between refreshes.",
         evidence="listings.json on the live site was last written July 1; the scrape cron "
                  "runs on the 1st of the month only."),
    dict(slug="city_seo_expansion", status="candidate", kind="content",
         name="Neighborhood landing pages for SF / LA / DC",
         prefixes=["/sf/", "/la/", "/dc/"], metric="owned_visitors",
         hypothesis="NYC has 47k pages and three other cities have one page each, so three "
                    "quarters of the tracked query universe has almost no surface area.",
         evidence="build_seo.py is NYC-only; DC already carries real neighborhood names, so "
                  "it is the cheapest of the three."),
    dict(slug="plus_funnel", status="candidate", kind="conversion",
         name="Rebuild the Plus upgrade funnel",
         prefixes=[], metric="mrr_usd",
         hypothesis="Traffic is not the only thing between here and revenue: the current "
                    "funnel has converted zero paying subscribers, so sending more traffic "
                    "through it unchanged just wastes it.",
         evidence="subscriptions table holds 1 owner account and 5 comps — no organic paid "
                  "conversions to date."),
]


def run():
    """Create anything missing. Returns (added_slugs, total)."""
    added = []
    for s in SEEDS:
        before = {t["slug"] for t in ledger.load_techniques()}
        ledger.add(slug=s["slug"], name=s["name"], hypothesis=s["hypothesis"],
                   kind=s["kind"], prefixes=s.get("prefixes"), metric=s.get("metric", "owned_visitors"),
                   source="seed", evidence=s.get("evidence", ""), status=s["status"],
                   notes=s.get("notes", ""))
        if s["slug"] not in before:
            added.append(s["slug"])
    if not ledger.get_state("goals"):
        ledger.set_state("goals", GOALS)
    return added, len(ledger.load_techniques())
