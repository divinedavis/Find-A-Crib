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
| `growth/scout.py` | Researches and proposes NEW techniques (needs an Anthropic key) |
| `growth/report.py` | The daily email |

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
