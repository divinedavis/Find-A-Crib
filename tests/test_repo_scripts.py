"""scripts/clean_builds.sh and scripts/new_worktree.sh, run against throwaway
directories. Both delete or overwrite files on the owner's Mac, so what they
refuse to do matters as much as what they do.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "scripts" / "clean_builds.sh"
NEW_WT = ROOT / "scripts" / "new_worktree.sh"
HAVE_TOOLS = all(shutil.which(t) for t in ("bash", "git", "curl", "gzip"))


def _age(path: Path, hours: float) -> None:
    """Backdate a path and everything under it."""
    t = time.time() - hours * 3600
    for q in [path, *path.rglob("*")]:
        os.utime(q, (t, t))


@unittest.skipUnless(HAVE_TOOLS, "needs bash, git, curl and gzip")
class CleanBuilds(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name in ("dhcr-map", "dhcr-map-daily"):
            b = self.tmp / name / "ios" / "build.nosync"
            (b / "tests" / "Build").mkdir(parents=True)
            (b / "tests" / "Build" / "app.o").write_bytes(b"x" * 4096)
            (b / "archive.log").write_text("log\n")
            (b / "ship-history.jsonl").write_text('{"build": 1}\n')
            _age(b, 3)
        (self.tmp / "dhcr-map" / "index.html").write_text("source\n")

    def run_clean(self, *args):
        return subprocess.run(["bash", str(CLEAN), "--root", str(self.tmp), *args],
                              capture_output=True, text=True)

    def tree(self, name):
        return self.tmp / name / "ios" / "build.nosync"

    def test_dry_run_without_keep_changes_nothing(self):
        # No --keep at all: bash 3.2 (macOS) treats an empty array under
        # `set -u` as unbound, which used to kill the script right here.
        r = self.run_clean()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 tree(s)", r.stdout)
        self.assertIn("Dry run", r.stdout)
        self.assertTrue((self.tree("dhcr-map") / "tests" / "Build" / "app.o").exists())

    def test_yes_empties_idle_trees_but_keeps_history_keep_and_source(self):
        r = self.run_clean("--yes", "--force", "--keep", "daily")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(q.name for q in self.tree("dhcr-map").iterdir()),
                         ["ship-history.jsonl"])
        self.assertTrue((self.tree("dhcr-map-daily") / "archive.log").exists())
        self.assertTrue((self.tmp / "dhcr-map" / "index.html").exists())

    def test_recently_written_tree_is_skipped(self):
        (self.tree("dhcr-map") / "archive.log").write_text("a build is writing here\n")
        r = self.run_clean()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"busy .*dhcr-map/ios/build\.nosync")
        self.assertIn("1 tree(s)", r.stdout)

    def test_unknown_argument_is_refused(self):
        self.assertEqual(self.run_clean("--yse").returncode, 2)


@unittest.skipUnless(HAVE_TOOLS, "needs bash, git, curl and gzip")
class NewWorktree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.main = self.tmp / "dhcr-map"
        self.site = self.tmp / "site"
        self.main.mkdir()
        self.site.mkdir()
        self.env = {**os.environ, "FAC_SITE": self.site.as_uri(),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        (self.main / "index.html").write_text("app\n")
        (self.main / ".gitignore").write_text("buildings*.json\nbuildings.slim.json.gz\n")
        (self.main / "featured.json").write_text('{"tracked": true}\n')
        for cmd in (["init", "-q", "-b", "main"], ["add", "index.html", "featured.json", ".gitignore"],
                    ["commit", "-q", "-m", "init"]):
            subprocess.run(["git", *cmd], cwd=self.main, env=self.env, check=True)
        # Ignored data as the main checkout holds it: months old.
        (self.main / "buildings.slim.json").write_text('[{"old": 1}]')
        (self.main / "buildings_geo.json").write_text('[{"pipeline": 1}]')
        _age(self.main / "buildings.slim.json", 24 * 60)
        _age(self.main / "buildings_geo.json", 24 * 60)
        (self.site / "buildings.slim.json").write_text('[{"live": 1}]')

    def run_new(self, *args):
        return subprocess.run(["bash", str(NEW_WT), *args, "HEAD", "--no-fetch"],
                              cwd=self.main, env=self.env, capture_output=True, text=True)

    def test_stale_public_file_is_refreshed_then_cloned(self):
        r = self.run_new("task")
        self.assertEqual(r.returncode, 0, r.stderr)
        wt = self.tmp / "dhcr-map-task"
        self.assertEqual((self.main / "buildings.slim.json").read_text(), '[{"live": 1}]')
        self.assertEqual((wt / "buildings.slim.json").read_text(), '[{"live": 1}]')
        # Pipeline-only data has no public source: cloned as it is, and called out.
        self.assertEqual((wt / "buildings_geo.json").read_text(), '[{"pipeline": 1}]')
        self.assertIn("buildings_geo.json", r.stdout)
        # A tracked file is never overwritten by a data copy.
        self.assertEqual((wt / "featured.json").read_text(), '{"tracked": true}\n')

    def test_ios_seed_gzip_is_refreshed(self):
        import gzip
        seed = self.main / "ios" / "FindACrib" / "Resources" / "Data"
        seed.mkdir(parents=True)
        (seed / "buildings.slim.json.gz").write_bytes(gzip.compress(b'[{"old": 1}]'))
        _age(seed / "buildings.slim.json.gz", 24 * 60)
        (self.site / "buildings.slim.json.gz").write_bytes(gzip.compress(b'[{"live": 1}]'))
        r = self.run_new("task")
        self.assertEqual(r.returncode, 0, r.stderr)
        for root in (self.main, self.tmp / "dhcr-map-task"):
            got = gzip.decompress((root / "ios/FindACrib/Resources/Data/buildings.slim.json.gz").read_bytes())
            self.assertEqual(got, b'[{"live": 1}]')
        # ...and a truncated download is thrown away.
        _age(seed / "buildings.slim.json.gz", 24 * 60)
        (self.site / "buildings.slim.json.gz").write_bytes(b"not gzip")
        r = self.run_new("task2")
        self.assertIn("could not refresh ios/FindACrib/Resources/Data/buildings.slim.json.gz", r.stderr)
        self.assertEqual(gzip.decompress((seed / "buildings.slim.json.gz").read_bytes()), b'[{"live": 1}]')

    def test_only_gitignored_files_are_cloned(self):
        # vacancies.json sits untracked and un-ignored in the owner's checkout.
        (self.main / "vacancies.json").write_text("[]")
        r = self.run_new("task")
        self.assertEqual(r.returncode, 0, r.stderr)
        wt = self.tmp / "dhcr-map-task"
        self.assertFalse((wt / "vacancies.json").exists())
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True)
        self.assertEqual(dirty.stdout, "")

    def test_error_page_never_replaces_data(self):
        (self.site / "buildings.slim.json").write_text("<html>502 Bad Gateway</html>")
        r = self.run_new("task")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.main / "buildings.slim.json").read_text(), '[{"old": 1}]')
        self.assertIn("could not refresh buildings.slim.json", r.stderr)
        self.assertEqual(list(self.main.glob("*.download.*")), [])

    def test_no_refresh_leaves_main_alone(self):
        r = self.run_new("task", "--no-refresh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.main / "buildings.slim.json").read_text(), '[{"old": 1}]')

    def test_fresh_file_is_not_downloaded_again(self):
        (self.main / "buildings.slim.json").write_text('[{"today": 1}]')
        r = self.run_new("task")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.main / "buildings.slim.json").read_text(), '[{"today": 1}]')

    def test_existing_path_is_refused(self):
        (self.tmp / "dhcr-map-task").mkdir()
        self.assertEqual(self.run_new("task").returncode, 1)


if __name__ == "__main__":
    unittest.main()
