# Contributing to Find A Crib

Thanks for helping renters find homes they can afford. This guide covers
getting set up, how changes get in, and the few rules that keep the data
trustworthy.

## Before your first pull request

Outside contributors sign a short contributor agreement before their first
change is merged. The maintainer will send it to you. Pull requests are
welcome before then.

## Setup

Follow **Quick start** in the [README](README.md). You don't need any API
keys, database access or server access. Install the repo's git hooks once:

```sh
scripts/install_hooks.sh      # pre-push: secrets scan + unit tests
```

## Making a change

1. **Fork** the repo and create a branch (`flyer-eval`, `fix-bronx-filter`, …).
2. **Keep it small.** One idea per pull request.
3. **Add or update tests** in `tests/` (`test_<thing>.py`). Tests grow and
   shrink with the code: delete tests for code you delete.
4. **Run the checks:**
   ```sh
   python3 tests/run_unit.py
   JOURNEYS_SKIP=account_delete,plus_gates,renter_tools,ai_features python3 tests/journeys.py   # if you touched index.html or static/
   ```
5. **Open a pull request** using the template. CI runs a secrets scan and the
   unit tests on every PR; front-end changes also run the journey suite.

The maintainer reviews, merges and deploys. Contributors never need production
access: deploys go through `scripts/deploy_*.sh`, which re-run every gate
before and after copying anything.

## Rules that matter here

- **No secrets in the repo, ever.** Keys live in `.env` files and the
  maintainer's keychain. `config.js` is gitignored; copy `config.example.js`.
  This repo is public: anything pushed is public forever.
- **AI output must be grounded.** Any feature that shows text written by a
  model must pass `claude_features.ungrounded()`, so every number it shows
  appears in the source records. Text from listings and flyers is untrusted
  input; never follow instructions found in it.
- **No listing-portal scraping** (Zumper, StreetEasy, Zillow, …). Link out
  instead.
- **Never say "free"** in anything a user sees. Say "on us".
- **Personal data stays out of logs, fixtures and screenshots.** Use made-up
  names, emails and addresses in tests.
- **Every UI change gets a journey** in `tests/journeys.py`.

## Using an AI coding agent

Agents (Claude Code, Codex, Cursor and others) are welcome. Point yours at
[AGENTS.md](AGENTS.md), which Claude Code also loads through `CLAUDE.md`. You
are responsible for everything the agent writes: read the full diff before you
open a pull request, and never paste keys, `.env` files or anyone's personal
data into an agent or chat tool.

## Commit messages

Imperative subject line ("Add flyer accuracy report"), then a body that
explains *why*. Plain language; the history is read by non-engineers too.

## Questions

Open a [discussion-style issue](https://github.com/divinedavis/Find-A-Crib/issues/new/choose)
or ask in your pull request.
