# Find A Crib — NYC Rent-Stabilized Buildings Explorer

An interactive map of every DHCR rent-stabilized building in **Manhattan**,
**the Bronx**, **Brooklyn**, **Queens**, and **Staten Island**, with a nightly
signal for which buildings were **recently advertised** for rent, plus the
building's HPD owner / managing agent and open violation & complaint counts.

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

Steps 1–5 produce regenerable intermediates (gitignored); `buildings.min.json`
and `listings.json` are the two files the front end actually fetches.

### HPD data

`fetch_hpd.py` pulls four NYC Open Data datasets and joins them on BBL:

- **Property Registrations** (`tesw-yqqr`) → who registered the building
- **Registration Contacts** (`feu5-w2e2`) → owner / managing agent / head officer name + business address
- **HPD Violations** (`wvxf-dwi5`) → open vs. closed, severity class A/B/C, recency
- **HPD Complaints** (`ygpa-z7cr`) → open vs. closed, recency

Each building shows the operator info, violation/complaint counts, and a
link to that building's full record on HPD Online.

## Front end

`index.html` — a single-file Leaflet map (marker clustering + Street View
thumbnails). No build step; serve the directory statically. An optional Supabase
backend powers email accounts, cross-device saved buildings, and privacy-safe
usage analytics. Copy `config.example.js` → `config.js` and fill in keys.

## Traffic report

`traffic_report.py` prints a traffic dashboard from the Supabase `visits` /
`events` logs: today's numbers, a month-to-month table, the last 14 days,
new-vs-returning, week-over-week retention, and today's activity breakdown. The
owner's own visits are always excluded. Needs the Supabase PAT in the macOS
keychain (`supabase-pat-clockin`).

```sh
python3 traffic_report.py          # dashboard
python3 traffic_report.py --json   # raw JSON
```

## Sources

- NYC Rent Guidelines Board / DHCR 2024 building files
- Coordinates from NYC PLUTO
- Recent-listing signal via a nightly Apify (StreetEasy) refresh
- Owner / managing agent / violations / complaints from NYC Open Data (HPD)
