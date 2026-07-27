# Find A Crib — growth decision journal

Append-only. One entry per review. The ledger (`techniques.json`) holds what each
technique *is* and how it scored; this holds *why* — what was observed, what was
concluded, what changed as a result, and what to watch next.

Written by the daily 6am review. Do not rewrite past entries; if a conclusion
turns out to be wrong, say so in a new entry.


## 2026-07-26 — Engine goes live
*claude (setup session)*

**Observed.** Organic search is ~3 visitors/day against 47k indexed pages; revenue is $0 (the 6 active subs are the owner plus 5 comps); the Developer API has a working Stripe checkout and zero real signups.

**Concluded.** The bottleneck is indexing and freshness, not content volume — the SEO rebuild ran monthly so IndexNow fired ~once a month. Revenue is a demand problem, not a product problem.

**Changed.** Shipped five daily techniques (voucher pages, dated briefs, llms.txt, daily sitemap, IndexNow), an Enterprise API tier, and drafts-only B2B outreach.

**Watching.** Whether /section8/ earns owned traffic within the 21-day grace period, and whether organic/day moves off ~3 once IndexNow runs daily instead of monthly.


## 2026-07-27 — First cycle: no post-launch data yet, ship Dataset/FAQ schema and 8 keywords
*6am review*

**Observed.** This review ran ~3.5 hours after the engine went live (setup committed 2026-07-26 20:29 ET). The droplet's own crons (05:40 UTC build, 06:00 ET measure) had not fired even once by the time this review ran (checked: 2026-07-27 00:32 UTC, before either scheduled time), so results.jsonl still ends at 2026-07-25 (14 visitors/day baseline, 3 organic) and state.json has no 'lastmod' key at all -- meaning no real (non-dry) build has ever executed. All 5 active techniques (T001-T005, T008) show 'activated: 2026-07-26' with zero days of post-activation owned_visitors data.

**Concluded.** There is nothing to judge yet -- not 'too early' in the usual 21-day-grace-period sense, but literally zero completed cycles. Nothing in the 07-24/07-25 numbers reflects the new techniques at all; that window is pure pre-launch baseline. The one actionable thing this absence itself proves: if next review still shows no lastmod state and no fresh results.jsonl rows, the droplet cron is not actually running (wrong crontab, deploy-key auth failure, or growth.env missing) and needs the owner's hands-on check -- I have no SSH/droplet access to diagnose it myself.

**Changed.** Two additive, low-risk changes verified via py_compile + build --dry-run (and a real non-dry build in an isolated scratch copy, which confirmed valid JSON-LD output on section8 hub/borough pages): (1) Added schema.org Dataset + FAQPage JSON-LD to the /section8/ hub and per-borough pages, and Dataset JSON-LD to /brief/<date>/ pages -- deliberately no 'license' field since the site has never stated a data license and I won't assert one. This targets a real gap: 2026 GEO guidance says structured, extractable data is what AI answer engines cite, and llms.txt alone (T003) only hands over prose, not machine-typed facts about the dataset itself. (2) Added 8 real tracked keywords to growth/keywords.py SEED and regenerated keywords.json (additive-only diff, verified with git diff -- did not touch any existing entry's 'covered' status): section8 borough pages for Queens/Bronx (existing pages, previously untracked), 'voucher friendly apartments nyc', SF/LA/DC exemption and just-cause-eviction queries (real tenant search intent the guide pages don't yet title-target), and two developer-intent queries ('rent stabilization data api', 'nyc housing data api') aimed at the API's demand problem (T007). Did NOT run keywords.check_coverage() against a real docroot -- this sandbox has no built HTML pages (only raw buildings.min.json/s8.json), and I initially ran it against '.' by mistake, which wiped out real coverage data with false negatives; I reverted that and left all 'covered' fields exactly as the droplet last computed them. The next real run's check_coverage(docroot) will fill in the 8 new entries' coverage honestly.

**Watching.** (1) Whether results.jsonl gains rows past 2026-07-25 and state.json gains a 'lastmod' key by the next review -- if not, escalate the cron-not-running hypothesis to the owner directly, don't just keep noting it. (2) Once owned_visitor data exists for T001/T002, whether it's nonzero at all (even 1-2/day would be a real signal this early). (3) Whether the new Dataset/FAQPage JSON-LD validates in Google's Rich Results Test once section8 pages are live and indexed. (4) Coverage delta for the 8 new keywords once check_coverage runs against the real docroot -- 'section 8 apartments queens/bronx' should come back covered=true since those pages already exist; if not, the page title/h1 needs the borough name to match harder.
