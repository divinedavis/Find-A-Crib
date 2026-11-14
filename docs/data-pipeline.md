# Data pipeline, alerts and cities

Moved from the README on 2026-11-06. Back to the [README](../README.md).

Every script named here lives in `pipeline/` (moved from the repo root on
2026-11-13); run them from the repo root, e.g. `python3 pipeline/fetch_hpd.py`.

## Data pipeline

| Step | Script | Output |
|------|--------|--------|
| 1. Parse raw DHCR building files | `parse_pdfs.py` | `buildings.json` |
| 2. Geocode addresses (NYC PLUTO) | `geocode.py` | `buildings_geo.json` |
| 3. Assign neighborhood (NTA 2020) | `assign_nta.py` | `buildings_geo_nta.json` |
| 4. Pull HPD owner / manager / violations / complaints | `fetch_hpd.py` | `buildings_hpd.json` |
| 5. Slim + merge HPD into a browser-ready blob | `slim.py` | `buildings.min.json` |
| 7. Section 8 building signals (monthly) | `fetch_section8.py` — HPD Affordable Housing Production (BBL join) + HUD project-based Section 8 contracts (address→BBL) | `s8.json` (`bldg` half) |
| 8. Live voucher listings (nightly) | `scrape_affordablehousing.py` — AffordableHousing.com search API, address→BBL | `s8.json` (`avail` half) |

Steps 1–5 produce regenerable intermediates (gitignored); `buildings.min.json`
(split into `buildings.slim.json` + `buildings.hpd.json` by `split_hpd.py`),
`s8.json` and `fmr.json` are the files the front end fetches.

Scripts live in `pipeline/` and the data they commit lives in `data/`: the
DHCR source PDFs (`data/dhcr/`), boundary files, hand-curated lists
(`rerental_pages.json`, `owner_vacancy_pages.json`, `agent_buildings.json`,
`housing_law_firms.json`) and snapshots of the published feeds
(`buildings.min.json`, `s8.json`, `fmr.json`, `hcr.json`). The site still serves
each feed at the root (`findacrib.com/fmr.json`); production jobs write the live
copies straight to the web docroot, so the `data/` copies are what a fresh
clone and the tests read. Regenerable intermediates stay gitignored.

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

Saving a building is subscribing to it. `saved_alerts.py` (06:20 ET daily on
the web droplet, `saved_alerts.sh`, `/etc/cron.d/rentmap-saved`) emails every
signed-in saver when a saved building gets a voucher listing (`s8.json`) or
its voucher-listing rent drops,
hosts a Housing Connect / HCR lottery or a marketing-agent re-rental (matched by
house number + lot distance / street), gains or clears open HPD violations, or
has its DHCR registration change. Only a *change* alerts: the first run seeds a
snapshot (`saved_alerts_state.json`) and sends nothing; each (user, building,
kind) is announced at most once per cooldown (`listing_alert_state`, via the
`saved_alert_state` / `saved_alert_mark` RPCs in `db/0024`). Tuesdays the same
run sends the weekly round-up instead: pending changes, the state of everything
saved, and what opened / closes this week in the boroughs the person saves and
browses in (`building_view` events). New accounts that saved something get a
"status" email 2–8 days in. Opt-outs: `findacrib.com/#unsub=<token>` (alerts)
and `#unsub=<token>&k=digest` (round-up only), tokens in `alert_prefs`.

**One email a day, per address, across every job.** `growth/mailcap.py` claims
the New York day in `public.email_sends` (`email_claim` / `email_release`)
before any send; the borough dispatcher, this job, the account lifecycle and
the report sequence all use it. A job that loses the slot holds its content
(`state["held"]` per subscriber, `state["pending"]` per user) for tomorrow.

```sh
python3 pipeline/saved_alerts.py --dry-run                        # print, no sends
python3 pipeline/saved_alerts.py --weekly --dry-run               # force the digest
python3 pipeline/saved_alerts.py --test-email you@x.com           # one sample email
python3 pipeline/lottery_alerts.py --nudge --dry-run              # first-week round-up
python3 pipeline/lottery_alerts.py --weekly --test-email you@x.com
```

The map's first view: `/api/geo` resolves the visitor's network address
against DB-IP City Lite (`scripts/refresh_geoip.sh`, monthly cron) and returns
a ~1 km point plus the borough of the nearest building; `index.html` opens
there on a bare landing with a dismissible chip. No browser permission prompt,
nothing stored.

### HPD data

`fetch_hpd.py` pulls four NYC Open Data datasets and joins them on BBL:

- **Property Registrations** (`tesw-yqqr`) → who registered the building
- **Registration Contacts** (`feu5-w2e2`) → owner / managing agent / head officer name + business address
- **HPD Violations** (`wvxf-dwi5`) → open vs. closed, severity class A/B/C, recency
- **HPD Complaints** (`ygpa-z7cr`) → open vs. closed, recency

Each building shows the operator info, violation/complaint counts, and a
link to that building's full record on HPD Online.

## Other cities

Each city is a directory (`web/sf/`, `web/la/`, `web/dc/`) holding its own
`buildings.min.json` plus an `index.html` generated from the root one by
`build_city_pages.py` — the frontend is city-aware at runtime via
`<html data-city="…">` and the `CITIES` config inside `index.html`, so a new
city is a builder script, a `CITIES` entry, and a `CITY_META` entry.

Only cities that publish **property-level** coverage data get a map (see
[`BACKLOG.md`](BACKLOG.md) for the ones that don't — most rent-controlled jurisdictions in
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

`web/index.html` — a single-file Leaflet map (marker clustering + Street View
thumbnails). No build step; `web/` is laid out like the docroot, and
`python3 scripts/preview.py` shows it over the live site's data. An optional Supabase
backend powers email accounts, cross-device saved buildings, and privacy-safe
usage analytics. Copy `web/config.example.js` → `web/config.js` and fill in keys.

