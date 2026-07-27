#!/usr/bin/env python3
"""The decision journal — what was seen, what was concluded, what changed.

The ledger records *what* each technique is and how it scored. This records the
*reasoning*: why a change was made, what was expected, and what to watch next.
Six months from now the numbers alone will not explain why something was tried,
and a growth log without the thinking is impossible to learn from.

Entries are append-only markdown in `journal.md`, oldest first, one section per
review. It is tracked in git deliberately — the file history is a second,
tamper-evident record of when each decision was actually made.

Written by the daily review (a human or an agent), via:

    python3 growth_daily.py journal --title "..." --observed "..." --concluded "..." \
        --changed "..." --watching "..."

or programmatically with append().
"""
import os

from . import ledger

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL_PATH = os.path.join(HERE, "journal.md")

HEADER = """# Find A Crib — growth decision journal

Append-only. One entry per review. The ledger (`techniques.json`) holds what each
technique *is* and how it scored; this holds *why* — what was observed, what was
concluded, what changed as a result, and what to watch next.

Written by the daily 6am review. Do not rewrite past entries; if a conclusion
turns out to be wrong, say so in a new entry.
"""


def _ensure():
    if not os.path.exists(JOURNAL_PATH):
        with open(JOURNAL_PATH, "w") as f:
            f.write(HEADER)


def append(title, observed="", concluded="", changed="", watching="", author="daily-review"):
    """Add one entry. Every field is free text; empty ones are omitted."""
    _ensure()
    parts = [f"\n\n## {ledger.today()} — {title}\n", f"*{author}*\n"]
    for label, body in (("Observed", observed), ("Concluded", concluded),
                        ("Changed", changed), ("Watching", watching)):
        if body and str(body).strip():
            parts.append(f"\n**{label}.** {str(body).strip()}\n")
    entry = "".join(parts)
    with open(JOURNAL_PATH, "a") as f:
        f.write(entry)
    return entry


def read(last=1):
    """Return the last N entries as text (for the report and for context)."""
    if not os.path.exists(JOURNAL_PATH):
        return ""
    with open(JOURNAL_PATH) as f:
        text = f.read()
    chunks = text.split("\n## ")
    if len(chunks) <= 1:
        return ""
    return "\n## ".join([""] + chunks[-last:]).strip()


def entry_count():
    if not os.path.exists(JOURNAL_PATH):
        return 0
    with open(JOURNAL_PATH) as f:
        return sum(1 for line in f if line.startswith("## "))
