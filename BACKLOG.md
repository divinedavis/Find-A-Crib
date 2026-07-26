# Find A Crib — Backlog

## Marketing

- [ ] **Ad campaigns for the new cities (SF + LA)** *(added 2026-07-19, owner request)*
  - Google Ads: the dedicated Find A Crib account (number in owner's notes).
    Create Search campaigns targeting SF + LA renters once the city pages are
    live and indexed:
    - SF: "rent controlled apartments san francisco", "sf rent board lookup",
      "is my apartment rent controlled sf" → https://findacrib.com/sf/
    - LA: "rent stabilized apartments los angeles", "rso apartment list",
      "is my building rent controlled la" → https://findacrib.com/la/
  - Reuse the NYC campaign structure/conversion tags (AW-1001356637). Needs
    owner sign-off on daily budget before enabling.
  - Consider a matching AdSense in-feed slot once the pending AdSense review
    clears (client `ca-pub-8077227518694725`).

## More cities

Scope rule (owner, 2026-07-26): **only ship cities with property-level data.**
A nationwide survey found local rent stabilization in NY, NJ, CA, DC, MD, MN and
ME (plus statewide *caps* with no covered-unit list at all in CA/OR/WA — those
are a rules calculator, not a map layer). Of all of them only a handful publish
anything at the property level; the rest are municipality-level or nothing.

- [x] **Washington DC** — DONE 2026-07-26. RentRegistry turned out to publish
  nightly bulk CSVs after all: the `/data-exports` page calls an unauthenticated
  `…azurewebsites.net/api/ListExports`, which returns blob URLs for
  `registrations`, `registered_accommodations` and `housing_accommodation_units`
  (~130 MB total). No FOIA and no portal scraping needed. See `build_dc.py`.
  4,316 properties / 78,004 covered units, with median *registered* rents.
- [ ] **Downstate NY ETPA (Westchester 21 / Nassau 16 / Rockland 2 + Kingston)**
  — same DHCR registration universe as NYC and the same parser, but published
  only through `apps.hcr.ny.gov/BuildingSearch` (address lookup, no export, and
  it refused connections from here on 7/26). FOIL HCR's Office of Rent
  Administration for the county building files, as with the NYC PDFs.
  Cheapest real win left — ~40 municipalities in the NYC metro.
- [ ] **Montgomery County MD** — rent stabilization since 7/2024 covers licensed
  rentals 23+ years old. dataMontgomery `et5s-xste` (Socrata) has address, unit
  count, year built and lat/lng — 23,464 licensed properties built ≤2003, so a
  derived layer like LA's is a one-day build. Confirm the exemption rules first.
- [ ] **Los Angeles (official list)** — replace the assessor-derived
  "likely RSO" set with LAHD's actual RSO inventory via a CA Public Records Act
  request (housing.lacity.gov, ~118k properties). Until then we ship the
  derived set with ZIMAS verification links.
- [ ] **Berkeley** — rentregistry.cityofberkeley.info has per-parcel lookups
  behind a REST API (needs APN enumeration); Rent Board publishes summary
  reports only. Small market — low priority.
- [ ] **NJ (Jersey City / Hoboken / Newark)** — no registries; could ship a
  municipality-level "this address is in a rent-controlled town" layer from the
  NJ DCA rent-control survey spreadsheet. Out of scope under the property-level
  rule above, but 100+ towns and heavy search intent — revisit as an SEO page.
- Ruled out for now (no property-level data anywhere): Oakland (no registry at
  all), San Jose + Berkeley (aggregate/ZIP-level publication only), Santa Monica
  (per-address portal), Prince George's County, Takoma Park, Mount Rainier,
  St. Paul, Portland ME.

## Product

- [ ] Developer API: expose /v1 for SF + LA + DC datasets (api_server.py
  currently reads NYC buildings.min.json only).
- [ ] SF/LA/DC SEO: per-neighborhood landing pages (build_seo.py is NYC-only;
  city pages are in sitemap-main.xml for now). DC already carries real
  neighborhood names, so it's the easiest of the three.
- [ ] LA neighborhoods: assign nb from LA Times neighborhood polygons so the
  Neighborhood filter works in LA (currently empty there).
- [ ] Refresh cadence: cron build_sf.py (DataSF refreshes daily), build_dc.py
  (RentRegistry exports nightly) and build_la.py (assessor layer refreshes
  monthly) + scp to droplet.
- [ ] Non-NYC detail sheets still show the NYC-only violation/construction stat
  tiles as "—" (pre-existing on SF/LA too). Hide them when `!IS_NYC`.
