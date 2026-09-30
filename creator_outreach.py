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
- the reply reader (creator_mail_reader.py, cron), which fills in a creator's
  rate from their email reply.
gunicorn runs one worker (deploy/findacrib-api.override.conf), but the reply
reader is a second process, so read-modify-write takes a thread lock and a
file lock (_locked).
"""
import base64, contextlib, datetime, fcntl, imaplib, json, os, pathlib, re, smtplib, ssl, threading, time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

CREATOR_DIR = pathlib.Path(os.environ.get("CREATOR_DIR", "/var/lib/findacrib-api/creators"))
DB = CREATOR_DIR / "creators.json"
FILES = CREATOR_DIR / "files"
_LOCK = threading.Lock()


@contextlib.contextmanager
def _locked():
    with _LOCK:
        CREATOR_DIR.mkdir(parents=True, exist_ok=True)
        with open(CREATOR_DIR / "creators.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield


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
    # The owner's calendar day, not the droplet's (UTC): a send at 9 pm in New
    # York must not read as tomorrow (it did on 2026-09-28).
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()


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
    r["can_send"] = bool(row.get("email")) and r["has_pdf"] and mailbox(row.get("product")) is not None
    return r


def listing():
    with _locked():
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
    with _locked():
        db = _load()
        row = db["creators"].get(cid)
        if row is None:
            raise KeyError(cid)
        for k, v in body.items():
            if k == "stage":
                _set_stage(row, v)
            else:
                row[k] = v
            if k == "rate":
                # A rate typed on the page is never overwritten by a later
                # email; clearing it lets the next reply fill it again.
                row["rate_source"] = "owner" if v else None
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
    with _locked():
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


# ---------- sending a pitch from the page ----------
# Owner, 2026-09-28: "make a button per row for me to send the email with pdf".
# The wording mirrors CreatorBriefs/mail_draft.py (draft + PITCH); keep the two in step.
MAILBOXES = CREATOR_DIR / "mail_forward.json"    # [{product, host, user, password, forward_to}], 0600
NAMES = {"marracat": "Marracat", "findacrib": "Find A Crib", "haukley": "Haukley"}
PITCH = {
    "haukley": ("Haukley is a free streaming service with 74 movies and 7 series and no subscription, "
                "including the Pioneers of Black Cinema collection, at haukley.com."),
    "marracat": ("Marracat is a free iPhone app with 1,000+ Black-owned and independent brands and "
                 "100,000+ products in one place, and you check out with the brand right in the app."),
    "findacrib": ("Find A Crib is a free app that maps every rent-stabilized building in New York City "
                  "and shows what's for rent there this week."),
}


def mailbox(product):
    try:
        boxes = json.loads(MAILBOXES.read_text())
    except (FileNotFoundError, PermissionError):
        return None
    return next((b for b in boxes if b.get("product") == product), None)


def _pitch(product, name, to, cfg):
    brand = NAMES[product]
    first = (name or "there").split()[0]
    m = EmailMessage()
    m["From"] = formataddr((cfg.get("from_name") or brand, cfg["user"]))
    m["To"] = to
    m["Subject"] = f"Paid review: {brand} x {name}"
    m["Message-ID"] = make_msgid(domain=cfg["user"].split("@")[1])
    m["Date"] = formatdate(localtime=True)
    m.set_content(f"""Hi {first},

I'm reaching out from {brand}. We love your content and would like to pay you for a {brand} review video.

{PITCH[product]}

The brief is attached, with what to show in the video, the deliverables and the date. If you're interested, reply with your rate and we'll take it from there.

Thanks,
{cfg.get("signature") or cfg.get("from_name") or brand}
""")
    return m


def send_pitch(cid):
    """Email this creator their PDF brief from the product's mailbox, file it in Sent, drop the matching draft, mark "reached out".
    Returns the updated row. Raises KeyError / ValueError with a reason."""
    with _locked():
        row = _load()["creators"].get(cid)
    if row is None:
        raise KeyError(cid)
    to, product = row.get("email"), row.get("product")
    if not to:
        raise ValueError("no email on file for this creator")
    cfg = mailbox(product)
    if cfg is None:
        raise ValueError(f"no {NAMES.get(product, product)} mailbox is set up to send from")
    pdf = FILES / f"{cid}.pdf"
    if not pdf.exists():
        raise ValueError("no PDF brief on file for this creator")
    m = _pitch(product, row.get("name") or cid, to, cfg)
    m.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                     filename=f"{NAMES[product]} Creator Brief - {row.get('name') or cid}.pdf")
    ctx = ssl.create_default_context()
    host = cfg.get("host", "mail.privateemail.com")
    with smtplib.SMTP_SSL(host, 465, context=ctx, timeout=60) as s:
        s.login(cfg["user"], cfg["password"])
        # No Bcc to the owner's Gmail (owner, 2026-09-30: "stop forwarding
        # emails from marracat to my gmail"); the copy is filed in Sent below.
        s.send_message(m, to_addrs=[to])
    try:
        with imaplib.IMAP4_SSL(host, 993, ssl_context=ctx, timeout=60) as i:
            i.login(cfg["user"], cfg["password"])
            i.append("Sent", "\\Seen", imaplib.Time2Internaldate(time.time()), m.as_bytes())
            i.select("Drafts")
            typ, data = i.search(None, "TO", to)
            for n in (data[0].split() if typ == "OK" and data[0] else []):
                i.store(n, "+FLAGS", "\\Deleted")
            i.expunge()
    except Exception:
        pass            # the email went out; filing it is housekeeping
    with _locked():
        db = _load()
        row = db["creators"][cid]
        if row.get("stage") == "not_reached_out":
            _set_stage(row, "reached_out")
        row["sent_at"] = row.get("sent_at") or _today()
        row.setdefault("sends", []).append(_now())
        row["updated_at"] = _now()
        _save(db)
        return _public(row)


# ---------- replies ----------
# Owner, 2026-09-30: "read emails that come to marracat and update the
# dashboard with their rate". creator_mail_reader.py calls this per reply.
def record_reply(sender, when, subject, rate=None, quote=None):
    """Note a reply from `sender` on that creator's row and, when the reply
    quotes a rate, put it in `rate` unless the owner typed one. Returns the
    row id, or None when the sender isn't a creator on the page."""
    em = (sender or "").strip().lower()
    if not em:
        return None
    with _locked():
        db = _load()
        row = next((r for r in db["creators"].values() if (r.get("email") or "").lower() == em), None)
        if row is None:
            return None
        if when >= (row.get("replied_at") or ""):
            row["replied_at"] = when
            row["reply_subject"] = (subject or "")[:200]
        if rate and row.get("rate_source") != "owner" and (not row.get("rate") or row.get("rate_source") == "email") \
                and when >= (row.get("rate_at") or ""):
            row["rate"] = rate[:40]
            row["rate_source"] = "email"
            row["rate_at"] = when
            row["rate_quote"] = (quote or "")[:300] or None
        row["updated_at"] = _now()
        _save(db)
        return row["id"]
