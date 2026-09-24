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
         evidence="Google does not consume IndexNow; sitemap lastmod is its re-crawl signal.",
         notes="2026-08-17: widened from 'the daily pages' to 'every page in a family this "
               "build owns that no pipeline shard lists'. It had been built purely from the "
               "lastmod state, and Ctx.unstage() drops a URL's lastmod entry when it hands a "
               "page back to the SEO pipeline — correct for the bytes, wrong for the sitemap, "
               "because the pipeline's own shard never picked the city hub tier up. Result: 103 "
               "DC, 112 LA and 37 SF hub pages live in the docroot against two sitemap URLs per "
               "city, i.e. 252 finished pages in no sitemap at all, on the same morning the URL "
               "Inspection sample read 'unknown to Google' — never fetched — for 159 of 198 "
               "URLs. Watch the 'rescued' count in the detail line: it is the size of that hole "
               "and should go to 0 when the SEO pipeline emits its own city shards.\n"
               "[2026-09-24] REVISIT DECISION: KEEP, WITH ONE CLAIM REMOVED IN CODE. The "
               "hypothesis still holds and nothing else in this loop does its job: the shard "
               "carries 25 URLs, 2 of which exist in the docroot and appear in no sitemap the "
               "SEO pipeline owns, so without it they would have no crawl path at all. The "
               "'rescued' count has not gone to 0, which is the standing signal that the "
               "pipeline still emits no city shards. WHAT CHANGED TODAY AND WHY. _price() gave "
               "/rent-report/ changefreq=daily on an assertion written into its own comment on "
               "2026-09-19 — 'rebuilt every morning from that night's listings scrape' — which "
               "nothing had ever checked. Checked on 2026-09-24: NO .sh IN THIS REPO INVOKES "
               "build_rent_report.py. Not refresh_seo.sh, not refresh_listings.sh, not "
               "growth_run.sh, not any of the fourteen scripts in scripts/, and not "
               "growth_daily.py or api_server.py either. That does not prove the page is never "
               "rebuilt — the owner may run it from a cron outside this repo — it proves this "
               "build cannot substantiate 'daily', which is the same standard the function's "
               "own docstring applies to a retired section and build_seo.py applies to a count. "
               "It is now priced from the evidence the shard already holds: the entry's lastmod, "
               "which for a rescued page is the file's own mtime. Written within 2 days reads "
               "'daily', within a month 'weekly', older 'monthly'. If the owner's cron does run "
               "nightly nothing changes; if it does not, the sitemap stops saying so and "
               "t_frozen_pages names the page on the same morning — two instruments, one "
               "question. NOTE WHAT THIS IS NOT: Google ignores changefreq and priority "
               "outright, so this moves no ranking. It is an accuracy fix on an artifact the "
               "IndexNow crawlers do read, and it removes a claim the build knew it could not "
               "support."),
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
               "only link to each other is exactly the orphan case. "
               "REVISIT 2026-09-04, AND THE HYPOTHESIS IS FALSIFIED AS A CAUSAL CLAIM. The "
               "linking half of it was fully delivered: 15 of 15 published sections now carry "
               "an inbound internal link and every one sits within 3 clicks of the homepage. "
               "Indexing did not follow it — it moved the other way, monotonically, over the "
               "30 days since. gsc_serving_pages 63 (08-20) → 39 (08-24) → 13 (08-30) → 5 "
               "(09-03, 09-04); index_state_indexed 10 → 1 across the same window; "
               "index_accept_pct_mature 50% (08-20) → 0.0% every day from 08-26 to 09-04. An "
               "inbound link is therefore necessary but nowhere near sufficient, and on this "
               "site it was not the binding constraint. DISTRUST ITS 'WORKS' VERDICT: "
               "review.py credits it with organic_visitors 9.5/day vs 2.5/day, but "
               "gsc_nonbranded_clicks has been 0 for seven straight days against 67 branded "
               "clicks, so the traffic it is being credited with is jayshomefinder and "
               "findacrib residue that this technique cannot have caused. The metric is "
               "mis-attributed; the audit is not. KEPT, as a guard and an instrument rather "
               "than a growth lever: it is read-only, it is what stops the next section "
               "shipping into an orphan hole, and its click-depth and 'published under no "
               "ACTIVE technique' readings are what the duplication work is steering by. "
               "Its own next improvement is to become a pure docroot reader — drop the "
               "ctx.out staging check and the ledger.set_state first-sighting write — so it "
               "can join techniques.DOCROOT_VERIFIERS and stop reporting a day late."),
    dict(slug="page_uniqueness", status="active", kind="indexing",
         name="Measure how much of each section's text is identical across its own pages",
         prefixes=[], metric="organic_visitors",
         hypothesis="Google is not refusing to find these pages, it is refusing to keep them. "
                    "On 2026-09-02 every published section sits within 3 clicks of the "
                    "homepage, /dc/ and /la/ are still 0-of-20 ever fetched a fortnight after "
                    "being linked from 47,165 pages, and of the 95 sampled URLs Google HAS "
                    "fetched, 94 read 'Crawled - currently not indexed' and one — the "
                    "homepage — is indexed. Some crawled as long ago as 2026-06-24. The "
                    "remaining explanation is that the pages are near-duplicates of each "
                    "other: two adjacent Chelsea building pages rendered from the repo share "
                    "425 of 465 words in identical order (91.4%), and 67 of the 94 "
                    "crawled-not-indexed URLs are building pages. If that is the constraint, "
                    "duplicate share should be high on exactly the tiers Google rejects, and "
                    "cutting it should move accept_pct_mature off 0.0% where nothing else has.",
         evidence="Hand-measured 2026-09-02 on /building/manhattan/246-10th-ave-1007220003/ "
                  "against /building/manhattan/299-10th-ave-1006990031/, rendered from this "
                  "checkout: 91.4% word-for-word overlap, the 40 differing words being the "
                  "street number, three counts, a year, a percentile and one sibling link. "
                  "That is one pair on one checkout, which is why this measures nightly "
                  "instead of asserting.",
         notes="Audits, never publishes, and reports without a threshold on purpose — the "
               "site has no distribution of duplicate share yet, and the depth crawler is the "
               "standing lesson about setting a bar before you have one. Sections come from "
               "the ledger's prefix declarations whatever a technique's status, because a "
               "retired section is still in the docroot and still part of what Google prices "
               "this domain on.\n"
               "[2026-09-20] FIRST EVIDENCE AGAINST THIS HYPOTHESIS, written here so the "
               "2026-10-02 revisit does not have to rediscover it. T046's computed block cut "
               "/building/ duplicate share hard: the hand pair above measured 91.4% "
               "word-for-word overlap, tonight's nightly audit reads 33% of 498 words shared "
               "with siblings. Different instruments, so read the pair as direction and not "
               "as a series. Nine building URLs have since been crawled while carrying the "
               "block (2026-08-25, x4; 08-29; 08-30; 08-31; 09-05; 09-09) and all nine came "
               "back 'Crawled - currently not indexed'. accept_pct_mature is still 0.0 across "
               "88 mature fetched URLs. n=9 cannot overturn the hypothesis, but it is the "
               "first real test of it and it went the wrong way. The revisit should therefore "
               "weigh the site-level explanation — crawl demand and authority — at least as "
               "heavily as the per-page duplication one: weekly crawls have run 24, 16, 11, "
               "16, 9, 2, 2, 3 since 2026-07-27, and no active technique earns a single "
               "external citation.\n"
               "[2026-09-23] THIS AUDIT'S OWN READING IS NOW A VERIFIED INSTRUMENT, which "
               "matters for how much weight the 10-02 revisit gives it. 2026-09-22 shipped a "
               "facts table and conditional footnotes to the /available/ tier and "
               "pre-registered a FALL in that section's duplicate share, explicitly refusing "
               "to predict the figure because a 93-page docroot is a different corpus from the "
               "40-page scratch build it was measured in. Today it reads 42% of 418 words "
               "against 50% of 294 the morning before, same n=24 of 93 — the direction was "
               "right and the reading tracked a change made in a generator this audit has no "
               "knowledge of. That is the second time it has moved on command (T046's "
               "/building/ block was the first) and no time it has moved without one.\n"
               "[2026-09-23] AND A SECOND INDEPENDENT NEGATIVE ON THE HYPOTHESIS ITSELF, from "
               "the index census rather than from content. Between 09-22 and 09-23, 25 of the "
               "458 census URLs moved BACKWARDS from 'Discovered - currently not indexed' to "
               "'URL is unknown to Google' (20 building, 3 zip, 2 neighborhood) and not one "
               "moved forwards; crawled_not_indexed held at 94 and indexed at 1. Google is not "
               "sitting on these pages deciding they are duplicates — it is forgetting it ever "
               "knew about them, which is a discovery and crawl-demand failure and cannot be "
               "caused by the text on a page it has never fetched. Weigh this above every "
               "duplicate-share reading in the revisit."),
    dict(slug="canonical_integrity", status="active", kind="indexing",
         name="Audit canonical and robots tags on the pages the docroot actually serves",
         prefixes=[], metric="organic_visitors",
         hypothesis="The working diagnosis since 2026-09-06 is that Google refuses this "
                    "corpus on quality/duplication grounds, and it may well be right — but "
                    "it has never been tested against the one rival explanation that "
                    "produces an IDENTICAL signature. Current practice names three technical "
                    "causes that mimic crawled-not-indexed at scale: internal linking, crawl "
                    "capacity, and canonicalization. The first two are instrumented here "
                    "(t_crawl_paths, since 2026-08-31) and read green — everything within 3 "
                    "clicks, 16 of 17 sections linked. Canonical tags have never been looked "
                    "at, on any page, on any night. On this site the stakes are specific: "
                    "index_triage() leaves ~46,000 of 47,165 building pages on noindex,follow, "
                    "so a canonical that drifts from a promoted page onto a demoted neighbour "
                    "withdraws that page from the index silently, and no other audit here "
                    "would see it. If the canonical layer reads clean, the duplication "
                    "diagnosis stands on firmer ground than it does today; if it does not, "
                    "the last six weeks of duplication work has been treating a symptom.",
         evidence="Read from the generator, this audit could only ever confirm itself: "
                  "build_seo.page() emits exactly one self-referential canonical from "
                  "`canonical = SITE + url`, and the four app shells and three hand-authored "
                  "pages each carry a correct self-canonical in the checkout. That is the "
                  "reason it reads the DOCROOT instead. 2026-09-12 and 2026-09-13 are the "
                  "standing evidence for why those are different claims: /developers/, "
                  "/embed/ and /marketing-agents/ were correct in git for weeks while the "
                  "live site served something else, because nothing deployed them.",
         notes="Audits, never publishes; adds no URL. Unlike page_uniqueness it DOES fail, "
               "because every class it reports has a known mechanism rather than being a "
               "number with no distribution yet: no canonical, more than one, one pointing "
               "off-host, one pointing at a URL with no page, one pointing at a noindexed "
               "page, and a URL the sitemaps advertise that is noindexed or canonicalized "
               "away on arrival (noindex does not save the fetch — Google requests the page "
               "and then drops it). A cross-URL canonical onto a live indexable page is "
               "counted and named but NOT failed: that is what canonicals are for. Pages "
               "whose </head> sits past the read cap are UNDETERMINED, never 'missing' — the "
               "one way this audit could invent a defect. Member of "
               "techniques.DOCROOT_VERIFIERS, so it is re-read after the SEO watchdog "
               "rebuilds the corpus instead of reporting a day late."),
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
               "only verifies the blocks are present and counts them. "
               "[2026-08-27 revisit] KEEP the block, REJECT the WORKS verdict it carried. It "
               "read 'WORKS — 27 owned visitors in 30d (median 0.5/day but falling)': the "
               "why-string described a halving while the verdict said True. Cause found and "
               "fixed in review.py the same day — the owned-prefix branch set works=True "
               "unconditionally, and its floor is 'total >= 20 OR recent >= 1' where total is "
               "CUMULATIVE, so a sum over a lengthening window cannot fall and a technique "
               "that drew traffic early and nothing since clears it forever. Same "
               "false-positive class fixed on the site-wide paths 2026-08-25 and the stock "
               "metrics 08-26; this branch went through neither. Now reads UNPROVEN. On the "
               "hypothesis itself ('depth on ~370 hubs beats volume'): after 30 days the hubs "
               "hold 9 of 273 ever-served URLs while building pages hold 260, so it is NOT "
               "confirmed — but not refuted either, because mature index acceptance is 0.0% "
               "site-wide and a page Google declines cannot demonstrate depth. The blocks are "
               "built and cost nothing to maintain; re-judge when acceptance is non-zero."),
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

    dict(slug="provenance_page", status="active", kind="indexing",
         name="Published methodology: where every record comes from (/methodology/)",
         prefixes=["/methodology/"], metric="index_accept_pct_mature", judge="site",
         hypothesis="Google is refusing this site wholesale, not page by page. On 2026-09-06 the "
                    "URL Inspection census read 455 sampled published URLs and found ONE indexed "
                    "— the homepage — while all 94 it had fetched and settled on came back "
                    "'Crawled - currently not indexed', spread evenly across every template the "
                    "site owns (67 building pages, 15 neighborhood hubs, 5 borough, 4 ZIP, "
                    "/developers/, /buildings/). Acceptance among pages crawled more than 21 days "
                    "ago has been 0.0% for thirteen consecutive days. Click depth (all sections "
                    "within 3 clicks) and link volume (47,165 pages linking the city tier for a "
                    "fortnight, 0 fetches) were both tested and both died, so what is left is a "
                    "site-level judgement. This site tells people where to live, which puts it in "
                    "the category everything published on trust signals treats most harshly, and "
                    "it had no page stating who compiles the data, from which records, how the "
                    "join is made, how often each part refreshes, or what each city's list does "
                    "NOT mean. Those facts existed only in Python docstrings. Publishing them "
                    "should raise the site-level judgement that gates acceptance.",
         evidence="build_dc.py, build_la.py, build_sf.py and fetch_hpd.py already document every "
                  "source, join key, refresh cadence and limit precisely — nothing had to be "
                  "invented, only published. Named sources with a stated methodology are also "
                  "what the 2026 answer-engine material consistently reports as the thing that "
                  "gets a data publisher cited rather than paraphrased.",
         notes="JUDGED SITE-WIDE ON PURPOSE (judge='site'). It owns /methodology/ so t_crawl_paths "
               "audits its reachability, but a one-page trust artifact judged on its own visitor "
               "count would be retired at day 21 for failing at something it was never for. Its "
               "claim is about index_accept_pct_mature, which is 0.0% today, so there is a real "
               "floor to move and no way to fake a win. It is also the only claimant on that "
               "metric, so the 2026-09-05 co-claimant guard has nothing to demote. If acceptance "
               "is still 0.0% at 2026-09-27, this hypothesis is wrong too and the next honest "
               "suspects are domain history (this domain published jayshomefinder.com before) and "
               "corpus size — not another page.")
    ,
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
               "and GDPR obligations that need a human decision. Needs the Anthropic key.\n"
               "[2026-09-24] REVISIT DECISION: KEEP, AND THE VERDICT ON IT IS MEASURING AN "
               "OUTAGE RATHER THAN AN IDEA. review.py records UNPROVEN on the ground that "
               "mrr_usd went 0 to 0 over 59 days. True, and it cannot mean what it looks like "
               "it means: this technique HAS NOT EXECUTED ONCE IN SIXTEEN CONSECUTIVE RUNS. "
               "last_run.json's outreach record read 'invalid_request_error: Your credit "
               "balance is too low to access the Anthropic API' on every run from 2026-09-08 "
               "to 2026-09-23 inclusive (the 2026-09-24 cron did not fire, so there is no "
               "reading for today) "
               "— the empty-account string, NOT the 'you have reached your specified API usage "
               "limits' string, so it is a balance at zero and not the self-imposed spend cap "
               "that was in force at the end of July. It drafts nothing, so nothing is sent, so "
               "mrr cannot move. A technique that cannot run cannot be judged, and retiring it "
               "on this reading would retire it for the owner's billing state. "
               "WHAT WOULD ACTUALLY TEST IT, so the next revisit is not another no-op: the "
               "question is not whether outreach converts but whether any draft was ever SENT. "
               "This technique writes drafts to growth/outreach_drafts/ and never sends — by "
               "design, because CAN-SPAM and GDPR need a human — so mrr_usd is downstream of a "
               "human step nothing here records. Before the next revisit, either point it at a "
               "metric this loop owns (drafts produced, prospects researched) or accept that "
               "its verdict will stay uninterpretable however long it runs."),
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
               "one to steer by; it survives history eviction via a running dropped total. "
               "2026-08-15: gsc_serving_pages is not an INDEXING number either, which this "
               "note and searchconsole.py's docstring both said it was. An impression needs "
               "the page indexed AND somebody to have searched for something it answers, and "
               "on 47,165 single-address pages the second condition is what almost every "
               "page fails — so '63 of ~47,600 served' is equally consistent with 63 indexed "
               "pages and with 47,000, and those imply opposite next moves. "
               "growth/indexstatus.py now asks the Search Console URL Inspection API for "
               "Google's own coverage state on a stable stratified cohort of ~430 URLs, 100 "
               "a night, and records index_pct / index_pct_building. Read gsc_serving_pages "
               "as the search FOOTPRINT and index_pct as the indexing rate. "
               "[2026-08-27 revisit] KEEP, and disown this technique's own verdict as a "
               "category error. The hypothesis had two halves. The measurement half succeeded "
               "beyond what it claimed: every finding this loop has made since late July — the "
               "serving-tier census, the per-URL history in gsc_pages.json, the 0.0% "
               "mature-acceptance reading, and the 08-27 building-richness test that refuted "
               "T027's criteria — exists only because this technique wired up Search Console. "
               "The 'cheapest rankings' half is REFUTED BY ITS OWN INSTRUMENT: it said page-2 "
               "queries would be cheap wins, and after 30 days tracked_ranking is 0 of 315 — "
               "there is no page-2 tier to harvest because nothing ranks anywhere. Its "
               "standing verdict ('organic_visitors — no measurable lift after 30d') is "
               "meaningless: an instrument cannot move the series it measures, the same "
               "category error corrected for T011/T018 on 08-26. Deliberately NOT repointing "
               "the metric — every candidate is one it also cannot cause, so a repoint would "
               "buy a differently-worded false verdict, not a truer one."),
    dict(slug="lifecycle_email", status="candidate", kind="lifecycle",
         name="Buyer follow-up sequence (Building Report)",
         # reports_sold, not mrr_usd: mrr_usd is monthly RECURRING revenue and the
         # Building Report is a one-time $9 purchase, so the old metric could not
         # have registered this technique's own revenue if it had worked perfectly.
         # reports_sold is a GATE rather than an attribution — this sequence emails
         # people who have already bought and does not cause sales — but while it
         # reads 0 the technique has no audience and any verdict on it is noise.
         prefixes=[], metric="reports_sold",
         hypothesis="Report buyers paid at the highest-intent moment in the funnel and each "
                    "have one specific building they care about. Nudging the free DHCR "
                    "rent-history request — the step that actually establishes overcharge "
                    "and the easiest to put off — is useful enough to earn the open.",
         evidence="Free accounts were the obvious audience but only 3 have ever saved a "
                  "building, too few for the 21-day review to find any signal."),
    dict(slug="account_lifecycle", status="candidate", kind="lifecycle",
         name="Free-account onboarding sequence",
         # accounts_with_saves, not visitors: this sequence has sent 26 emails in
         # 30 days and no onboarding email can move a site-wide visitor count, so
         # "no measurable lift in visitors" was measuring the paid-ad flight and
         # the search collapse, not this. The hypothesis below names the activation
         # rate, and accounts_with_saves is that number.
         prefixes=[], metric="accounts_with_saves",
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
               "explicitly ruled out. "
               "2026-09-11: a fourth step, `saved`, day 5+, to accounts that have saved a "
               "building AND been on the site in the last 14 days. It is the first paid ask "
               "this sequence has ever made, and it exists because the sequence's own metric "
               "kept rising while revenue did not: accounts_with_saves 6 -> 21 since 08-25, "
               "reports_sold and paying_subs 0 for the products' entire lives. An engaged "
               "saver used to receive `welcome` and then nothing ever — `activate` is skipped "
               "once they save, `lapsed` while they keep visiting — so the one audience with "
               "proven intent was the one never asked. Measured by sent_saved (the ask) "
               "against reports_sold (the answer); the ask is only made when a saved building "
               "resolves in the corpus with an HPD record behind it, and never to somebody "
               "who already bought a report."),
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
               "because no SEO-owned shard knows these URLs exist. "
               "2026-08-29 REVISIT — retired 08-20 on '0 owned visitors in 21d, and its pages "
               "earned 0 search impressions across 0 URLs — invisible in search'. That verdict "
               "is withdrawn: the URL Inspection census has now inspected 57 of these URLs and "
               "all 57 come back 'unknown to Google' with not one crawl between them, so the "
               "zero measured the crawler's reach and not the pages. Reactivated with the clock "
               "restarted. The hypothesis itself SURVIVES the revisit on the site's own numbers: "
               "NYC's equivalent aggregate tier (198 neighborhood + 165 zip + 5 borough = 368 "
               "pages) has 9 URLs that have ever earned an impression, 2.4%, against 261 of "
               "47,165 building pages, 0.55% — a 4.4x higher serving rate per page, and NOT a "
               "crawl artefact, because the census fetches the two tiers at almost the same rate "
               "(NYC hubs 23 of 90, buildings 55 of 206). So aggregates do earn more visibility "
               "per page than address pages; this tier is simply the one Google has never "
               "reached. The constraint is crawl reach, not the pages, and the reachability "
               "defect is specific: /<city>/buildings/ is the sole inbound path to these hubs "
               "and is itself uncrawled (3 sampled, 0 fetched), so the whole tier sits behind a "
               "door Googlebot has not opened. Do not re-retire this on an impression count "
               "until at least one of its URLs has been fetched — review.py's census guard now "
               "enforces that."),
    dict(slug="frozen_pages", status="active", kind="indexing",
         name="Audit how old every live page is, so a tier the build has abandoned says so",
         prefixes=[], metric="organic_visitors",
         hypothesis="Both deploy paths on this droplet rsync WITHOUT --delete, on purpose, "
                    "because the docroot also holds the app. So a page a build stops writing "
                    "is not unpublished — it is frozen: still served, out of every sitemap the "
                    "build owns, and stuck at whatever text it carried the last night it "
                    "qualified. Several tiers have data-dependent build sets "
                    "(build_seo.py gates the SF/LA/DC hubs on MIN_CITY_HUB=5, /available/ on "
                    "AVAIL_MIN=3, /landlord/ submits 300 of 1,416, index triage moves ~46,000 "
                    "building pages in and out), so any of them can shrink silently. No audit "
                    "here has ever looked at a page's AGE — all four docroot walks read "
                    "content — which means the loop can neither see a frozen page nor correct "
                    "one, because every fix it ships reaches only the pages still in the build "
                    "set. If frozen pages exist outside /available/, this is the audit that "
                    "names the tier and the run that follows fixes its build set.",
         evidence="Measured by hand on 2026-09-22, which is why this exists: "
                  "t_page_uniqueness read 93 pages under /available/ in the live docroot while "
                  "build_seo.py wrote 41, so 52 live pages — 56% of the section — had not been "
                  "rebuilt for an unknown number of nights and still said 'recently advertised "
                  "for rent' off a feed last refreshed 2026-05-09, three days after a run had "
                  "fixed that exact wording on the 41 pages it could reach. Confirmed against "
                  "growth/index_status.json rather than inferred: 6 of the 15 /available/ URLs "
                  "in the index census were outside the build set and "
                  "/available/bronx/concourse-concourse-village/ read 'Discovered - currently "
                  "not indexed', so Google had a frozen page queued for fetch. The same "
                  "comparison run against the whole census on 2026-09-23 found no OTHER tier "
                  "with a page outside the build set — but the census samples 5 of 1,416 "
                  "/landlord/ pages and 250 of 47,165 building pages, so it cannot rule a "
                  "partial freeze out in a large tier. This audit reads every page.",
         notes="Audits, never publishes, adds no URL, and opens no page — os.stat only, so it "
               "is the cheapest member of DOCROOT_VERIFIERS despite walking the whole corpus. "
               "The mtime is not a proxy for 'last written': rsync -a preserves the source "
               "mtime and build_seo.py's write() rewrites every page in its set every night, "
               "so it is the record. t_sitemap_daily already dates its rescued pages from the "
               "same clock.\n"
               "IT FAILS ONLY ON A PARTIALLY FROZEN TIER — some pages written tonight, others "
               "months old — because that combination can only mean a live build is abandoning "
               "URLs, and that is fixable from this loop by making the page set the published "
               "set. A WHOLLY frozen tier is named just as loudly and does not fail: every one "
               "on this site today is either retired (/brief/, 2026-08-16) or has no deploy "
               "path from here (the app shells, which only scripts/deploy_app.sh reaches). "
               "Failing on those would make the audit permanently red, and a permanently red "
               "audit carries no information.\n"
               "Tiers come from the URL, NOT from the ledger's prefix declarations, which is "
               "the one design choice worth defending: the failure this looks for is a page "
               "nobody is tracking, and /landlord/ (1,416 pages) and /council-district/ (51) "
               "are in no technique's prefixes and appear in no other audit's readings."),
    dict(slug="voucher_reach", status="active", kind="indexing",
         name="Put the nightly voucher feed on the pages Google actually crawls",
         prefixes=[], metric="organic_visitors",
         hypothesis="The AffordableHousing.com voucher feed is the only dataset on this site "
                    "that genuinely changes every night, and until 2026-09-24 it was published "
                    "onto exactly six URLs — /section8/ and five borough pages — which the URL "
                    "Inspection census says Google has never fetched, not once, across their "
                    "whole lives. Meanwhile the ~47,000 building pages and 200 hub pages that "
                    "Google DOES fetch changed only when a monthly rebuild moved them. "
                    "Google's July 2026 crawl-budget documentation is explicit that crawl "
                    "demand follows genuine change, so a site whose only fresh data sits "
                    "behind an unvisited door earns nothing for it. Writing the same dated, "
                    "sourced fact onto the building page of every listed address — no new "
                    "URL, which the 2026-08-25 T002 decision established this domain cannot "
                    "afford — puts nightly change on the daily-crawled surface and puts the "
                    "phrase a voucher holder actually searches on the page about the address "
                    "they are searching. This technique is the audit half: it reads the live "
                    "page of every BBL the feed names and reports how many carry the block.",
         evidence="2026-09-23 URL Inspection census (growth/index_status.json), 458 URLs: "
                  "/building/ 67 ever fetched of 250 sampled, /neighborhood/ 15 of 40, "
                  "/borough/ 5 of 10, / 1 of 1 — and /section8/ 0 of 6, /guide/ 0 of 10, "
                  "/available/ 0 of 15, /brief/ 0 of 10. The committed s8.json snapshot "
                  "carries 253 available listings, 238 of them flagged as accepting vouchers, "
                  "and all 253 BBLs match a building in buildings.min.json.",
         notes="Audits only — it writes no page and adds no URL; build_seo.py writes the "
               "block, this reads it back out of the docroot. It is a CENSUS, not a sample: "
               "the feed names a few hundred BBLs and their page paths are computable, so it "
               "opens exactly those pages. ok is False only when the feed is fresh and not one "
               "page carries the marker, which is the integration being broken. A stale or "
               "undated feed is reported and passes, because build_seo.py suppresses every "
               "voucher claim at that age (48h, the same limit error_report.py already applies "
               "to s8.json) and silence is then the correct behaviour rather than a fault.\n"
               "THE ACCURACY RULE THAT GOVERNS THE COPY IT CHECKS FOR: source-of-income "
               "discrimination is illegal in New York City, so no wording may imply that a "
               "building without a listing refuses vouchers. Every sentence build_seo.py "
               "writes is a claim about a listing on AffordableHousing.com, never about a "
               "landlord's policy, and both the building block and the hub block say so "
               "outright."),
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
                   notes=s.get("notes", ""), judge=s.get("judge"))
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
                               ("prefixes", "prefixes"), ("metric", "metric"),
                               ("judge", "judge")):
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
