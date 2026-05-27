# Rent Map — NYC Rent-Stabilized Buildings Explorer

An interactive map of every DHCR rent-stabilized building in **Manhattan** and
**Brooklyn**, with a nightly signal for which buildings were **recently
advertised** for rent on Zumper.

Deployed at [https://jayshomefinder.com](https://jayshomefinder.com).

## What "recently advertised" means

The map does **not** have real vacancy data. A building is flagged as *recently
advertised* if, in the most recent nightly scrape, a public rental listing on
Zumper (or RentHop) had an address that normalized to that building's BBL. It is
a proxy for rental activity — not a guarantee a unit is available, and not
specific to the rent-stabilized units in the building.

## Data pipeline

| Step | Script | Output |
|------|--------|--------|
| 1. Parse raw DHCR building files | `parse_pdfs.py` | `buildings.json` |
| 2. Geocode addresses (NYC PLUTO) | `geocode.py` | `buildings_geo.json` |
| 3. Assign neighborhood (NTA 2020) | `assign_nta.py` | `buildings_geo_nta.json` |
| 4. Pull HPD owner / manager / violations / complaints | `fetch_hpd.py` | `buildings_hpd.json` |
| 5. Slim + merge HPD into a browser-ready blob | `slim.py` | `buildings.min.json` |
| 6. Nightly listings scrape | `scrape_listings.py` | `listings.json` |

Steps 1–5 produce regenerable intermediates (gitignored); `buildings.min.json`
and `listings.json` are the two files the front end actually fetches.

### HPD data

`fetch_hpd.py` pulls four NYC Open Data datasets and joins them on BBL:

- **Property Registrations** (`tesw-yqqr`) → who registered the building
- **Registration Contacts** (`feu5-w2e2`) → owner / managing agent / head officer name + business address
- **HPD Violations** (`wvxf-dwi5`) → open vs. closed, severity class A/B/C, recency
- **HPD Complaints** (`ygpa-z7cr`) → open vs. closed, recency

Each building's popup shows the operator info, violation/complaint counts, and a
link to that building's full record on HPD Online.

## Front end

`index.html` — a single-file Leaflet map (marker clustering + Street View
thumbnails). No build step; serve the directory statically.

## Sources

- NYC Rent Guidelines Board / DHCR 2024 building files
- Coordinates from NYC PLUTO
- Listings via Zumper / RentHop (nightly Playwright scrape)
- Owner / managing agent / violations / complaints from NYC Open Data (HPD)
