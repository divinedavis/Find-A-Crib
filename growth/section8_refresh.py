#!/usr/bin/env python3
"""Rebuild /section8/ from tonight's voucher feed, and nothing else.

The growth engine has been paused since 2026-10-12 (owner: "pause seo for
FAC"), and t_fresh_section8 only runs inside it. But ~373 hub pages built by
build_seo.py say Find A Crib "rebuilds a list every night" about /section8/,
and error_report's stale_claims flags that promise once /section8/ is more
than two days old (10/21 digest: 2.8 days). The feed itself never stopped
(scrape_affordablehousing.py, 04:15 UTC), so this keeps the promise true
without un-pausing anything:

  * no LLM, no IndexNow, no sitemap or lastmod ledger writes, no git;
  * the pages are rendered by t_fresh_section8 itself, so its stale-feed
    wording ("listings as of <date>") still applies if the feed stops;
  * written to a temp dir and copied over docroot/section8 only on success.

When the engine resumes, its 05:40 build supersedes this; delete the cron line.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from growth import techniques  # noqa: E402


class Section8Context(techniques.Context):
    """Writes pages to a private staging dir and never touches the ledger."""

    def write_page(self, relpath, html, url=None, submit=True):
        full = os.path.join(self.out, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(html)
        return "changed", url or self._url_for(relpath), None


def main():
    docroot = os.environ.get("GROWTH_DOCROOT", "/var/www/rent-map")
    build_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as tmp:
        ctx = Section8Context(build_dir, docroot)
        ctx.out = tmp
        res = techniques.t_fresh_section8(ctx)
        if not res.get("ok"):
            print(f"section8_refresh: not published: {res.get('detail')}")
            return 1
        src = os.path.join(tmp, "section8")
        for dirpath, _, files in os.walk(src):
            dest = os.path.join(docroot, "section8", os.path.relpath(dirpath, src))
            os.makedirs(dest, exist_ok=True)
            for name in files:
                # Copy-then-rename so a reader never sees a half-written page.
                part = os.path.join(dest, name + ".part")
                shutil.copyfile(os.path.join(dirpath, name), part)
                os.chmod(part, 0o644)
                os.replace(part, os.path.join(dest, name))
        print(f"section8_refresh: {res.get('pages')} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
