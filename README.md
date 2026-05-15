# Rent Map — NYC Rent-Stabilized Buildings Explorer

An interactive map of every DHCR rent-stabilized building in **Manhattan** and
**Brooklyn**, with a nightly signal for which buildings were **recently
advertised** for rent on Zumper.

Deployed at `http://104.236.120.144/rent-map/`.

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
| 4. Slim for the browser | `slim.py` | `buildings.min.json` |
| 5. Nightly listings scrape | `scrape_listings.py` | `listings.json` |

Steps 1–4 produce regenerable intermediates (gitignored); `buildings.min.json`
and `listings.json` are the two files the front end actually fetches.

## Front end

`index.html` — a single-file Leaflet map (marker clustering + Street View
thumbnails). No build step; serve the directory statically.

## Sources

- NYC Rent Guidelines Board / DHCR 2024 building files
- Coordinates from NYC PLUTO
- Listings via Zumper / RentHop (nightly Playwright scrape)
