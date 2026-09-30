"""Business & legal checklist: the owner's progress on the company setup for
all the apps (LLC, DBAs, trademarks, copyrights, accounts, insurance, estate).

The checklist itself (steps, costs, links) is static and lives in the page,
dashboard/business/index.html. This module stores only what the owner changes:
a flat map of key -> value, e.g.

    "item.file_articles"            -> true        (step ticked)
    "note.file_articles"            -> "filed 10/2, ID 1234"
    "item.findacrib.trademark"      -> true        (a step in an app's group)
    "app.spendcap.track"            -> "no"        (app moved off the board
                                                    into the registry; "yes"
                                                    brings it back)
    "custom.meeting-notes"          -> "product|Meeting Notes"  (an app the
                                                    owner added by hand)

Where it lives: BUSINESS_DIR on the droplet (default
/var/lib/findacrib-api/business), writable by the `findacrib` service user.
Not in git: this repo is public and notes may hold filing numbers.

The app list and company steps are private too (they name the employer,
clients, and which app holds patient data), so they are not in the page:
CATALOG is catalog.json beside the state, shipped from the owner's laptop by
scripts/deploy_business_catalog.sh, and only returned to the signed-in owner.
"""
import contextlib, datetime, fcntl, json, os, pathlib, re, threading

BUSINESS_DIR = pathlib.Path(os.environ.get("BUSINESS_DIR", "/var/lib/findacrib-api/business"))
DB = BUSINESS_DIR / "state.json"
CATALOG = BUSINESS_DIR / "catalog.json"
_LOCK = threading.Lock()

KEY_RE = re.compile(r"^(item|note|app|custom)\.[a-z0-9_-]{1,40}(\.[a-z0-9_-]{1,24})?$")
MAX_KEYS = 2000
MAX_TEXT = 1000


@contextlib.contextmanager
def _locked():
    with _LOCK:
        BUSINESS_DIR.mkdir(parents=True, exist_ok=True)
        with open(BUSINESS_DIR / "state.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield


def _load():
    try:
        return json.loads(DB.read_text())
    except FileNotFoundError:
        return {"values": {}, "updated": {}}


def _save(db):
    tmp = DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=1, sort_keys=True))
    os.chmod(tmp, 0o600)
    os.replace(tmp, DB)


def listing():
    db = _load()
    try:
        catalog = json.loads(CATALOG.read_text())
    except (FileNotFoundError, ValueError):
        catalog = {"company": [], "apps": []}
    return {"values": db.get("values", {}), "updated": db.get("updated", {}), "catalog": catalog}


def update(body):
    """Set one key. `value` is a bool for ticks, a short string otherwise;
    null clears the key."""
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    key, value = body.get("key"), body.get("value")
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise ValueError("bad key")
    kind = key.split(".", 1)[0]
    if kind == "item" and not (value is None or isinstance(value, bool)):
        raise ValueError("item values are true/false")
    if kind in ("note", "app", "custom") and not (value is None or (isinstance(value, str) and len(value) <= MAX_TEXT)):
        raise ValueError("value too long")
    with _locked():
        db = _load()
        vals, upd = db.setdefault("values", {}), db.setdefault("updated", {})
        if value is None or value == "" or value is False:
            vals.pop(key, None)
            upd.pop(key, None)
            _save(db)
            return {"key": key, "value": None, "updated": None}
        else:
            if key not in vals and len(vals) >= MAX_KEYS:
                raise ValueError("too many keys")
            vals[key] = value
        upd[key] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        _save(db)
    return {"key": key, "value": vals.get(key), "updated": upd[key]}
