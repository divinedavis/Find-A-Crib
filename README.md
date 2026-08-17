# Find A Crib — Rent-Stabilized Buildings Explorer (NYC · SF · LA · DC)

An interactive map of every DHCR rent-stabilized building in **Manhattan**,
**the Bronx**, **Brooklyn**, **Queens**, and **Staten Island**, with a nightly
signal for which buildings were **recently advertised** for rent, plus the
building's HPD owner / managing agent and open violation & complaint counts.

Three more cities ride the same frontend (see **Other cities** below):
**San Francisco** at [/sf/](https://findacrib.com/sf/) (SF Rent Board Housing
Inventory, block-level, with median reported rents), **Los Angeles** at
[/la/](https://findacrib.com/la/) (buildings meeting the RSO criteria, derived
from LA County assessor rolls), and **Washington DC** at
[/dc/](https://findacrib.com/dc/) (properties registered with DHCD as holding
rent-controlled units, with median *registered* rents).

🔗 **Live at [findacrib.com](https://findacrib.com)**

![Find A Crib demo — searching the map, opening a building, filtering by borough](docs/demo.gif)

## How it works

Search by address, neighborhood, ZIP, or BBL, or just pan the map. Every pin is
a rent-stabilized building; clusters show how many sit in an area. Open a
building to see its operator, violation/complaint history, and a link to its
full HPD Online record. Filter by borough, neighborhood, bedroom count, whether
it was recently advertised, and violation/complaint status. Sign in to save
buildings across devices.

## What "recently advertised" means

The map does **not** have real vacancy data. A building is flagged as *recently
advertised* if, in the most recent nightly scrape, a public rental listing had an
address that normalized to that building's BBL. It is a proxy for rental
activity — not a guarantee a unit is available, and not specific to the
rent-stabilized units in the building.

## Data pipeline

| Step | Script | Output |
|------|--------|--------|
| 1. Parse raw DHCR building files | `parse_pdfs.py` | `buildings.json` |
| 2. Geocode addresses (NYC PLUTO) | `geocode.py` | `buildings_geo.json` |
| 3. Assign neighborhood (NTA 2020) | `assign_nta.py` | `buildings_geo_nta.json` |
| 4. Pull HPD owner / manager / violations / complaints | `fetch_hpd.py` | `buildings_hpd.json` |
| 5. Slim + merge HPD into a browser-ready blob | `slim.py` | `buildings.min.json` |
| 6. Nightly listings refresh | `scripts/refresh_listings.sh` (`fetch_apify.py` → `parse_apify.py` → `combine_listings.py`) | `listings.json` |
| 7. Section 8 building signals (monthly) | `fetch_section8.py` — HPD Affordable Housing Production (BBL join) + HUD project-based Section 8 contracts (address→BBL) | `s8.json` (`bldg` half) |
| 8. Live voucher listings (nightly) | `scrape_affordablehousing.py` — AffordableHousing.com search API, address→BBL | `s8.json` (`avail` half) |

Steps 1–5 produce regenerable intermediates (gitignored); `buildings.min.json`,
`listings.json`, and `s8.json` are the three files the front end actually fetches.

### Section 8 / housing vouchers

The **Section 8** filter and the green badges have two tiers:

- **Listed for voucher holders now** — the building has a live listing on
  [AffordableHousing.com](https://www.affordablehousing.com) (ex-GoSection8),
  the site NYCHA/HPD point voucher holders to. Landlords there are explicitly
  soliciting voucher tenants; the badge links to the cheapest such listing.
- **Subsidized / voucher-friendly building** — the building appears in HPD's
  *Affordable Housing Production by Building* (city-financed, income-restricted
  rentals, `hg8x-zxpr`) and/or HUD's *Multifamily Properties – Assisted* with a
  project-based Section 8 contract.

Source-of-income discrimination is illegal in NYC, so the absence of a badge
never means "vouchers not accepted" — the UI says so wherever badges appear and
links to the NYC Commission on Human Rights complaint page.

### Saved-building alert emails

`notify_saved_listings.py` (nightly cron, 05:00 UTC, on the report droplet
alongside `traffic_report.py`) emails signed-in users when a building they
saved is **newly** advertised. It diffs the public `listings.json` (Zumper) and
`s8.json` (AffordableHousing.com) feeds against the previous night's snapshot,
so only fresh listings trigger mail; each (user, building, source) is notified
at most once per 60 days (`listing_alert_state` in Supabase), and the first run
seeds the snapshot without sending. Every email carries a one-click
unsubscribe link (`findacrib.com/#unsub=<token>` → `unsubscribe_alerts` RPC,
tokens in `alert_prefs`; migration `supabase/migrations/0001_listing_alerts.sql`).

```sh
python3 notify_saved_listings.py --dry-run                 # print, no sends
python3 notify_saved_listings.py --test-email you@x.com    # one sample email
```

### HPD data

`fetch_hpd.py` pulls four NYC Open Data datasets and joins them on BBL:

- **Property Registrations** (`tesw-yqqr`) → who registered the building
- **Registration Contacts** (`feu5-w2e2`) → owner / managing agent / head officer name + business address
- **HPD Violations** (`wvxf-dwi5`) → open vs. closed, severity class A/B/C, recency
- **HPD Complaints** (`ygpa-z7cr`) → open vs. closed, recency

Each building shows the operator info, violation/complaint counts, and a
link to that building's full record on HPD Online.

## Other cities

Each city is a directory (`sf/`, `la/`, `dc/`) holding its own
`buildings.min.json` plus an `index.html` generated from the root one by
`build_city_pages.py` — the frontend is city-aware at runtime via
`<html data-city="…">` and the `CITIES` config inside `index.html`, so a new
city is a builder script, a `CITIES` entry, and a `CITY_META` entry.

Only cities that publish **property-level** coverage data get a map (see
`BACKLOG.md` for the ones that don't — most rent-controlled jurisdictions in
the US publish nothing below the municipality level).

| City | Script | Source | Records |
|------|--------|--------|---------|
| San Francisco | `build_sf.py` | DataSF `gdc7-dmcn`, SF Rent Board Housing Inventory (owner-reported, anonymized to the block) | ~12k block-sides |
| Los Angeles | `build_la.py` | LA County Assessor parcels filtered by LAHD's RSO criteria — *derived*, labelled "likely RSO" | ~68k parcels |
| Washington DC | `build_dc.py` | DHCD RentRegistry nightly public CSV exports | ~4.3k properties / 78k covered units |

DC is the only one besides NYC that is an authoritative registry rather than a
derivation. Its exports are discovered at runtime from an unauthenticated
`api/ListExports` endpoint (see the `build_dc.py` docstring); coverage there is
a *per-unit* determination, so the script counts non-exempt units from the unit
file rather than trusting a building-level flag.

## Front end

`index.html` — a single-file Leaflet map (marker clustering + Street View
thumbnails). No build step; serve the directory statically. An optional Supabase
backend powers email accounts, cross-device saved buildings, and privacy-safe
usage analytics. Copy `config.example.js` → `config.js` and fill in keys.

## Growth engine

`growth_daily.py` + the `growth/` package run a self-improving loop for organic
traffic and revenue. Two crons on the web droplet (`/etc/cron.d/rentmap-growth`):

| When | Command | What it does |
|------|---------|--------------|
| 05:40 UTC | `growth_daily.py build --deploy` | Rebuilds the daily pages from the overnight voucher feed, deploys them, submits new URLs to IndexNow |
| 06:00 ET | `growth_daily.py daily --email …` | Measures yesterday, judges every active technique, retires the dead ones, scouts for new techniques, mails the report |

A third job runs in Anthropic's cloud, not on the droplet:

| When | What |
|------|------|
| 06:00 ET | **Daily growth review** — a Claude Code routine reads the ledger, journal and measurements, judges whether last week's changes worked, researches what's currently working, changes something, and logs its reasoning |

That agent has only a git checkout — no SSH, no keys, no database. **Git is the
channel between it and production:** it pushes ledger and code changes, and
`growth_run.sh` pulls them in before each droplet run and pushes the night's
measurements back. The droplet's daily pass therefore runs at 05:00 ET, an hour
ahead of the review, so the agent always reads fresh numbers.

**Reading whether the droplet ran at all.** Because git is the only channel,
silence in git is the only symptom the review agent sees — and silence has three
causes needing three different fixes: the cron never fired, it fired and the run
crashed, or it ran and the push was lost. `growth_run.sh` therefore appends a
`start` and a `finish` record to `growth/cron_heartbeat.jsonl` around every
invocation, carrying the exit code, the pull's outcome and — on failure only —
the last two lines of output, and commits that file whether or not the run
succeeded. **Every invocation leaves a commit**, so no commit for a morning now
means the script did not run, full stop. `growth_daily.py status` prints the
verdict first; read it before anything else. Two failure modes it names directly:
a `start` with no `finish` is a run that died mid-flight, and `"pull":"recovered"`
means an operator push collided with the droplet's own ledger write. That
collision used to be silent and permanent — `git pull --rebase --autostash`
exits **0** when the autostash pop conflicts, leaving `<<<<<<<` markers in
`growth/techniques.json`, which `ledger.load_techniques()` refuses to parse on
that run and every run after it. The script now checks `git ls-files -u`
independently of the pull's exit code and resets the conflicted paths to
`origin/main`, which is safe because the droplet is their only writer and pushes
them every run.

**What a git push does and does not deploy.** Only two paths reach the docroot
on their own: `growth_daily.py build --deploy` rsyncs `growth_out/`, and
`scripts/refresh_seo.sh` rsyncs `build_seo.py`'s `seo/`. **Nothing in either
cron deploys the root `index.html`** — the app shell is copied to the docroot by
hand ("no build step; serve the directory statically", above). So a change the
review agent pushes to `index.html` sits in git until someone deploys the app,
while a change to `build_seo.py` or `growth/techniques.py` goes live the next
morning. This is not obvious from the checkout and has already cost one review
cycle: on 2026-08-05 the review fixed two orphaned sections by adding links to
`index.html`, and the 2026-08-06 audit correctly still reported them orphaned.

Those two paths are not equally reliable, either. `refresh_seo.sh` is chained
after the listings scrape and stops when anything ahead of it fails — it wrote
nothing between 2026-08-01 and 08-08, so a `build_seo.py` change is only live
once that pipeline recovers. The growth build's own rsync is the path that can
be observed working every morning (`growth/last_run.json` → `build.deployed`,
and `build.seo_corpus` for how stale the other one is). So prefer whichever of
the two is currently running for anything site-wide, and check `seo_corpus`
before assuming a `build_seo.py` edit shipped.

**Reading why the SEO pipeline stopped.** `build.seo_corpus` is an mtime: it
dates the freeze but never explains it, and "the cron never fired", "`build_seo.py`
crashed" and "the rsync failed" are three different owner actions behind one
identical number. Four mornings in August 2026 were spent unable to tell them
apart. Since 2026-08-12 `refresh_seo.sh` writes `.seo-build-status.json` into
the **docroot** at start and again on exit — naming the step in flight, the exit
code, the commit it built from and how many pages the build produced — and the
05:40 growth build reads it (`techniques._seo_pipeline_status`) into
`growth/last_run.json` → `build.seo_pipeline`, which it commits. The docroot is
the only place both pipelines can see, and the growth build's push is the only
channel that reaches the cloud review; `refresh_seo.sh` runs from a different
checkout and never commits. `growth_daily.py status` prints the verdict under
the cron line, and the daily report names the failing step in its "SEO corpus
frozen" callout. Unlike `cron_heartbeat.jsonl`, that record carries **structured
fields only, never captured output** — the docroot is web-served and `$BUILD`
holds `indexnow.key`. It also catches one failure the mtime cannot: a build that
completes and rsyncs a *truncated* corpus looks freshly written, so a clean run
reporting fewer than 1,000 pages is reported as a break.

Read a **missing** status record carefully, because it is the one case with two
meanings. The script pulls itself (`STEP=pull` is inside it), and bash has
already read the file by then, so a cron that fires at all picks the new version
up on one run and self-reports from the *next* one. An absence on its own, with
a fresh corpus, therefore means nothing.

**A frozen `seo_corpus` is decisive on its own, though, and does not need the
status record at all** — this was worked out on 2026-08-14 and it settles the
question a day earlier than the rule that used to sit here. `build_seo.py`'s
`write()` opens and rewrites *every* file it emits on *every* run, unconditionally
(only `<lastmod>` is content-aware, via `LM_STATE`), and `sitemap-main.xml`
embeds `BUILD_DATE`. So a healthy run gives each `sitemap-*.xml` in `$BUILD` a
fresh mtime and fresh bytes even on a night when no page changed, and `rsync -a`
copies them across. **A docroot `sitemap-*.xml` older than a day therefore proves
`refresh_seo.sh` did not reach `STEP=deploy`, whatever the status record says.**
The status record then only distinguishes *how* it stopped: present means it ran
and died at the named step; absent means it never started, because `status start`
is written before the pull and before the build, so even an instant crash leaves
the file behind.

**The watchdog.** On 2026-08-14 the corpus had been frozen since 08-08 with no
status record, i.e. six nights of the 04:10 cron not firing, which stranded every
`build_seo.py` change since 08-01 in git. The cloud review cannot touch cron —
but `growth_run.sh` is on the droplet, in the right checkout, with `GROWTH_DOCROOT`
already set, and it demonstrably runs every morning. It now re-runs the refresh
the missing cron owes: `seo_watchdog()` fires only on the `build` job, only when
every non-growth-owned `sitemap-*.xml` in the docroot is more than `SEO_STALE_DAYS`
(default 2) old, under `flock` and `timeout` (default 3600s), with every failure
swallowed so it can never cost the night's ledger push. It runs
`./scripts/refresh_seo.sh` from the growth checkout — which `growth_run.sh` has
just pulled — rather than the copy in `$SEO_BUILD`, so the script is always the
newest version instead of one night behind its own self-pull; `refresh_seo.sh`
cds to `$SEO_BUILD` and pulls it, so the data and build dir are unchanged. Its
outcome lands in `cron_heartbeat.jsonl` as `seo_watchdog_start` /
`seo_watchdog_finish`, which is committed and pushed, so the review reads the
result the same morning. Set `GROWTH_SEO_WATCHDOG=0` in `growth.env` to stop it —
that is the switch to use if the pipeline is ever stopped on purpose. **If a new
growth-written `sitemap-*.xml` is ever added to the docroot it must be excluded
in `seo_watchdog()` as well as in `GROWTH_OWNED_SITEMAPS`, or the watchdog reads
it as freshness and silently stops firing.**

**Publishing a page and getting it into a sitemap are two separate jobs, and the
handover between the pipelines dropped the second one.** `t_sitemap_daily` built
`sitemap-daily.xml` purely from the lastmod state — the URLs *this* build wrote
— and `Ctx.unstage()` deletes a URL's lastmod entry when it hands a page back to
the SEO pipeline, reasoning that "the URL is no longer ours to list". That holds
only if the pipeline then lists it. For the SF/LA/DC hub tier it did not: on
2026-08-17 the docroot held 103 DC, 112 LA and 37 SF hub pages while the docroot
sitemaps carried **two URLs per city**, so 252 finished pages had no sitemap
entry anywhere, and the URL Inspection sample that morning came back *unknown to
Google* — never fetched — for 80% of what it read. `t_sitemap_daily` now lists
the union of what this build wrote and every page in a family it owns
(`/section8/`, `/brief/`, `/guide/`, the city hub tier) that is live in the
docroot but absent from every pipeline-owned shard. That second set is read off
the filesystem and never asserted: a page is listed only if it exists, dated by
its own mtime rather than today, and it leaves this shard by itself the day the
pipeline starts listing it. The `rescued` count in the technique's detail line is
the size of the hole — it should fall to 0 when the pipeline emits its own city
shards, and a jump means the pipeline dropped a tier.

One consequence of that ordering: **`build` runs every technique first and
rsyncs last**, so any check that reads the docroot is scoring the *previous*
run's deploy. `t_crawl_paths` therefore also reads `growth_out/` and says
"awaiting this run's rsync" for a link it staged minutes earlier, rather than
reporting an orphan that is already fixed. That fallback only works if the audit
runs *after* the technique that stages the page — `t_hub_direct_answers` sat
ahead of both city-hub publishers in `techniques.ORDER` until 2026-08-12 and so
reported the previous night's docroot as though it were the current run's
result, which cost two reviews a wrong prediction. Audits go after publishers.

**Two different link audits, at two different scales.** `t_crawl_paths` asks
whether each *section* has an inbound link at all — a whole family orphaned. It
cannot see the other failure, which is a family that is linked but only barely:
until 2026-08-13 every building page's "Other rent-stabilized buildings in
&lt;neighborhood&gt;" list was `sorted_by_address[:12]`, identical on every page
in the neighborhood, so 13 addresses per neighborhood collected every sibling
link and **44,738 of 47,165 building pages (94.9%) had two or fewer inbound
internal links** — 11,294 had exactly one. `build_seo.py` now takes a window
around each page's own position in a geographically snaked order
(`_geo_ring_order` / `_ring_window`), which makes the neighborhood a ring: every
page links to 12 siblings and is linked from 12, and the listed buildings are
genuinely next door (median 76 m apart in the East Village, against 466 m
before) instead of alphabetical neighbours. The ordering is deterministic
because `seo_lastmod.json` only bumps `<lastmod>` when a page's HTML really
changed, and a shuffled list would rewrite 47,165 lastmods every night.

**"Indexed" and "earns impressions" are different numbers, and conflating them
cost three weeks.** `gsc_serving_pages` counts distinct URLs that earned a
Search Console impression in the window. Until 2026-08-15 every review, the
daily report's "Indexing" bar and `searchconsole.py`'s own docstring read that as
*how much of the corpus is indexed* — but an impression needs the page indexed
**and** somebody to have typed a query it could answer, and on 47,165
single-address pages the second condition is the binding one for almost every
page. "63 of ~47,600 pages served" is equally consistent with 63 indexed pages
and with 47,000 of them, and the two imply opposite next moves: consolidate the
corpus, or stop publishing address pages and go where the search demand is.

`growth/indexstatus.py` measures it directly. The Search Console **URL
Inspection API** returns Google's own coverage state per URL ("Submitted and
indexed", "Crawled – currently not indexed", "Discovered – currently not
indexed", a Google-chosen canonical that is not ours, …). Its quota is 2,000
URLs/day per property against ~47,600 pages, so it samples:

* a **stable cohort** (~430 URLs) persisted in `growth/index_status.json`, so a
  move in the indexed rate is Google changing its mind rather than a different
  draw. Members leave only when they leave the sitemaps; top-ups are picked in
  `sha1(url)` order so they do not depend on build order.
* **stratified by page family**, because `/building/` is 99% of the corpus and
  0% of the interesting question. Any family not named in `COHORT` still gets
  `DEFAULT_QUOTA` slots, so a technique that ships a new URL prefix is sampled
  without anyone remembering to edit the dict.
* `GROWTH_INDEX_BUDGET` (default 100) inspections per night, oldest reading
  first *within each family* and the families interleaved in proportion to their
  size, so the whole cohort still refreshes in ~4 days and every stratum is
  measured on the **first** night. A single global sort by `(checked, sha1)` is
  not equivalent and was the bug fixed on 2026-08-17: `reconcile()` tops a
  family up with its lowest-hashing candidates, so `/building/`'s 250 URLs — the
  250 lowest hashes out of 47,165 — sorted ahead of nearly everything else, and
  196 of the first 198 URLs ever read were `/building/`. The interleave also
  pins each family's oldest member to the front of the night, because a family
  smaller than `cohort/budget` members otherwise never comes up at all.

It runs inside `measure`, needs the same service-account key as the rest of
Search Console, and never raises — a measurement job must not be why the night's
other measurements go unrecorded. Every exit path writes an explicit `ok` into
`last_run.indexstatus` (the 2026-07-28 lesson: `outreach.run()` omitted `ok` on
success and the report announced a healthy job as "DID NOT RUN"). A `403` stops
the run after one call rather than burning the quota — the URL Inspection API
requires the service account to be an **owner or full user** of the property, and
a restricted user gets `403` on every call. Set `GROWTH_INDEX_STATUS=0` to
disable. The file holds public URLs and Google's public opinion of them, no PII,
so it is tracked in git and the cloud review can read it — via the `git add`
allowlist at the end of `growth_run.sh`, which is what "tracked" actually means
here and which this file was missing until 2026-08-16.

The rate on its own does not say what to do. `index_state_<bucket>` records the
**site-wide coverage-state split** into `results.jsonl` every night, dense over
`indexstatus.BUCKETS` so a zero is a recorded fact rather than a gap. It is the
diagnosis: *unknown to Google* is Google having no record of the URL at all, so
the problem is upstream of both of the others and the fix is discovery — a
sitemap entry and internal links, not better pages; *discovered, never crawled*
is Google knowing the URL and declining to spend a crawl, a budget/priority
problem, so submit fewer and better-linked URLs; *crawled, not indexed* is
Google fetching the page and refusing it — a quality/duplication judgement, so
consolidate or strengthen the pages. `index_status.json` only ever holds each
URL's latest state, so this series is the only thing that can show pages *moving*
between those states after a fix.

Read the state string literally and check the discriminator before building on
it: `unknown_to_google` is Google's answer about the URL, `unknown` is the API
returning no coverage state at all, and Google has been observed relabelling
long-known URLs "unknown". A URL it has genuinely never fetched also carries no
`lastCrawlTime` and `pageFetchState: PAGE_FETCH_STATE_UNSPECIFIED`; a relabelled
one keeps its crawl time. On 2026-08-17 all 159 "unknown" readings had no crawl
time and all 39 known ones had both a crawl time and `SUCCESSFUL`.

Everything is driven by a **ledger** (`growth/techniques.json`), so the ledger —
not the code — decides what runs. Flipping a technique to `retired` stops it
without a deploy, which is what lets the review loop prune autonomously.

| Module | Role |
|--------|------|
| `growth/ledger.py` | The registry + append-only measured results |
| `growth/techniques.py` | The executable techniques (one `t_<slug>` function each) |
| `growth/metrics.py` | Daily traffic / funnel / revenue, attributed per technique |
| `growth/review.py` | Judges, retires, and de-duplicates techniques |
| `growth/keywords.py` | The tracked query universe the search-share goal is measured against |
| `growth/searchconsole.py` | Positions, serving pages and per-page impressions from Search Console |
| `growth/indexstatus.py` | Google's own index coverage for a stable stratified sample of pages |
| `growth/scout.py` | Researches and proposes NEW techniques (needs an Anthropic key) |
| `growth/outreach.py` | Daily B2B prospect research + drafted outreach — **never sends** |
| `growth/journal.py` | The decision journal: what was observed, concluded, changed, watched |
| `growth/report.py` | The daily email |

The **ledger** records what a technique is and how it scored; the **journal**
(`growth/journal.md`) records why anything changed. Both are tracked in git, so
the file history doubles as a tamper-evident record of when each decision was
made — that history is the year-end "what worked" list.

A technique must be **idempotent** (it runs every day), **honest** (it never
publishes an empty page just to have a URL to submit), and **attributable** (it
declares the URL prefixes it owns, so `review.py` can tell whether it actually
earned traffic). Site-wide techniques declare no prefixes and are judged on a
global series instead.

The scout proposes; it does not deploy. It can write ledger candidates and add
tracked keywords, but it cannot write code, change the live site, spend money,
or send mail — an unattended loop with commit rights eventually ships something
broken at 6am on a Sunday.

```sh
python3 growth_daily.py build --dry-run       # what would be published
python3 growth_daily.py status                # the ledger + keyword coverage
python3 growth_daily.py measure --days 30     # backfill measurements
python3 growth_daily.py report                # print the daily report
```

State (`techniques.json`, `keywords.json`, `results.jsonl`, `state.json`) lives
on the droplet at `/root/dhcr-build/growth/` and is gitignored; `seed.py` and
`keywords.py` hold the definitions that recreate it from scratch.

**Edit a seeded technique's prose in `seed.py`, never in `techniques.json`.**
`cmd_build` calls `seed.run()` first, and for every slug in `SEEDS` it copies
`name`, `hypothesis`, `evidence`, `notes`, `prefixes` and `metric` from the seed
over whatever the ledger holds — deliberately, so those definitions live in code
and in review, but it means a hand-edit to any of those six fields in
`techniques.json` survives exactly until the next 05:40 build and then vanishes
with no error. (`status`, `verdict`, `revisit_on`, `activated` and the measured
history are *not* touched, so `set_status` / `set_verdict` / `set_revisit` are
safe to call directly.) This is the likeliest explanation for the 2026-08-12
review whose journal entry claimed a ledger note its diff did not contain: the
note was written, committed, and then overwritten by the next build.

## Traffic report

`traffic_report.py` prints a traffic dashboard from the Supabase `visits` /
`events` logs: today's numbers, a month-to-month table, the last 14 days,
new-vs-returning, week-over-week retention, and today's activity breakdown. The
owner's own visits are always excluded. Needs the Supabase PAT in the macOS
keychain (`supabase-pat-clockin`).

```sh
python3 traffic_report.py                      # dashboard
python3 traffic_report.py --json               # raw JSON
python3 traffic_report.py --email a@b.com      # email the dashboard
```

Emailing uses `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` from the
environment. A weekly cron on the caprecruiting droplet (167.71.170.219,
`/root/findacrib-report/`) mails this to the owner every Monday 8am ET.

## Sources

- NYC Rent Guidelines Board / DHCR 2024 building files
- Coordinates from NYC PLUTO
- Recent-listing signal via a nightly Apify (StreetEasy) refresh
- Owner / managing agent / violations / complaints from NYC Open Data (HPD)
- SF Rent Board Housing Inventory via DataSF (`gdc7-dmcn`)
- LA County Assessor parcel rolls, filtered by LAHD's RSO criteria
- DC DHCD RentRegistry public data exports; DC neighborhood label points (DCGIS)
  and Census 2020 ZCTAs for DC neighborhood/ZIP assignment
