#!/usr/bin/env python3
"""Find A Crib growth engine — daily driver.

Two crons run this on the web droplet:

  05:40 UTC  growth_daily.py build --deploy      (after the 04:15 voucher scrape)
  06:00 ET   growth_daily.py daily --email …     (measure, review, scout, report)

Commands:
  build     run every active technique, write pages into growth_out/
  deploy    rsync growth_out/ into the docroot
  measure   pull yesterday's traffic/funnel/revenue numbers into the ledger
  review    judge active techniques; retire the dead and the redundant
  scout     research and propose new techniques (needs an LLM key)
  report    print / email the daily growth report
  daily     measure → review → scout → report
  status    print the ledger and the scoreboard

Nothing here touches the live docroot except `deploy`, and `--dry-run` makes
every command read-only, so it is safe to run by hand on the server.
"""
import argparse
import json
import os
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from growth import ledger, keywords, metrics, report, review, seed, techniques  # noqa: E402

DEFAULT_BUILD = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DOCROOT = "/var/www/rent-map"


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------- build

def cmd_build(args):
    seed.run()
    keywords.seed()
    ctx = techniques.Context(args.build_dir, args.docroot, dry_run=args.dry_run, log=log)

    active = {t["slug"] for t in ledger.active()}
    run_log = []
    for slug in techniques.ORDER:
        if slug not in active:
            log(f"  skip {slug} (not active in the ledger)")
            continue
        fn = techniques.REGISTRY.get(slug)
        if not fn:
            log(f"  skip {slug} (no implementation)")
            continue
        try:
            res = fn(ctx)
        except Exception as e:
            traceback.print_exc()
            res = {"ok": False, "detail": f"crashed: {e}"}
        res["slug"] = slug
        run_log.append(res)
        log(f"  [{'ok ' if res.get('ok') else 'FAIL'}] {slug}: {res.get('detail', '')}")

    ledger.set_state("last_build", {"date": ledger.today(), "log": run_log,
                                    "new": len(ctx.new_urls), "changed": len(ctx.changed_urls)})
    log(f"  {len(ctx.new_urls)} new URLs, {len(ctx.changed_urls)} changed")

    if args.deploy and not args.dry_run:
        cmd_deploy(args)
    return run_log


def cmd_deploy(args):
    out = os.path.join(args.build_dir, "growth_out")
    if not os.path.isdir(out):
        log("  nothing to deploy")
        return
    # No --delete: the docroot also holds the app, the data blobs and the
    # monthly SEO build. We only ever add or overwrite our own files.
    r = subprocess.run(["rsync", "-a", out + "/", args.docroot + "/"],
                       capture_output=True, text=True)
    if r.returncode:
        log(f"  deploy FAILED: {r.stderr.strip()}")
    else:
        log(f"  deployed {out} -> {args.docroot}")


# ----------------------------------------------------------------- measure

def cmd_measure(args):
    try:
        data, totals = metrics.collect_and_record(days=args.days)
    except Exception as e:
        log(f"  measure failed: {e}")
        return None
    for d, m in sorted(data.items()):
        log(f"  {d}: {m['visitors']} visitors, {m['organic_visitors']} organic, "
            f"{m['ai_visitors']} AI")
    log(f"  totals: {totals}")
    try:
        _, changed = keywords.check_coverage(args.docroot)
        s = keywords.summary()
        log(f"  keywords: {s['covered']}/{s['total']} covered ({s['coverage_pct']}%), "
            f"{changed} changed")
    except Exception as e:
        log(f"  keyword coverage failed: {e}")
    return data


# ------------------------------------------------------------------ review

def cmd_review(args):
    out = review.run(apply=not args.dry_run)
    for r in out["evaluated"]:
        if r["action"] != "skip":
            log(f"  {r['id']} {r['slug']}: {r['action']} — {r['why']}")
    for a in out["actions"]:
        log(f"  {a}")
    if not out["actions"]:
        log("  no changes")
    return out


# ------------------------------------------------------------------- scout

def cmd_scout(args):
    try:
        from growth import scout
    except Exception as e:
        log(f"  scout unavailable: {e}")
        return None
    try:
        return scout.run(dry_run=args.dry_run, docroot=args.docroot)
    except Exception as e:
        log(f"  scout failed: {e}")
        return None


# ------------------------------------------------------------------ report

def cmd_report(args, run_log=None, review_out=None):
    text = report.build_text(run_log=run_log, review_out=review_out)
    print(text)
    if args.email and not args.dry_run:
        try:
            report.email(text, args.email)
            log(f"\n  emailed to {args.email}")
        except Exception as e:
            log(f"\n  email failed: {e}")
    return text


def cmd_status(args):
    techs = ledger.load_techniques()
    for t in techs:
        v = t.get("verdict") or {}
        mark = {"active": "●", "candidate": "○", "retired": "×"}.get(t.get("status"), "?")
        log(f"{mark} {t['id']} {t['name']}  [{t['kind']}/{t['status']}]")
        if v:
            log(f"    verdict: {'WORKS' if v.get('works') else 'no'} — {v.get('why')}")
    log("")
    log(json.dumps(keywords.summary(), indent=2))


def cmd_outreach(args):
    """Research prospects and draft outreach. Never sends — see growth/outreach.py."""
    if not any(t["slug"] == "b2b_outreach" for t in ledger.active()):
        log("  b2b_outreach is not active in the ledger — skipped")
        return None
    try:
        from growth import outreach
    except Exception as e:
        log(f"  outreach unavailable: {e}")
        return None
    try:
        return outreach.run(dry_run=args.dry_run)
    except Exception as e:
        log(f"  outreach failed: {e}")
        return None


def cmd_daily(args):
    log("== measure ==")
    cmd_measure(args)
    log("== review ==")
    rv = cmd_review(args)
    log("== scout ==")
    cmd_scout(args)
    log("== outreach ==")
    cmd_outreach(args)
    log("== report ==")
    last = ledger.get_state("last_build", {})
    cmd_report(args, run_log=last.get("log"), review_out=rv)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["build", "deploy", "measure", "review", "scout",
                                       "outreach", "report", "daily", "status"])
    p.add_argument("--build-dir", default=os.environ.get("GROWTH_BUILD_DIR", DEFAULT_BUILD))
    p.add_argument("--docroot", default=os.environ.get("GROWTH_DOCROOT", DEFAULT_DOCROOT))
    p.add_argument("--deploy", action="store_true", help="rsync after build")
    p.add_argument("--dry-run", action="store_true", help="write nothing, send nothing")
    p.add_argument("--days", type=int, default=1, help="days to measure (backfill)")
    p.add_argument("--email", help="email the report here")
    args = p.parse_args()

    seed.run()
    {"build": cmd_build, "deploy": cmd_deploy, "measure": cmd_measure,
     "review": cmd_review, "scout": cmd_scout, "outreach": cmd_outreach,
     "report": cmd_report, "daily": cmd_daily, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    main()
