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

## More cities (blocked on records requests — need owner action)

- [ ] **Washington DC** — RentRegistry (rentregistry.dc.gov, live since 6/2025)
  is a Power Apps portal with no bulk export. FOIA/ask DHCD for the housing-
  provider export, or scrape the public portal (brittle). Best data after SF.
- [ ] **Los Angeles (official list)** — replace the assessor-derived
  "likely RSO" set with LAHD's actual RSO inventory via a CA Public Records Act
  request (housing.lacity.gov, ~118k properties). Until then we ship the
  derived set with ZIMAS verification links.
- [ ] **Berkeley** — rentregistry.cityofberkeley.info has per-parcel lookups
  behind a REST API (needs APN enumeration); Rent Board publishes summary
  reports only. Small market — low priority.
- [ ] **NJ (Jersey City / Hoboken / Newark)** — no registries; could ship a
  municipality-level "this address is in a rent-controlled town" layer from the
  NJ DCA rent-control survey spreadsheet.

## Product

- [ ] Developer API: expose /v1 for SF + LA datasets (api_server.py currently
  reads NYC buildings.min.json only).
- [ ] SF/LA SEO: per-neighborhood landing pages (build_seo.py is NYC-only;
  city pages are in sitemap-main.xml for now).
- [ ] LA neighborhoods: assign nb from LA Times neighborhood polygons so the
  Neighborhood filter works in LA (currently empty there).
- [ ] Refresh cadence: cron build_sf.py (DataSF refreshes daily) and
  build_la.py (assessor layer refreshes monthly) + scp to droplet.
