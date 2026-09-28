"""Creator outreach: the owner's tracker for paid creator reviews.

One row per creator, keyed by their social handle. Rows are never deleted
(owner, 2026-09-28: "rows dont get removed"); they move through STAGES.

Where the data lives: a JSON file and the brief files under CREATOR_DIR on
this droplet (default /var/lib/findacrib-api/creators, writable by the
unprivileged `findacrib` service user). Nothing here is in git: this repo is
public, and rows hold creators' names and email addresses.

Who writes:
- the owner, from /dashboard/creators/ (stage, dates, rate, notes);
- the owner's laptop app ("Creator Briefs", ~/projects/CreatorBriefs), through
  /creators-ingest with X-Ingest-Key, when it makes a brief or finds a pitch
  in the mailbox's Sent folder.
gunicorn runs one worker (deploy/findacrib-api.override.conf), so a process
lock around read-modify-write is enough.
"""
import base64, datetime, json, os, pathlib, re, threading

CREATOR_DIR = pathlib.Path(os.environ.get("CREATOR_DIR", "/var/lib/findacrib-api/creators"))
DB = CREATOR_DIR / "creators.json"
FILES = CREATOR_DIR / "files"
_LOCK = threading.Lock()

STAGES = ["not_reached_out", "reached_out", "contract_in_progress",
          "contract_sent", "contract_confirmed", "contract_complete"]
PRODUCTS = ("marracat", "findacrib", "haukley")   # haukley: film creators (owner, 2026-09-28)
HANDLE_RE = re.compile(r"^[a-z0-9._-]{1,40}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_FILE = 2_000_000          # a brief is ~50 KB (PDF) or ~300 KB (JPG)

# Fields the owner may edit from the page, and how each is checked.
EDITABLE = {
    "stage": lambda v: v in STAGES,
    "sent_at": lambda v: v is None or bool(DATE_RE.match(v)),
    "contract_start": lambda v: v is None or bool(DATE_RE.match(v)),
    "due_date": lambda v: v is None or bool(DATE_RE.match(v)),
    "rate": lambda v: v is None or (isinstance(v, str) and len(v) <= 40),
    "notes": lambda v: v is None or (isinstance(v, str) and len(v) <= 2000),
    "email": lambda v: v is None or (isinstance(v, str) and bool(EMAIL_RE.match(v))),
}


def _today():
    return datetime.date.today().isoformat()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _load():
    try:
        return json.loads(DB.read_text())
    except FileNotFoundError:
        return {"creators": {}}


def _save(db):
    CREATOR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=1, sort_keys=True))
    os.chmod(tmp, 0o600)
    tmp.replace(DB)


def _set_stage(row, stage):
    """Move a row to `stage`, logging when. Reaching out stamps the send date."""
    if row.get("stage") == stage:
        return
    row["stage"] = stage
    row.setdefault("stage_log", []).append({"stage": stage, "at": _now()})
    if stage != "not_reached_out" and not row.get("sent_at"):
        row["sent_at"] = _today()
    if stage == "contract_confirmed" and not row.get("contract_start"):
        row["contract_start"] = _today()
    if stage == "contract_complete" and not row.get("completed_at"):
        row["completed_at"] = _today()


def _public(row):
    r = {k: v for k, v in row.items() if not k.startswith("_")}
    r["complete"] = row.get("stage") == "contract_complete"
    r["has_pdf"] = (FILES / f"{row['id']}.pdf").exists()
    r["has_jpg"] = (FILES / f"{row['id']}.jpg").exists()
    return r


def listing():
    with _LOCK:
        rows = list(_load()["creators"].values())
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return [_public(r) for r in rows]


def update(cid, body):
    """Owner edit from the page. Returns the row, or raises ValueError."""
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    bad = [k for k in body if k not in EDITABLE or not EDITABLE[k](body[k])]
    if bad:
        raise ValueError("invalid field(s): " + ", ".join(sorted(bad)))
    with _LOCK:
        db = _load()
        row = db["creators"].get(cid)
        if row is None:
            raise KeyError(cid)
        for k, v in body.items():
            if k == "stage":
                _set_stage(row, v)
            else:
                row[k] = v
        row["updated_at"] = _now()
        _save(db)
        return _public(row)


def _lev(a, b):
    """Edit distance, for handles a screenshot misread by a letter."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def find_existing(creators, handle, email=None, name=None):
    """The row this creator already has, if any (owner, 2026-09-28: "make sure
    duplicates dont go on the creator dashboard"). Same handle; else the same
    email; else a handle one edit away with the same name (a screenshot read
    "dejalashayyy" where the email says "dejalashayy")."""
    if handle in creators:
        return handle
    em = (email or "").strip().lower()
    nm = (name or "").strip().lower()
    for key, row in creators.items():
        if em and (row.get("email") or "").lower() == em:
            return key
    for key, row in creators.items():
        if nm and (row.get("name") or "").strip().lower() == nm and _lev(key, handle) <= 1:
            return key
    return None


def ingest(payload):
    """Upsert from the laptop app. Never deletes, never moves a stage back.

    payload: {handle, name, product, platform, followers, email, fit, flags,
              note, post_by, stage?, sent_at?, jpg_b64?, pdf_b64?}
    """
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    handle = str(payload.get("handle") or "").lstrip("@").strip().lower()
    if not HANDLE_RE.match(handle):
        raise ValueError("bad handle")
    product = payload.get("product")
    email = payload.get("email") or None
    if email is not None and not (isinstance(email, str) and EMAIL_RE.match(email)):
        email = None
    blobs = {}
    for ext, magic in (("pdf", b"%PDF-"), ("jpg", b"\xff\xd8\xff")):
        raw = payload.get(f"{ext}_b64")
        if raw:
            data = base64.b64decode(raw, validate=True)
            if len(data) > MAX_FILE or not data.startswith(magic):
                raise ValueError(f"bad {ext}")
            blobs[ext] = data
    with _LOCK:
        db = _load()
        key = find_existing(db["creators"], handle, email, payload.get("name"))
        if key and key != handle:
            # Same creator under another spelling: update that row, remember the alias.
            row = db["creators"][key]
            if handle not in row.setdefault("aliases", []):
                row["aliases"].append(handle)
            handle = key
        row = db["creators"].get(handle)
        new = row is None
        if new:
            row = {"id": handle, "handle": handle, "created_at": _now(), "stage": "not_reached_out",
                   "stage_log": [{"stage": "not_reached_out", "at": _now()}], "sent_at": None,
                   "contract_start": None, "due_date": None, "rate": None, "notes": None}
            db["creators"][handle] = row
        for k in ("name", "platform", "followers", "fit", "note"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                row[k] = v.strip()[:200]
        if product in PRODUCTS:
            row["product"] = product
        if isinstance(payload.get("flags"), list):
            row["flags"] = [str(f)[:200] for f in payload["flags"][:8]]
        if email and not row.get("email"):
            row["email"] = email
        pb = payload.get("post_by")
        if isinstance(pb, str) and DATE_RE.match(pb) and not row.get("due_date"):
            row["due_date"] = pb
        stage = payload.get("stage")
        if stage in STAGES and STAGES.index(stage) > STAGES.index(row.get("stage", "not_reached_out")):
            _set_stage(row, stage)
        sa = payload.get("sent_at")
        if isinstance(sa, str) and DATE_RE.match(sa) and row.get("stage") != "not_reached_out":
            row["sent_at"] = sa
        if blobs:
            FILES.mkdir(parents=True, exist_ok=True)
            for ext, data in blobs.items():
                p = FILES / f"{handle}.{ext}"
                p.write_bytes(data)
                os.chmod(p, 0o600)
            row["brief_name"] = str(payload.get("brief_name") or "")[:120] or None
        row["updated_at"] = _now()
        _save(db)
        return {"id": handle, "created": new}


def brief_file(cid, ext):
    if ext not in ("pdf", "jpg") or not HANDLE_RE.match(cid or ""):
        return None
    p = FILES / f"{cid}.{ext}"
    return p if p.exists() else None
