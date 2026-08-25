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
  seo-status  re-read the SEO corpus after growth_run.sh's watchdog repaired it,
              and correct the build record it was too early to describe

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
    if not args.dry_run:
        # Record how stale the separately-built SEO corpus is as its own field,
        # not only inside a technique's detail string. It is the biggest single
        # blocker when it goes stale — the 47k pages Google actually crawls stop
        # being rewritten, so every build_seo.py change sits in git — and both
        # readers of this file need it first-class: the report, to put one
        # actionable line on the owner's phone, and the cloud review agent,
        # which cannot see the docroot at all and had been reverse-engineering
        # the date out of a sentence in t_crawl_paths' detail.
        age = techniques._seo_corpus_age(args.docroot)
        # …and what that pipeline says about itself. The age above is an mtime:
        # it dates the freeze but never explains it, and a cron that never
        # fired, a crashed build_seo.py and a failed rsync are three different
        # owner actions behind one identical number. refresh_seo.sh writes a
        # status record into the docroot; this build is the only thing that can
        # carry it out to the cloud review, because it is the only one that
        # commits. None until the droplet picks up the 2026-08-12 script.
        ledger.write_last_run("build", {
            "new_urls": len(ctx.new_urls), "changed_urls": len(ctx.changed_urls),
            "techniques": {r["slug"]: {"ok": bool(r.get("ok")), "detail": r.get("detail", "")}
                           for r in run_log},
            "seo_corpus": {"written": age[0], "days_old": age[1]} if age else None,
            "seo_pipeline": techniques._seo_pipeline_status(args.docroot),
            "deployed": bool(args.deploy)})
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
        from growth import searchconsole
        gsc = searchconsole.collect(days=7)
        log(f"  search console: {gsc['page_clicks']} clicks, {gsc['page_impressions']} impressions "
            f"(page dimension; query dimension sees {gsc['clicks']}/{gsc['impressions']}), "
            f"{gsc['serving_pages']} pages serving, {gsc['tracked_ranking']}/{len(keywords.load())} "
            f"tracked queries ranking, share {gsc['share_pct']}%")
    except Exception as e:
        log(f"  search console unavailable: {e}")
    # Measured index coverage. gsc_serving_pages counts pages that earned an
    # impression, which needs the page to be indexed AND someone to have
    # searched for it; on 47k address pages the second half is the binding
    # constraint, so that number has never actually said whether the corpus is
    # indexed. This asks Google directly, for a stable stratified sample.
    if os.environ.get("GROWTH_INDEX_STATUS", "1") != "0":
        try:
            from growth import indexstatus
            ix = indexstatus.collect(args.docroot)
            if ix.get("ok"):
                log(f"  index status: {ix['inspected']} inspected, "
                    f"{ix['read']}/{ix['cohort']} cohort read, "
                    f"{ix['indexed_pct']}% indexed")
            else:
                log(f"  index status unavailable: {ix.get('detail')}")
        except Exception as e:
            log(f"  index status failed: {type(e).__name__}: {e}")
    try:
        _, changed = keywords.check_coverage(args.docroot)
        s = keywords.summary()
        log(f"  keywords: {s['covered']}/{s['total']} covered ({s['coverage_pct']}%), "
            f"{changed} changed")
        ledger.write_last_run("measure", {
            "days": args.days, "keywords_covered": s["covered"],
            "keywords_total": s["total"], "coverage_pct": s["coverage_pct"],
            "latest_measured_day": max(data) if data else None})
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
    # Built once: the console gets the text part, the email gets both parts.
    built = report.build(run_log=run_log, review_out=review_out)
    text = built[2]
    print(text)
    if args.email and not args.dry_run:
        try:
            report.email(args.email, prebuilt=built)
            log(f"\n  emailed to {args.email}")
        except Exception as e:
            log(f"\n  email failed: {e}")
    return text


def cmd_journal(args):
    """Append a decision-journal entry (see growth/journal.py)."""
    from growth import journal
    if not args.title:
        print(journal.read(last=args.days or 1) or "(journal is empty)")
        return
    entry = journal.append(title=args.title, observed=args.observed or "",
                           concluded=args.concluded or "", changed=args.changed or "",
                           watching=args.watching or "", author=args.author or "daily-review")
    print(entry)


HEARTBEAT_PATH = os.path.join(DEFAULT_BUILD, "growth", "cron_heartbeat.jsonl")


def cron_liveness(path=HEARTBEAT_PATH, now=None):
    """Has the droplet's cron actually been running?

    growth_run.sh appends a start and a finish record per invocation and commits
    the file, so this is the one question a review running on a bare checkout can
    answer directly instead of inferring from silence. Returns (summary, rows).
    """
    import datetime
    try:
        with open(path) as f:
            rows = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return ("no heartbeat file — growth_run.sh has not run since it was added "
                "on 2026-08-10, or an older copy is deployed on the droplet"), []
    except json.JSONDecodeError as e:
        return f"heartbeat file is corrupt ({e})", []
    if not rows:
        return "heartbeat file is empty", []
    last = rows[-1]
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        at = datetime.datetime.fromisoformat(last["at"].replace("Z", "+00:00"))
        hours = (now - at).total_seconds() / 3600.0
        age = f"{hours:.1f}h ago"
    except Exception:
        hours, age = None, "unparseable timestamp"
    # A run that started and never finished is a crash mid-flight; a finish with
    # rc != 0 is a run that reported its own failure. Both beat silence.
    if last.get("phase") == "bootstrap":
        state = "no droplet run recorded yet — only the file's bootstrap record"
    elif last.get("phase") == "start":
        state = f"STARTED BUT NEVER FINISHED ({last.get('job')}) — the run died mid-flight"
    elif last.get("rc") not in (0, None):
        state = f"last run FAILED rc={last.get('rc')} ({last.get('job')}): {last.get('note') or 'no output captured'}"
    else:
        state = f"last run ok ({last.get('job')})"
    # Worth saying out loud even on a green run: it means the operator's push and
    # the droplet's own ledger write collided, which used to wedge the checkout.
    if last.get("pull") == "recovered":
        state += " — but the pull hit a conflict and was reset to origin/main"
    if hours is not None and hours > 26:
        state = f"NO RUN FOR {hours / 24:.1f} DAYS — cron, the host or the checkout. " + state
    return f"{state}; last record {age}", rows


def cmd_seo_status(args):
    """Re-read the SEO corpus after the watchdog has run, and correct last_run.json.

    Ordering bug this exists to fix, observed 2026-08-20. growth_run.sh does
    three things in this order: run `build --deploy` (which writes
    last_run.json's build record, including seo_corpus and seo_pipeline read
    from the docroot), then run the SEO watchdog (which re-runs
    scripts/refresh_seo.sh and REWRITES that corpus), then commit and push. The
    watchdog only fires when the corpus is stale — so on every morning it
    succeeds, the record that gets committed is the pre-fix snapshot saying the
    corpus is frozen. On 2026-08-20 the heartbeat carried seo_watchdog_finish
    rc=0 "ran refresh_seo.sh to completion" at 05:41:24 while the committed
    last_run.json said "NO RUN FOR 2.0 DAYS — cron, the host or the checkout",
    and `status` printed that as its headline. The one file the cloud review is
    told to trust as ground truth was structurally guaranteed to report failure
    on the mornings the repair worked.

    So: after the watchdog, re-read the docroot and patch those two fields in
    place, and record what the watchdog itself did as `seo_watchdog` — rc, note
    and time — so the outcome is first-class in last_run.json instead of only
    in the heartbeat, which the report cannot read and no reviewer opens first.

    --watchdog-rc/-note are the values growth_run.sh already computed for the
    heartbeat. `ran` is always set explicitly, on every path, for the reason
    2026-07-28 taught: a job whose record omits `ok` gets announced as a
    failure it never had.
    """
    age = techniques._seo_corpus_age(args.docroot)
    pipe = techniques._seo_pipeline_status(args.docroot)
    rc = args.watchdog_rc
    # Correct these two only upward in confidence: a re-read that comes back
    # empty (unreadable docroot, a deleted status file) must leave the build's
    # own reading standing rather than blank it. Both readers treat a MISSING
    # seo_corpus as "nothing known" and fall silent, so clobbering a real
    # "frozen since 08-18" with null would suppress the very alarm this command
    # exists to keep honest. Keeping the older value can only under-report
    # freshness, never claim a frozen corpus is fresh, and that is the side to
    # err on.
    rec = {"seo_watchdog": {
            "ran": True,
            "ok": rc == 0,
            "rc": rc,
            # Same truncation rule as the heartbeat note: this is committed to
            # a public repo and the tail of a build log is not reviewed here.
            "note": (args.watchdog_note or "")[:300],
            "at": ledger.now_iso(),
        },
    }
    if age:
        rec["seo_corpus"] = {"written": age[0], "days_old": age[1]}
    if pipe:
        rec["seo_pipeline"] = pipe
    if args.dry_run:
        log(f"  (dry run) would patch build: {json.dumps(rec, sort_keys=True)}")
        return rec
    ledger.patch_last_run("build", rec)
    log(f"  corpus now {age[0] if age else 'UNREADABLE — left the build reading in place'} "
        f"({age[1] if age else '?'}d old); watchdog rc={rc}")
    return rec


def cmd_status(args):
    summary, rows = cron_liveness()
    log(f"cron: {summary}")
    for r in rows[-6:]:
        log(f"    {r.get('at')} {str(r.get('job'))[:18].ljust(18)} {str(r.get('phase')).ljust(9)}"
            f" rc={r.get('rc')} pull={r.get('pull')} {(r.get('note') or '')[:60]}")
    # The second cron, and the one that publishes 47,599 of ~47,600 pages. It
    # runs from a different checkout and cannot commit, so the only copy that
    # reaches a bare cloud checkout is the one the build folded into
    # last_run.json — read it from there, not from the docroot.
    build = ledger.read_last_run().get("build") or {}
    corpus, pipe = build.get("seo_corpus") or {}, build.get("seo_pipeline")
    if pipe:
        log(f"seo pipeline: {pipe.get('state')}; last record {pipe.get('hours_ago', '?')}h ago"
            f" ({pipe.get('corpus_pages', '?')} pages built, "
            f"{pipe.get('changed_urls', '?')} changed, head {pipe.get('head', '?')}, "
            f"pull {pipe.get('pull', '?')}, code {pipe.get('code', '?')})")
    elif corpus:
        log(f"seo pipeline: no status record — the droplet's refresh_seo.sh predates "
            f"2026-08-12. Corpus mtime says {corpus.get('written')} "
            f"({corpus.get('days_old')}d ago); that is all we know.")
    # Whether the watchdog had to step in, and what happened when it did. Both
    # fields above are re-read after it runs (see cmd_seo_status), so from
    # 2026-08-20 they describe the corpus AFTER any repair rather than the
    # snapshot the build happened to take a minute too early.
    wd = build.get("seo_watchdog")
    if isinstance(wd, dict) and wd.get("ran"):
        log(f"seo watchdog: ran at {wd.get('at')}, rc={wd.get('rc')} "
            f"({'ok' if wd.get('ok') else 'FAILED'}) — {wd.get('note') or 'no note'}")
    log("")
    techs = ledger.load_techniques()
    for t in techs:
        v = t.get("verdict") or {}
        mark = {"active": "●", "candidate": "○", "retired": "×"}.get(t.get("status"), "?")
        log(f"{mark} {t['id']} {t['name']}  [{t['kind']}/{t['status']}]")
        if v:
            mk = {True: "WORKS", False: "no"}.get(v.get("works"), "UNPROVEN")
            log(f"    verdict: {mk} — {v.get('why')}")
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


def cmd_lifecycle(args):
    """Buyer follow-up sequence. Only runs if the ledger says it's active."""
    if not any(t["slug"] == "lifecycle_email" for t in ledger.active()):
        log("  lifecycle_email is not active in the ledger — skipped")
        return None
    try:
        from growth import lifecycle
    except Exception as e:
        log(f"  lifecycle unavailable: {e}")
        return None
    try:
        by_bbl = {}
        try:
            with open(os.path.join(args.docroot, "buildings.min.json")) as f:
                by_bbl = {str(b["bbl"]): b for b in json.load(f)}
        except Exception:
            pass          # copy still sends; it just falls back to "your building"
        return lifecycle.run(buildings_by_bbl=by_bbl, dry_run=args.dry_run)
    except Exception as e:
        log(f"  lifecycle failed: {e}")
        return None


def cmd_accounts(args):
    """Free-account onboarding sequence. Gated on the ledger, like everything else."""
    if not any(t["slug"] == "account_lifecycle" for t in ledger.active()):
        log("  account_lifecycle is not active in the ledger — skipped")
        return None
    try:
        from growth import accounts
    except Exception as e:
        log(f"  accounts unavailable: {e}")
        return None
    try:
        # The lapsed email cites the live voucher count, so it has to be real.
        n = None
        try:
            with open(os.path.join(args.docroot, "s8.json")) as f:
                n = len((json.load(f).get("avail") or {}))
        except Exception:
            pass
        return accounts.run(dry_run=args.dry_run, voucher_buildings=n)
    except Exception as e:
        log(f"  accounts failed: {e}")
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
    log("== lifecycle ==")
    cmd_lifecycle(args)
    log("== accounts ==")
    cmd_accounts(args)
    log("== report ==")
    last = ledger.get_state("last_build", {})
    cmd_report(args, run_log=last.get("log"), review_out=rv)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["build", "deploy", "measure", "review", "scout",
                                       "outreach", "lifecycle", "accounts", "report", "daily", "status",
                                       "journal", "seo-status"])
    p.add_argument("--build-dir", default=os.environ.get("GROWTH_BUILD_DIR", DEFAULT_BUILD))
    p.add_argument("--docroot", default=os.environ.get("GROWTH_DOCROOT", DEFAULT_DOCROOT))
    p.add_argument("--deploy", action="store_true", help="rsync after build")
    p.add_argument("--dry-run", action="store_true", help="write nothing, send nothing")
    p.add_argument("--days", type=int, default=1, help="days to measure (backfill)")
    p.add_argument("--email", help="email the report here")
    # journal fields
    p.add_argument("--title", help="journal: entry title")
    p.add_argument("--observed", help="journal: what the numbers showed")
    p.add_argument("--concluded", help="journal: what you concluded and why")
    p.add_argument("--changed", help="journal: what you actually changed")
    p.add_argument("--watching", help="journal: what to check next time")
    p.add_argument("--author", help="journal: who wrote it")
    # seo-status: what growth_run.sh's watchdog just did, so last_run.json can
    # say it without anyone parsing the heartbeat.
    p.add_argument("--watchdog-rc", type=int, default=0,
                   help="seo-status: exit code of the watchdog's refresh_seo.sh")
    p.add_argument("--watchdog-note", default="",
                   help="seo-status: the watchdog's one-line outcome")
    args = p.parse_args()

    seed.run()
    {"build": cmd_build, "deploy": cmd_deploy, "measure": cmd_measure,
     "review": cmd_review, "scout": cmd_scout, "outreach": cmd_outreach,
     "lifecycle": cmd_lifecycle, "accounts": cmd_accounts,
     "report": cmd_report, "daily": cmd_daily, "status": cmd_status,
     "journal": cmd_journal, "seo-status": cmd_seo_status}[args.command](args)


if __name__ == "__main__":
    main()
