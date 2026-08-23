# Council-district outreach

The link problem, stated plainly: findacrib.com has 44 clicks and 589 impressions
across 180 days, and ten distinct queries. Four of those are `jayshomefinder`
variants. Nothing on the site has ever taken an impression for a rent-stabilization
query. On-page work cannot fix that — the domain has no authority, so Google
rations crawl, and 329 of the 445 URLs it has inspected it has never fetched.

Links fix it. `/council-district/` exists to be the thing worth linking to: it is
the only geography on this site that a named person has a standing reason to cite,
and nobody else publishes it.

## The list

`council_outreach.csv`, rebuilt by `build_council.py` on every run. One row per
district: member, office email, borough, the four counts, the district's rank by
open violations, its page URL, and a one-sentence hook already written.

Emails come from council.nyc.gov's own district table. They are public office
addresses and they stay in this CSV — they are deliberately **not** on the
published pages, which are about buildings, not about republishing a scraped
contact table.

## Who to approach first

Rank by open violations and start at the top — the number is most quotable where
it is largest, and a district office is most likely to use a figure that makes a
case it is already making. As of the current build:

| Rank | District | Member | Open violations | Buildings |
|---|---|---|---|---|
| 1 | 15 | Oswald J. Feliz | 65,205 | 1,407 |
| 2 | 14 | Pierina Ana Sanchez | 64,255 | 1,196 |
| 3 | 10 | Carmen De La Rosa | 54,940 | 1,461 |
| 4 | 9 | Yusef Salaam | 54,627 | 1,605 |
| 5 | 40 | Rita C. Joseph | 53,078 | 1,309 |

Second tier, same email, different reader: the housing reporter at a borough
outlet (Bronx Times, Brooklyn Paper, THE CITY, Gothamist). They want the ranked
index page, not one district.

## What to send

Short, one number, no ask beyond the link. Something like:

> Subject: Open HPD violations in Council District 15
>
> Hi — I maintain Find A Crib, which maps every DHCR-registered rent-stabilized
> building in the city. I joined those 47,165 buildings to council districts,
> which as far as I can tell nobody publishes.
>
> District 15 has 65,205 open HPD violations across its 1,407 rent-stabilized
> buildings — 20,484 of them class C, the immediately hazardous grade. That is
> the highest of the 51 districts.
>
> The page is here, and it rebuilds from the city's open data:
> https://findacrib.com/council-district/15/
>
> Free to use, no attribution needed — though a link helps me.

## Rules

- **One number per email.** The hook column is the number for that district.
- **Never send a figure you have not just checked against the live page.** The
  counts move on every HPD refresh, and a stale number in a cold email to an
  elected office is the whole credibility of the pitch.
- **Do not send in bulk from the droplet.** These are individually addressed.

## Status

Not sent. The pages are live and the list is built; sending is a separate
decision and has not been made.
