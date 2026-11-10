#!/usr/bin/env python3
"""One line per ship: the result, the build, how long each stage took, how
long it waited for memory, and each stage's real memory peak.

ship.sh writes an events file as it goes (scripts/ship_log.sh): one
tab-separated line per stage start, memory wait, memory sample and note.
This turns it into

    SHIP SUMMARY ok build=180 tier=fast catalog=droplet total=24:10 ram-wait=0:00 peak=12.4GB | checks 0:06 | ...

at the end of the log (grep "SHIP SUMMARY" build/daily-ship.log) and appends
the same facts as JSON to build/ship-history.jsonl, so the next look at
where the time goes is one grep, and the memory guard's 4 and 6 GB
reservations (guesses, 2026-11-01) can be set from what stages really used.

    ship_summary.py EVENTS --result RC [--history build/ship-history.jsonl] [--now EPOCH]

Never fails a ship: any trouble prints a short note and exits 0.
"""
import argparse
import json
import sys
import time


def clock(seconds):
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def read(path):
    events = []
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            try:
                events.append((int(parts[0]), parts[1], parts[2:]))
            except ValueError:
                continue
    return sorted(events, key=lambda e: e[0])


def summarise(events, result, now):
    """-> dict: result, notes, total, ram_wait, peak_gb, swap_mb, stages[]."""
    notes, stages, mem, waits = {}, [], [], []
    start = events[0][0] if events else now
    for at, kind, rest in events:
        if kind == "stage":
            stages.append({"name": rest[0], "at": at})
        elif kind == "note" and "=" in rest[0]:
            key, value = rest[0].split("=", 1)
            notes[key] = value
        elif kind == "ramwait":
            try:
                waits.append((at, int(rest[0])))
            except ValueError:
                pass
        elif kind == "mem":
            try:
                mem.append((at, float(rest[0]), float(rest[1]) if len(rest) > 1 else 0.0))
            except ValueError:
                pass
    for i, st in enumerate(stages):
        end = stages[i + 1]["at"] if i + 1 < len(stages) else now
        st["seconds"] = max(0, end - st["at"])
        # A wait is logged when it ends, inside the stage that asked for it.
        st["ram_wait"] = sum(w for at, w in waits if st["at"] <= at <= end and (at < end or i + 1 == len(stages)))
        inside = [(at, gb) for at, gb, _ in mem if st["at"] <= at < end]
        before = [gb for at, gb, _ in mem if at < st["at"]]
        if inside:
            # What the stage itself added: its peak over what was in use when
            # its work began (after any memory wait), which is the number the
            # guard's reservation should match.
            work_from = st["at"] + st["ram_wait"]
            base = next((gb for at, gb in inside if at >= work_from), before[-1] if before else inside[0][1])
            st["peak_gb"] = round(max(gb for _, gb in inside), 1)
            st["rise_gb"] = round(max(0.0, st["peak_gb"] - base), 1)
    return {
        "result": "ok" if result == 0 else f"FAILED({result})",
        "notes": notes,
        "started": start,
        "total": max(0, now - start),
        "ram_wait": sum(w for _, w in waits),
        "peak_gb": round(max((gb for _, gb, _ in mem), default=0.0), 1),
        "swap_mb": round(max((sw for _, _, sw in mem), default=0.0)),
        "stages": [{k: v for k, v in st.items() if k != "at"} for st in stages],
    }


def line(s):
    head = ["SHIP SUMMARY", s["result"]]
    for key in ("build", "tier", "catalog"):
        if key in s["notes"]:
            head.append(f"{key}={s['notes'][key]}")
    head += [f"total={clock(s['total'])}", f"ram-wait={clock(s['ram_wait'])}"]
    if s["peak_gb"]:
        head.append(f"peak={s['peak_gb']}GB")
        head.append(f"swap={s['swap_mb']}MB")
    parts = [" ".join(head)]
    for st in s["stages"]:
        extra = []
        if st.get("ram_wait"):
            extra.append(f"{clock(st['ram_wait'])} waiting for memory")
        if "rise_gb" in st and st["seconds"] >= 20:
            extra.append(f"+{st['rise_gb']}GB to {st['peak_gb']}")
        parts.append(f"{st['name']} {clock(st['seconds'])}" + (f" ({', '.join(extra)})" if extra else ""))
    return " | ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--result", type=int, default=0)
    ap.add_argument("--history")
    ap.add_argument("--now", type=int)
    args = ap.parse_args(argv)
    try:
        s = summarise(read(args.events), args.result, args.now or int(time.time()))
        print(line(s))
        if args.history:
            with open(args.history, "a") as f:
                f.write(json.dumps(s, sort_keys=True) + "\n")
    except Exception as e:  # noqa: BLE001 (a summary must never fail a ship)
        print(f"SHIP SUMMARY unavailable: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
