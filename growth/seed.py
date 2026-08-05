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
    dict(slug="crawl_paths", status="active", kind="indexing",
         name="Every published section must have an inbound internal link",
         prefixes=[], metric="organic_visitors",
         hypothesis="A section reachable only from a sitemap does not get indexed. On "
                    "2026-08-05, /section8/ had been live 10 days, rebuilt nightly, listed in "
                    "sitemap-daily.xml and submitted to IndexNow every night, and had never "
                    "earned a single Search Console impression — and nothing on the site "
                    "linked to it. Every URL that HAS served sits in the interlinked SEO "
                    "corpus or is linked from the homepage nav. Giving each published section "
                    "a real inbound link from a page Google already crawls should get it "
                    "indexed; auditing that link nightly should stop the next section from "
                    "shipping into the same hole.",
         evidence="/sf/ /la/ /dc/ are the test case already in the data: they are the only "
                  "non-building URLs besides the homepage, six ZIP hubs and one neighborhood "
                  "hub to serve at all, and they are the ones the homepage nav links to. "
                  "2026 indexing guidance is consistent that Google treats a URL with no "
                  "internal link as unimportant regardless of sitemap inclusion.",
         notes="Audits, never publishes. Reads the ledger's own prefix declarations against "
               "the live docroot, so a technique added later is covered without being "
               "listed here. Self-links inside a prefix do not count — a family whose pages "
               "only link to each other is exactly the orphan case."),
    dict(slug="hub_direct_answers", status="active", kind="content",
         prefixes=["/neighborhood/", "/borough/", "/zip/"], metric="owned_visitors",
         name="Direct-answer blocks on hub pages",
         hypothesis="47,600 thin pages earned 89 impressions, so volume is not the lever. "
                    "Concentrating depth on the ~370 hub pages that aggregate real numbers "
                    "should do more than another page ever will. Each hub now opens with a "
                    "self-contained 45-80 word answer — the place, the count, what rent "
                    "stabilization actually means, and the per-building caveat — written to "
                    "be lifted whole by an AI answer engine or a featured snippet, which a "
                    "lead sentence that assumes page context cannot be.",
         evidence="Published case studies crediting AI-answer gains to depth on a small "
                  "page set (PlushBeds/ResultFirst, 25 pages) describe hand-rewriting, not "
                  "page volume. Their headline percentages are on tiny baselines and come "
                  "from a vendor, so this is treated as a hypothesis to test, not a result "
                  "to copy. The honest test is whether gsc_serving_pages and hub-page "
                  "positions move while thin-page counts stay flat.",
         notes="Implementation lives in build_seo.py:answer_block(), not in techniques.py — "
               "the hub pages are generated by the SEO build, so the growth technique here "
               "only verifies the blocks are present and counts them."),
    dict(slug="city_guides", status="active", kind="content",
         prefixes=["/guide/is-my-apartment-rent-controlled-"], metric="organic_visitors",
         name="Cornerstone guides for San Francisco, Los Angeles and Washington DC",
         hypothesis="Every one of the site's six guide pages was about New York, while SF, "
                    "LA and DC — three of the four cities in the dataset and 42 of the 97 "
                    "tracked queries — had no explanatory page at all. Their 'explain' and "
                    "'check' queries were pointed at the city map, which is a listings UI "
                    "that cannot answer 'what are the exemptions' or 'is my building "
                    "covered', so those queries were counted as covered while being "
                    "unanswerable. One cornerstone guide per city, targeting the "
                    "is-my-apartment-rent-controlled question that every other query in "
                    "that city orbits, is the cheapest way to make three quarters of the "
                    "tracked universe addressable at all. Unlike another 40k templated "
                    "pages, these are three hand-written pages on a domain whose problem is "
                    "trust, not volume.",
         evidence="Measured, not assumed: 0 of 97 tracked queries rank in the top 10 and "
                  "77 of ~47,600 pages earn a Search Console impression (2026-07-29), so "
                  "the constraint is not page count. The SF/LA/DC city pages are the same "
                  "SPA shell with a different <title> — their visible text is NYC borough "
                  "filters and HPD violation controls, which is why an SF exemptions query "
                  "has nothing to match. 2026 pSEO guidance is consistent that templated "
                  "pages survive only where each carries unique data and intent; a "
                  "hand-written cornerstone page per city is the opposite failure mode.",
         notes="Content lives in seo_guides.py, rendered by build_seo.guide_page(). The "
               "technique verifies the three pages exist in the docroot AND still carry "
               "their data caveat — LA is derived from assessor criteria and labelled "
               "'likely RSO', SF is anonymized to the block. A guide that loses its caveat "
               "is a credibility bug, so it fails the run. Since 2026-08-02 it also "
               "PUBLISHES a guide the SEO pipeline has not deployed, through the growth "
               "build's own rsync: that pipeline's checkout stopped taking pushes and these "
               "three pages sat finished in git for four days, live nowhere. Ownership is "
               "by marker — a docroot copy without FALLBACK_MARKER belongs to the SEO "
               "build and is never overwritten — so the two pipelines cannot fight over one "
               "file. Fallback-published guides are listed in sitemap-daily.xml because no "
               "SEO shard knows they exist."),

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
         name="Drive demand to the Developer API",
         prefixes=["/developers/"], metric="mrr_usd",
         hypothesis="Reaching $10k/mo through $4.99 consumer subs needs ~2,000 subscribers. "
                    "The API reaches it with roughly 200 Pro or 50 Business customers — or a "
                    "handful of Enterprise bulk licences, which is why that tier now exists. "
                    "Proptech, appraisers, brokerages, tenant-side law firms and researchers "
                    "all need property-level rent-regulation data and mostly cannot get it.",
         evidence="Verified 2026-07-26: the product is already BUILT and working end to end — "
                  "self-serve signup, metered keys, live Stripe checkout (cs_live_ session "
                  "confirmed), and a working webhook. The api_keys table holds only the "
                  "owner's own smoke tests, so the gap is demand, not product.",
         notes="Enterprise tier added 2026-07-26 to raise the ceiling. REQUIRED: confirm "
               "api@findacrib.com is a live forwarding alias in Namecheap, or Enterprise "
               "enquiries bounce."),
    dict(slug="b2b_outreach", status="active", kind="distribution",
         name="Daily B2B prospect research + drafted outreach",
         prefixes=[], metric="mrr_usd",
         hypothesis="Nobody discovers a data API by accident, and zero real signups confirms "
                    "it. A steady trickle of genuinely researched, personalised outreach "
                    "converts far better than volume in markets this small.",
         evidence="api_keys contains no real developer signups despite the API being live "
                  "since July.",
         notes="Drafts only, never auto-sends — bulk cold mail from findacrib.com would put "
               "the saved-building alert emails into spam, and cold outreach carries CAN-SPAM "
               "and GDPR obligations that need a human decision. Needs the Anthropic key."),
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
               "rent-map-gsc-service-account. "
               "2026-08-04: gsc_serving_pages alone was being read as the gating number and "
               "it cannot carry that weight — a rolling count of distinct URLs served says "
               "nothing about whether it is the same set twice. searchconsole.py now keeps a "
               "per-URL serving history in gsc_pages.json and records gsc_serving_stable / "
               "_entered / _left / _ever beside it. Backfilled from the six committed "
               "snapshots 2026-07-30..08-04: the daily count sat at 78-89 the whole time "
               "while distinct-pages-ever went 82 -> 142, i.e. newly-served pages displace "
               "old ones instead of adding to the total. _ever is the monotone one and the "
               "one to steer by; it survives history eviction via a running dropped total."),
    dict(slug="lifecycle_email", status="candidate", kind="lifecycle",
         name="Buyer follow-up sequence (Building Report)",
         prefixes=[], metric="mrr_usd",
         hypothesis="Report buyers paid at the highest-intent moment in the funnel and each "
                    "have one specific building they care about. Nudging the free DHCR "
                    "rent-history request — the step that actually establishes overcharge "
                    "and the easiest to put off — is useful enough to earn the open.",
         evidence="Free accounts were the obvious audience but only 3 have ever saved a "
                  "building, too few for the 21-day review to find any signal."),
    dict(slug="account_lifecycle", status="candidate", kind="lifecycle",
         name="Free-account onboarding sequence",
         prefixes=[], metric="visitors",
         hypothesis="A new account currently receives nothing at all, so the first "
                    "impression after signing up is silence. A welcome, one activation "
                    "nudge for people who never saved anything, and one lapsed check "
                    "should raise the 6% week-over-week return rate.",
         evidence="Supabase auth runs with mailer_autoconfirm and no SMTP host: no "
                  "confirmation and no welcome is sent. 17 of 20 accounts have never "
                  "saved a building.",
         notes="Accounts created before the 2026-07-27 cutover never enter the sequence — "
               "gating only the welcome on age would still have fired the day-3 and day-21 "
               "steps at 17 cold accounts at once, which is the backfill blast the owner "
               "explicitly ruled out."),
    dict(slug="listings_freshness", status="candidate", kind="content",
         name="Refresh the 'recently advertised' feed more than monthly",
         prefixes=["/available/"], metric="owned_visitors",
         hypothesis="The rental-activity signal is the site's most commercial content, and it "
                    "currently decays for a month between refreshes.",
         evidence="listings.json on the live site was last written July 1; the scrape cron "
                  "runs on the 1st of the month only."),
    dict(slug="city_seo_expansion", status="candidate", kind="content",
         name="Aggregate browse hubs for SF / LA / DC",
         # The tier this technique generates, NOT the bare city roots. /sf/, /la/
         # and /dc/ are the pre-existing SPA map shells written by
         # build_city_pages.py and listed in sitemap-main.xml since long before
         # this technique existed; claiming them made the first gsc_owned_*
         # reading (2026-08-01) report 3 pages serving at position 8 for a
         # technique with zero pages live in the docroot.
         prefixes=["/sf/neighborhood/", "/sf/buildings/",
                   "/la/zip/", "/la/buildings/",
                   "/dc/neighborhood/", "/dc/buildings/"],
         metric="owned_visitors",
         hypothesis="The page tier that ranks on this site is the one that aggregates, and three "
                    "of the four cities had none of it. Of the 82 pages earning any Search "
                    "Console impression on 2026-07-30, 75 are single-building pages whose only "
                    "query is the literal street address — 58 of the 82 sit at position 10 or "
                    "better, so ranking ability is not the constraint, addressable search volume "
                    "is, and one address has almost none. The ZIP and neighborhood hubs rank at "
                    "positions 2-4 where they serve. So: give SF, LA and DC the same aggregate "
                    "tier NYC has, 252 pages instead of another 47,000 addresses, each carrying "
                    "counts and distributions that only this dataset holds.",
         evidence="/sf/, /la/ and /dc/ were a single JavaScript map shell each — which is also "
                  "why 11 city queries were scored 'covered' by a page that cannot answer them "
                  "(found 2026-07-29). 2026 large-site guidance is consistent that a crawler "
                  "reaches hub pages first and that aggregate pages survive only where each "
                  "carries unique data; these carry per-place counts, unit-size or decade "
                  "distributions, and median reported rents where the city reports them.",
         notes="Rendered by build_seo.py:city_hub_docs() at /<city>/neighborhood/<slug>/ (SF, "
               "DC) and /la/zip/<zip>/, plus a browse hub at /<city>/buildings/. Grouped on the "
               "dimension each city's data actually carries: SF and DC record a neighborhood, LA "
               "records only a ZIP. No page states a stat its city does not hold — LA has no "
               "reported rents, DC has no build years — and no place with fewer than 5 records "
               "gets a page. Deliberately NOT building-level: SF is anonymized to the block and "
               "LA is a derived 'likely RSO' list, so the aggregate is the honest unit of "
               "publication for those two. Since 2026-08-03 the technique also PUBLISHES the "
               "tier the SEO pipeline has not deployed, through the growth build's own rsync, "
               "on the same terms as the city guides: ownership by FALLBACK_MARKER, so a docroot "
               "copy the SEO build wrote is never overwritten and this steps aside on the day "
               "/root/dhcr-build starts pulling again. 255 pages had been finished in git and "
               "live nowhere for five days. Fallback-published hubs are listed in "
               "sitemap-daily.xml (changefreq monthly) and the three browse hubs in llms.txt, "
               "because no SEO-owned shard knows these URLs exist."),
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
    """Create anything missing and refresh the descriptions of what exists.

    This file is the source of truth for a seeded technique's wording, so an
    edit here propagates on the next run. Status, verdicts and dates are left
    alone — those belong to the running ledger, and overwriting them would
    erase measured history every deploy.
    """
    added, updated = [], []
    for s in SEEDS:
        before = {t["slug"] for t in ledger.load_techniques()}
        ledger.add(slug=s["slug"], name=s["name"], hypothesis=s["hypothesis"],
                   kind=s["kind"], prefixes=s.get("prefixes"), metric=s.get("metric", "owned_visitors"),
                   source="seed", evidence=s.get("evidence", ""), status=s["status"],
                   notes=s.get("notes", ""))
        if s["slug"] not in before:
            added.append(s["slug"])
            continue
        techs = ledger.load_techniques()
        dirty = False
        for t in techs:
            if t["slug"] != s["slug"]:
                continue
            for field, key in (("name", "name"), ("hypothesis", "hypothesis"),
                               ("evidence", "evidence"), ("notes", "notes"),
                               ("prefixes", "prefixes"), ("metric", "metric")):
                new = s.get(key, t.get(field))
                if new is not None and t.get(field) != new:
                    t[field] = new
                    dirty = True
        if dirty:
            ledger.save_techniques(techs)
            updated.append(s["slug"])
    if not ledger.get_state("goals"):
        ledger.set_state("goals", GOALS)
    return added, len(ledger.load_techniques())
