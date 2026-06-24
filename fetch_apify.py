#!/usr/bin/env python3
"""Run the Apify StreetEasy actor/task and dump its dataset to JSON (stdlib only).

Designed for the droplet cron: no third-party deps, so the Playwright venv is
no longer required. Starts a run, polls to completion, fetches dataset items.

Env:
    APIFY_TOKEN   required — Apify API token
    APIFY_TASK    task id (preferred; input is saved in the Apify task), OR
    APIFY_ACTOR   actor id (input must be supplied via APIFY_INPUT)
    APIFY_INPUT   optional path to a JSON file with the actor input (actor mode)
    APIFY_TIMEOUT optional max seconds to wait for the run (default 1800)

Usage:
    APIFY_TOKEN=... APIFY_TASK=... python3 fetch_apify.py apify_export.json
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

API = "https://api.apify.com/v2"
POLL_EVERY = 15  # seconds between run-status checks


def _req(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "apify_export.json"
    token = os.environ.get("APIFY_TOKEN")
    task = os.environ.get("APIFY_TASK")
    actor = os.environ.get("APIFY_ACTOR")
    timeout = int(os.environ.get("APIFY_TIMEOUT", "1800"))
    if not token:
        sys.exit("APIFY_TOKEN is required")
    if not (task or actor):
        sys.exit("set APIFY_TASK or APIFY_ACTOR")

    # raise the run's server-side timeout for big scrapes (the actor's default
    # is often 3600s, too short for a full-borough run). 0/unset = actor default.
    run_timeout = os.environ.get("APIFY_RUN_TIMEOUT", "")
    qs = f"&timeout={run_timeout}" if run_timeout else ""

    # 1) start the run
    if task:
        start = f"{API}/actor-tasks/{task}/runs?token={token}{qs}"
        body = None
    else:
        start = f"{API}/acts/{actor}/runs?token={token}{qs}"
        body = None
        inp = os.environ.get("APIFY_INPUT")
        if inp:
            body = json.loads(open(inp).read())
    run = _req("POST", start, body)["data"]
    run_id, dataset_id = run["id"], run["defaultDatasetId"]
    print(f"started run {run_id}", flush=True)

    # 2) poll until terminal
    deadline = time.time() + timeout
    status = run["status"]
    while status in ("READY", "RUNNING"):
        if time.time() > deadline:
            sys.exit(f"timed out after {timeout}s (run {run_id} still {status})")
        time.sleep(POLL_EVERY)
        status = _req("GET", f"{API}/actor-runs/{run_id}?token={token}")["data"]["status"]
    # SUCCEEDED is ideal, but TIMED-OUT/ABORTED still leave a usable partial
    # dataset we paid for — pull it anyway and just warn. Only a hard FAILED
    # with no data is fatal.
    if status not in ("SUCCEEDED", "TIMED-OUT", "TIMING-OUT", "ABORTED", "ABORTING"):
        sys.exit(f"run {run_id} ended {status}")
    if status != "SUCCEEDED":
        print(f"WARNING: run {run_id} ended {status} — pulling partial dataset", flush=True)

    # 3) pull dataset items
    items = _req("GET", f"{API}/datasets/{dataset_id}/items?clean=true&format=json&token={token}")
    open(out_path, "w").write(json.dumps(items))
    print(f"wrote {len(items)} items -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
