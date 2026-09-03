# LinkNYC kiosk codes

One QR per kiosk so the dashboard's "Counter signage" card counts each screen
separately. Each encodes `https://findacrib.com/c/<code>`; nginx already
302s `/c/[ab]<n>` to `/?src=qr-<code>` and logs it to findacrib-qr.log, so no
server change was needed. Regenerate with segno (error correction H, 4-module
quiet zone) -- never edit the PNGs.

| code | kiosk |
|---|---|
| a11 | 75 8th Ave @ W 14th St, Manhattan |
| a12 | 182 Bedford Ave @ N 7th St, Brooklyn |
| a13 | 248 Duffield St @ Fulton St, Brooklyn |
| a14 | 74-04 Roosevelt Ave @ 74th St, Elmhurst, Queens |
| a15 | 2493 Valentine Ave @ E Fordham Rd, Bronx |
| a16 | 201 E 60th St @ 3rd Ave, Manhattan |
| a21 | MTA subway Liveboards (programmatic, via a DSP) — `subway-a21.png`; vanity path findacrib.com/rent 302s to /c/a21 |

Chosen 2026-09-03 by the 10-criteria score (DOT counts, MTA ridership,
stabilized-unit density, tract mover rate, entrances, weekend share).
