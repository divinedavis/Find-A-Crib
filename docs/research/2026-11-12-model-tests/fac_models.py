#!/usr/bin/env python3
"""Which model should read Find A Crib's flyers and write Help me apply?
(owner, 2026-11-12: "why not use open weight model?", "will inkling 2 small
work? lets do a test").

Three tasks on the same live flyers (PDF links in findacrib.com/featured.json
that have a text layer), every model through Vercel AI Gateway with the
production prompt (flyer_reader.SYSTEM / claude_features.APPLY_SYSTEM). The
schema is put in the prompt as JSON for every model alike; production Haiku
uses strict structured outputs on top.

  flyer   the flyer's text -> unit table. Answer key: Claude Opus 5.5 on the
          same text. Scored as unit rows matched exactly (beds, rent,
          household sizes, income min/max), before and after production's
          grounding filter (claude_features.ungrounded: a row with a number
          not in the source is dropped), plus deadline and first-come.
  scan    the same flyer as page IMAGES only (pdftoppm, first 3 pages), as if
          it were scanned. Same answer key. Today a scanned flyer goes to
          Haiku as a PDF and is marked unverified.
  apply   Help me apply from the listing + flyer text, after production's
          grounding filter; Claude Opus 5.5 grades every model's answer for a
          listing in one blind call (shuffled letters), 1-10.

    TEST_BUDGET_USD=6 ~/.venvs/dhcr-map/bin/python research/2026-11-12-model-tests/fac_models.py [--n 14]

Writes report.md here (committed) and results.json (not committed: it holds
the flyers' text and agents' contact details).
"""
import argparse
import json
import random
import statistics
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                      # docs/research/<run>/ -> repo root (moved 2026-11-13)
sys.path.insert(0, str(ROOT / "pipeline"))  # claude_features, flyer_reader
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import gw  # noqa: E402
import claude_features as cf  # noqa: E402
import flyer_reader as fr  # noqa: E402

REF = "anthropic/claude-opus-5.5"
TEXT_MODELS = ["anthropic/claude-haiku-4.5", "anthropic/claude-haiku-5.5", "thinkingmachines/inkling-2-small",
               "moonshotai/kimi-k3.1-pro", "deepseek/deepseek-v4.1-flash", "zai/glm-5.3-flash",
               "alibaba/qwen3.8-flash", "openai/gpt-oss-120b"]
VISION_MODELS = ["anthropic/claude-haiku-4.5", "anthropic/claude-haiku-5.5", "thinkingmachines/inkling-2-small",
                 "moonshotai/kimi-k3.1-pro", "deepseek/deepseek-v4.1-flash", "zai/glm-5.3-flash",
                 "mistral/mistral-small", "minimax/minimax-m3.1-flash", "google/gemini-3-flash"]
OPEN = {"thinkingmachines/inkling-2-small", "moonshotai/kimi-k3.1-pro", "deepseek/deepseek-v4.1-flash",
        "zai/glm-5.3-flash", "alibaba/qwen3.8-flash", "openai/gpt-oss-120b", "mistral/mistral-small",
        "minimax/minimax-m3.1-flash"}
FLYER_SYS = fr.SYSTEM + "\n\nReply with ONE JSON object matching this JSON Schema, nothing else:\n" + json.dumps(fr.SCHEMA)
APPLY_SYS = cf.APPLY_SYSTEM + "\n\nReply with ONE JSON object matching this JSON Schema, nothing else:\n" + json.dumps(cf.APPLY_SCHEMA)


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; FindACrib/1.0)"}), timeout=30) as r:
        return r.read()


def pages_png(pdf, n=3):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "f.pdf").write_bytes(pdf)
        subprocess.run(["pdftoppm", "-r", "100", "-png", "-l", str(n), str(Path(d) / "f.pdf"), str(Path(d) / "p")],
                       check=True, capture_output=True, timeout=60)
        return [p.read_bytes() for p in sorted(Path(d).glob("p*.png"))]


def load(n):
    feed = json.loads(get("https://findacrib.com/featured.json"))["listings"]
    pdfs = [l for l in feed if l["href"].lower().split("?")[0].endswith(".pdf") or l.get("href_kind") == "flyer"]
    random.Random(1112).shuffle(pdfs)
    out = []
    for l in pdfs:
        try:
            text, pdf = fr.pdf_source(l["href"])
        except Exception:  # noqa: BLE001
            continue
        if len(text) < 200:
            continue
        meta = {k: l.get(k) for k in ("agent", "title", "address", "borough", "beds", "money_kind", "money_low", "money_high")}
        meta["address"] = l.get("address_src") or l.get("address")
        out.append({"href": l["href"], "meta": meta, "text": text, "pngs": pages_png(pdf),
                    "apply_listing": {k: l.get(k) for k in cf.APPLY_KEEP}})
        if len(out) >= n:
            break
    return out


def flyer_msg(f, scan):
    head = f"<listing>\n{json.dumps(f['meta'], sort_keys=True)}\n</listing>\n"
    if not scan:
        return [{"role": "user", "content": head + f"<source>\n{f['text']}\n</source>"}]
    return [{"role": "user", "content": [gw.image_part(p, "image/png") for p in f["pngs"]] +
             [{"type": "text", "text": head + "Read the attached flyer (page images)."}]}]


def rows(out):
    keys = ("beds", "rent", "household_size_min", "household_size_max", "income_min", "income_max")
    return Counter(tuple((u or {}).get(k) for k in keys) for u in (out or {}).get("units") or [] if isinstance(u, dict))


def f1(got, ref):
    if not ref and not got:
        return 1.0
    tp = sum((got & ref).values())
    p = tp / max(1, sum(got.values()))
    r = tp / max(1, sum(ref.values()))
    return 0.0 if tp == 0 else 2 * p * r / (p + r)


def grounded(out, f):
    nums = fr.source_numbers(f["meta"], f["text"])
    keep = [u for u in out.get("units") or [] if isinstance(u, dict) and not any(
        cf.ungrounded(str(v), nums) for k, v in u.items()
        if isinstance(v, int) and k not in ("beds", "household_size_min", "household_size_max"))]
    return {**out, "units": keep}


def norm(s):
    return " ".join(str(s or "").lower().replace(",", " ").split())


def apply_filter(out, f):
    src = {"listing": f["apply_listing"], "page": f["text"]}
    nums = cf.record_numbers(src)
    out = dict(out)
    out["steps"] = [x for x in out.get("steps") or [] if isinstance(x, str) and not cf.ungrounded(x, nums)]
    out["documents"] = [d for d in out.get("documents") or [] if isinstance(d, dict) and not cf.ungrounded(d.get("item", ""), nums)]
    if out.get("deadline") and cf.ungrounded(out["deadline"], nums):
        out["deadline"] = None
    refused = bool(cf.ungrounded(out.get("email_body") or "", nums))
    return out, refused


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=14)
    a = ap.parse_args()
    flyers = load(a.n)
    print(f"{len(flyers)} flyers with text", flush=True)
    jobs = [("ref", REF, i, False) for i in range(len(flyers))]
    jobs += [("flyer", m, i, False) for m in TEXT_MODELS for i in range(len(flyers))]
    jobs += [("scan", m, i, True) for m in VISION_MODELS for i in range(len(flyers))]
    jobs += [("apply", m, i, False) for m in TEXT_MODELS for i in range(len(flyers))]

    def run(job):
        task, model, i, scan = job
        f = flyers[i]
        try:
            if task == "apply":
                msg = [{"role": "user", "content": f"<listing>\n{json.dumps(f['apply_listing'], sort_keys=True)}\n</listing>\n"
                        f"<page>\n{f['text']}\n</page>"}]
                r = gw.chat(model, msg, system=APPLY_SYS, max_tokens=8000)
            else:
                r = gw.chat(model, flyer_msg(f, scan), system=FLYER_SYS, max_tokens=12000)
        except gw.OverBudget as e:
            r = {"ok": False, "error": str(e), "cost": 0}
        r["json"] = gw.parse_json(r.get("text")) if r.get("ok") else None
        return {"task": task, "model": model, "i": i, **{k: r.get(k) for k in ("ok", "error", "cost", "ms", "json", "out")}}

    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(run, jobs))
    ref = {r["i"]: r["json"] for r in res if r["task"] == "ref" and r["json"]}

    # Blind grading of Help me apply: one Opus call per listing, letters shuffled.
    grades = {}
    for i, f in enumerate(flyers):
        outs = [(r["model"], *apply_filter(r["json"], f)) for r in res if r["task"] == "apply" and r["i"] == i and r["json"]]
        if not outs:
            continue
        random.Random(i).shuffle(outs)
        letters = "ABCDEFGHIJ"
        body = "\n\n".join(f"### Answer {letters[k]}\n{json.dumps(o, ensure_ascii=False)}" + ("\n(The app would refuse this one: its email quotes a number that is not in the listing.)" if refused else "")
                           for k, (_, o, refused) in enumerate(outs))
        prompt = (f"A renter in New York asked Find A Crib how to apply for this apartment.\n\n<listing>\n{json.dumps(f['apply_listing'])}\n</listing>\n"
                  f"<page>\n{f['text'][:12000]}\n</page>\n\nEach answer below is a list of steps, documents, deadline, contact and a draft email "
                  "to the marketing agent. Grade each 1-10: 10 = every fact matches the page, the steps are the page's real process, "
                  "nothing invented, contact details right, the email is ready to send. Heavily penalise invented or wrong rents, "
                  "incomes, dates or contacts; an answer the app would refuse scores at most 2.\n\n" + body +
                  "\n\nReply with JSON only: {\"A\": score, \"B\": score, ...}")
        try:
            g = gw.parse_json(gw.chat(REF, [{"role": "user", "content": prompt}], max_tokens=6000).get("text")) or {}
        except gw.OverBudget:
            g = {}
        for k, (m, _, _) in enumerate(outs):
            if letters[k] in g:
                grades.setdefault(m, []).append(float(g[letters[k]]))

    lines = ["# Find A Crib: which model reads flyers and writes Help me apply (2026-11-12)", "",
             f"{len(flyers)} live flyers from findacrib.com/featured.json with a text layer. Answer key for flyers: "
             f"Claude Opus 5.5 reading the same text ({len(ref)} usable). Every model through Vercel AI Gateway, "
             f"same prompt as production. Total spend ${gw.SPENT['usd']:.2f}.", ""]

    def summary(task, models, scorer):
        out = []
        for m in models:
            rs = [r for r in res if r["task"] == task and r["model"] == m]
            ok = [r for r in rs if r["json"]]
            cost = sum(r["cost"] or 0 for r in rs)
            ms = [r["ms"] for r in ok if r["ms"]]
            row = {"Model": m + (" (open)" if m in OPEN else ""), "Answered": f"{len(ok)}/{len(rs)}",
                   "Cost / 1,000": f"${1000 * cost / max(1, len(rs)):.2f}",
                   "p50 s": f"{statistics.median(ms) / 1000:.1f}" if ms else "—"}
            row.update(scorer(m, rs))
            out.append(row)
        return out

    def flyer_scores(m, rs):
        f1s, kept, dl, fc = [], [], [], []
        for r in rs:
            if r["i"] not in ref:
                continue
            got = r["json"] or {}
            f1s.append(f1(rows(got), rows(ref[r["i"]])))
            kept.append(f1(rows(grounded(got, flyers[r["i"]])), rows(ref[r["i"]])) if r["json"] else 0.0)
            dl.append(norm(got.get("deadline")) == norm(ref[r["i"]].get("deadline")))
            fc.append(bool(got.get("first_come_first_served")) == bool(ref[r["i"]].get("first_come_first_served")))
        mean = lambda xs: f"{sum(xs) / len(xs):.0%}" if xs else "—"  # noqa: E731
        return {"Unit rows (F1)": mean(f1s), "After grounding filter": mean(kept), "Deadline": mean(dl), "First-come": mean(fc)}

    def scan_scores(m, rs):
        s = flyer_scores(m, rs)
        s.pop("After grounding filter")
        return s

    def apply_scores(m, rs):
        g = grades.get(m, [])
        refused = sum(1 for r in rs if r["json"] and apply_filter(r["json"], flyers[r["i"]])[1])
        return {"Opus grade (1-10)": f"{statistics.mean(g):.1f}" if g else "—", "Refused by app": refused}

    cols_f = ["Model", "Unit rows (F1)", "After grounding filter", "Deadline", "First-come", "Answered", "Cost / 1,000", "p50 s"]
    cols_s = ["Model", "Unit rows (F1)", "Deadline", "First-come", "Answered", "Cost / 1,000", "p50 s"]
    cols_a = ["Model", "Opus grade (1-10)", "Refused by app", "Answered", "Cost / 1,000", "p50 s"]
    lines += ["## Flyer reader (text)", "", gw.table(summary("flyer", TEXT_MODELS, flyer_scores), cols_f), "",
              "## Scanned flyer (page images only)", "", gw.table(summary("scan", VISION_MODELS, scan_scores), cols_s), "",
              "## Help me apply", "", gw.table(summary("apply", TEXT_MODELS, apply_scores), cols_a), ""]
    errs = Counter((r["model"], (r["error"] or "")[:60]) for r in res if not r["json"])
    if errs:
        lines += ["Failures: " + "; ".join(f"{m}: {e} ×{n}" for (m, e), n in errs.most_common(12)), ""]
    (HERE / "report.md").write_text("\n".join(lines))
    (HERE / "results.json").write_text(json.dumps({"flyers": [{k: v for k, v in f.items() if k != "pngs"} for f in flyers],
                                                   "results": res, "grades": grades}, indent=1, default=str))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
