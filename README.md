# Find A Crib

[![ci](https://github.com/divinedavis/Find-A-Crib/actions/workflows/ci.yml/badge.svg)](https://github.com/divinedavis/Find-A-Crib/actions/workflows/ci.yml)
[![journeys](https://github.com/divinedavis/Find-A-Crib/actions/workflows/journeys.yml/badge.svg)](https://github.com/divinedavis/Find-A-Crib/actions/workflows/journeys.yml)
[![App Store](https://img.shields.io/badge/App_Store-Find_A_Crib-0D96F6?logo=apple&logoColor=white)](https://apps.apple.com/us/app/find-a-crib/id6807549249)

**Find the affordable apartments renters can actually get.** Find A Crib maps
every rent-stabilized building in New York City, plus rent-controlled and
income-restricted housing in San Francisco, Los Angeles, Washington DC and
more, and alerts renters the moment a housing lottery or affordable
re-rental opens up.

🔗 **[findacrib.com](https://findacrib.com)** · 📱 **[iPhone & iPad app](https://apps.apple.com/us/app/find-a-crib/id6807549249)**

![Find A Crib: searching the map, opening a building, filtering by borough](docs/demo.gif)

## What it does

- **Map of covered buildings.** Every NYC building on the DHCR rent-stabilization
  rolls, with its HPD owner / managing agent, open violations and complaints.
  SF, LA and DC run on the same front end from each city's own records.
- **Lotteries and re-rentals.** NYC Housing Connect and HCR lotteries, plus
  marketing-agent re-rentals that go first come, first served.
- **Alerts.** Email and iPhone push when a lottery, re-rental or saved
  building matches what you're looking for. Alerts can be filtered by
  borough, household size and income.
- **AI that shows its sources.** A nightly reader turns each listing's flyer
  into a unit table (rent, household size, income limits). Every number it
  extracts must appear in the source text, or that row is dropped
  (`claude_features.ungrounded`).
- **"Do I qualify?"** Checks household size and income against each listing's
  limits.

## How the code is laid out

| Area | Where |
|------|-------|
| Web app (one file, Leaflet, no build step) | `index.html`, `static/` |
| City pages generated from the root page | `build_city_pages.py` → `sf/`, `la/`, `dc/` |
| Data builders (one script per source) | `parse_pdfs.py`, `fetch_hpd.py`, `scrape_hcr.py`, `build_*.py` |
| API (Flask) | `api_server.py`, `ai_gateway.py`, `deploy/api/` |
| Alerts | `lottery_alerts.py`, `saved_alerts.py`, `apns.py` |
| AI features | `flyer_reader.py`, `nl_search.py`, `claude_features.py`, `ai_gateway.py` |
| Database (Supabase / Postgres) | `db/` migrations, `supabase/functions/` |
| iOS app (SwiftUI) | `ios/` (see [ios/README.md](ios/README.md)) |
| Growth engine (SEO pages, outreach) | `growth/`, `growth_daily.py` |
| Deploy + cron jobs | `deploy/`, `scripts/deploy_*.sh` |
| Tests | `tests/` |

More detail:
[data pipeline, alerts and cities](docs/data-pipeline.md) ·
[growth engine](docs/growth-engine.md) ·
[traffic report](docs/traffic-report.md) ·
[backlog](BACKLOG.md)

## Quick start

You need Python 3.14 (what CI runs) and no API keys.

```sh
git clone https://github.com/divinedavis/Find-A-Crib.git
cd Find-A-Crib
python3.14 -m venv .venv && . .venv/bin/activate
pip install requests numpy pillow opencv-python-headless shapely PyJWT segno anthropic playwright==1.62.0
python3 tests/run_unit.py                 # unit tests (same as CI)
```

To see a front-end change, run the user-journey suite. It loads **your local
`index.html`** over the live site's data in phone, desktop and iPad browsers:

```sh
playwright install chromium webkit
JOURNEYS_SKIP=account_delete,plus_gates,renter_tools,ai_features python3 tests/journeys.py
```

Large data files (`buildings.slim.json` and friends) are generated and
gitignored. The journey suite fetches them from findacrib.com, so you don't
need to build them.

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)**. In short, fork the repo, open a pull
request, and keep CI green. Issues labelled
[`good first issue`](https://github.com/divinedavis/Find-A-Crib/labels/good%20first%20issue)
are a good place to start.

Found a security problem? Please don't open an issue. See [SECURITY.md](SECURITY.md).

## Ground rules for the data

- **No listing-portal data.** The Zumper and StreetEasy feeds were removed on
  2026-10-06 (Zumper's Terms forbid scraping). Building cards link out to
  StreetEasy (NYC) or Zillow (other cities) instead. Don't add a portal scrape.
- **Only cities with property-level records get a map.** See `BACKLOG.md` for
  the ones that publish nothing below the town level.
- **No badge never means "no."** Source-of-income discrimination is illegal in
  NYC, so a missing Section 8 badge never means vouchers aren't accepted.

## Sources

- NYC Rent Guidelines Board / DHCR 2024 building files
- Coordinates from NYC PLUTO
- Owner / managing agent / violations / complaints from NYC Open Data (HPD)
- NYC Housing Connect and NY HCR HousingSearch lotteries
- SF Rent Board Housing Inventory via DataSF (`gdc7-dmcn`)
- LA County Assessor parcel rolls, filtered by LAHD's RSO criteria
- DC DHCD RentRegistry public data exports; DC neighborhood label points (DCGIS)
  and Census 2020 ZCTAs for DC neighborhood/ZIP assignment
- HUD Fair Market Rents and project-based Section 8 contracts

