# Running the journeys on a real iPhone

`tests/journeys.py` runs the phone pass in Playwright's WebKit — the same
engine as iOS Safari, without the device. Three things only the device has:

- the software keyboard and the viewport resize when it closes
- the memory limit at which iOS kills a tab ("A problem repeatedly occurred")
- the GPU and its compositing limits

The crash of 2026-09-06 lived exactly there (results sheet with a permanent
compositing layer + keyboard closing after an area pick) and never
reproduced in emulation. So a change that touches the search box, the
results sheet, the map size or anything `position: fixed` also wants a run
on the phone.

## One-time setup (phone + this Mac)

1. iPhone: Settings → Safari → Advanced → **Web Inspector** on, and
   **Remote Automation** on.
2. Mac: `safaridriver --enable` once (asks for the admin password).
3. Plug the phone in over USB and trust the Mac.
4. `~/.venvs/dhcr-map/bin/pip install selenium`

## Run

```
~/.venvs/dhcr-map/bin/python tests/device_journeys.py
```

`device_journeys.py` (to write when the phone is on hand) drives Safari on
the phone through the same paths with real taps and real keyboard: type
"Bronx", tap the borough suggestion, let the keyboard close, tap List,
scroll, tap a pin, open the sheet. It passes when the page's
`localStorage['fac.trace']` never restarts from `boot` mid-run — that is
the page surviving — and fails on any reload it did not ask for.

Until that file exists, the manual equivalent is: do those steps on the
phone, then check the `events` table for a `crash_trace` row from your
visitor id. The page writes one on the reload after any kill.
