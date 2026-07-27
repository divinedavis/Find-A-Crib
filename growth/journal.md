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


## 2026-07-26 — Correcting yesterday's review: the crons were running
*claude (setup session)*

**Observed.** The 2026-07-27 review concluded 'no real (non-dry) build has ever executed' from an absent lastmod key in state.json. That was wrong. Builds had run and deployed on 07-26 (IndexNow accepted 8 URLs, HTTP 200) and results.jsonl held a 21-day backfill. state.json is gitignored — it carries per-URL content hashes and visitor ids — so the cloud agent literally cannot see it, and read invisible as nonexistent.

**Concluded.** The review reasoned correctly from what it could see; the fault was mine, in giving it no way to distinguish 'the cron did not fire' from 'that file is not in the repo'. Left unfixed it would have escalated a false cron failure. A second, sharper flaw surfaced the same run: check_coverage() run against a bare checkout marks every query uncovered, silently replacing real coverage history with false negatives — the review did this, caught it, and reverted, but the next one might not.

**Changed.** Added growth/last_run.json, tracked in git and written by build and measure: what ran, when, and what it did, with no hashes or ids. check_coverage() now refuses to run unless the target actually looks like a built docroot. Also fixed a deploy bug this exposed — growth_run.sh existed untracked on the droplet and blocked git pull, so the review's changes did not reach production until removed; the pull-failure fallback did its job and the build still ran on the local copy.

**Watching.** That the next review reads last_run.json and does NOT repeat the cron-failure alarm. Its own predictions still stand: whether /section8/ and /brief/ earn any owned visitors, and whether the new Dataset/FAQPage JSON-LD (verified live and valid on /section8/ — 4 blocks) shows up in Rich Results.


## 2026-07-27 — Found the real reason last_run.json never arrived: growth_run.sh's git add list missed it; ship a rendered FAQ and 8 keywords
*6am review*

**Observed.** One full day of post-activation data exists: 2026-07-26 (activation day) had 11 visitors, 1 organic, 0 AI — below the pre-launch baseline of ~14/day, ~3 organic. fresh_section8 and daily_brief show owned_visitors=0 for 07-26, the only post-activation row. That is one noisy day, not a trend. growth/last_run.json — the ground-truth file the 2026-07-26 correction commit (e38e539) added specifically so this review can tell a real cron failure from an invisible gitignored file — was itself absent from this checkout. Root cause found by reading growth_run.sh: write_last_run() writes it correctly on the droplet, but the nightly commit line only runs 'git add -A growth/techniques.json growth/keywords.json growth/results.jsonl growth/journal.md' — last_run.json was never added to that list, so it is generated every night and never pushed. Separately, the /section8/ hub page emits FAQPage JSON-LD (SECTION8_FAQ, 2 Q&A pairs) but never rendered that text anywhere in the visible HTML body — schema describing content that does not exist on the page.

**Concluded.** The cron-failure question from the last two entries is still genuinely unresolved by data, but for a newly-diagnosed reason: the messenger was broken, not the signal. This was not a repeat of the 07-26 false alarm (that one misread an invisible gitignored file as absent; this one is a real, verifiable bug in a tracked file, confirmed by reading growth_run.sh directly). It is too early to judge T001/T002/T004/T005 on one day of data regardless. The hidden-FAQ gap is a real, if modest, GEO/schema-compliance defect: AI answer engines extract from rendered text far more reliably than JSON-LD, and Google's own guidance expects structured data to reflect visible content.

**Changed.** (1) Fixed growth_run.sh: added growth/last_run.json to the nightly git add list, so tonight's build/measure run should finally push it and next review can read real droplet ground truth instead of inferring from its absence. (2) Rendered SECTION8_FAQ as visible HTML (new _faq_html() in techniques.py, styled via .faq-item) on the /section8/ hub page, directly beneath the existing content — the FAQPage JSON-LD now describes real on-page text instead of standing alone. Verified via a real (non-dry) build into an isolated scratch docroot: 2 faq-item blocks rendered with the exact question/answer text, all 4 JSON-LD blocks (BreadcrumbList, ItemList, Dataset, FAQPage) still parse. (3) Added 8 additive-only tracked keywords to keywords.py SEED: NYC rent-guidelines-board and lease-renewal queries (timely — RGB sets its annual allowable increase around this time of year), 'how much can rent go up' variants for SF/LA/DC to match the pattern the NYC list already had but the other three cities lacked, and one more developer-intent query ('affordable housing dataset api') for T007's demand problem. Verified via git diff that no existing keywords.json entry's covered/position/etc. fields were touched — did not run check_coverage() against this checkout.

**Watching.** (1) Whether growth/last_run.json actually appears in the repo after tonight's droplet run — if it still doesn't, the bug diagnosis here was wrong and needs revisiting, not the git-add fix repeated. (2) Whether 07-27 and 07-28 owned_visitors for fresh_section8/daily_brief stay at 0 or turn nonzero — two data points is still not a trend, but a third and fourth zero should start to weigh against the hypothesis. (3) Whether the visible FAQ block shows any measurable effect on ai_visitors (T003's metric) — unlikely to be visible in days, but worth a first look after ~2 weeks. (4) Coverage numbers for the 8 new keywords once a real check_coverage(docroot) runs on the droplet.

## 2026-07-27 — Anthropic key installed; scout runs; three bugs it exposed
*claude (setup session)*

**Observed.** Key installed to keychain and the droplet. First API call returned 'credit balance is too low' (a real 400 at that moment); minutes later calls succeeded, so credits landed or propagated. First real scout run then failed parsing its own output — web-search answers overran max_tokens=4000 and truncated the JSON mid-object. Second run proposed 3 techniques (T015 Dataset schema on all 47k building pages, T016 embeddable address-lookup widget for reporters/tenant orgs, T017 one-time paid Building Report) and 23 keywords.

**Concluded.** T017 is the sharpest finding so far and reframes the revenue problem: most visitors need this data exactly once, before signing a specific lease, so a $4.99/mo recurring ask is wrong at the highest-intent moment. That is a better explanation for zero paid conversions than 'not enough traffic'. Separately, 8 of the 23 proposed keywords were paraphrases of tracked ones ('...rent controlled sf' vs '...san francisco') because the scout prompt listed existing techniques but never existing keywords — padding the universe with restatements would make the 90%-share denominator meaningless.

**Changed.** max_tokens 4000→8000 and extract_json now salvages truncated JSON by walking back to the last balanced position, dropping the partial entry rather than guessing it. Anthropic errors now carry the API's own message instead of a bare 'HTTP 400', and the daily report gained a RESEARCH JOBS BLOCKED section so a job that is merely out of credit no longer looks like one with nothing to say. Scout prompt now lists tracked queries. Added a fingerprint dedup to keywords.add(). NOTE: my first dedup attempt was too aggressive — it treated 'lookup'/'list'/'for rent' as noise and destructively dropped 10 entries including 'rent stabilized apartments for rent', a listings query merged into an explainer. Restored from git and narrowed the noise list to genuinely contentless words; only 1 real paraphrase now dedupes. Universe: 68 queries, 50% covered.

**Watching.** Whether tomorrow's 6am review proposes something overlapping T015 (the cloud agent already shipped Dataset/FAQPage markup on /section8/ — the scout does not yet know what the review agent built). Whether the salvage path ever fires again now that max_tokens is 8000. Whether keyword coverage moves off 50% as the review agent targets uncovered queries.
