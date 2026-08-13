#!/usr/bin/env python3
"""One look, and one sender, for every email Find A Crib sends.

The house style already existed in notify_saved_listings.py:render_email() —
inline CSS, a #1a63d6 brand line, a 560px column, multipart text+HTML. This
generalises it rather than inventing a second look, so the buyer sequence, the
account sequence and the report delivery all read as the same product.

Why the constraints are what they are:

  inline CSS only    Gmail strips <style> blocks. A stylesheet in the head
                     silently becomes an unstyled email for a large share of
                     recipients, and you never see it because it renders fine
                     in your own client.
  no images          An email with no images renders identically whether or not
                     the client blocks them, which most do by default. It also
                     avoids tracking pixels, which we are not doing.
  real text part     multipart/alternative with a genuine plain-text body, not
                     a stripped-tags afterthought. Text-only clients and screen
                     readers get something written for them, and a missing or
                     junk text part is a spam signal.
  explicit colours   Dark-mode clients invert unstyled backgrounds and leave
                     styled text where it was, which is how emails end up grey
                     on grey. Every container sets both colour and background.

Callers describe content as blocks and never write markup:

    html, text = render(
        title="A building you saved was just advertised",
        intro="Rent-stabilized units move fast.",
        blocks=[{"type": "card", "heading": "816 Ocean Ave", "meta": "Flatbush",
                 "body": "...", "link": ("View building", url)}],
        cta=("Open the map", "https://findacrib.com/"),
        unsub_url=unsub)
"""
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

SITE = "https://findacrib.com"
BRAND = "Find A Crib"

INK = "#1a1f36"
INK2 = "#5b6472"
INK3 = "#9aa3af"
LINE = "#e3e8ef"
BLUE = "#1a63d6"
PAPER = "#ffffff"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

# Status colours. Tints are opaque, not alpha, so a dark-mode client that
# inverts the page background does not bleed through them.
GOOD, GOOD_BG = "#0b7a4b", "#eaf7f0"
BAD, BAD_BG = "#b42318", "#fef3f2"
WARN, WARN_BG = "#b54708", "#fff8eb"
SOFT = "#f7f9fc"
TONES = {"good": (GOOD, GOOD_BG), "bad": (BAD, BAD_BG), "warn": (WARN, WARN_BG),
         "info": (BLUE, "#eef4fe"), "mute": (INK2, SOFT)}


def esc(s):
    return (str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def safe_url(u):
    """Only http(s) and mailto reach an href.

    Some of the URLs in these emails are written by a model — the scout's
    technique notes, the outreach drafts it researches. esc() stops attribute
    injection but not a `javascript:` or `data:` href, so the scheme is checked
    here rather than trusted at every call site. Anything else renders as '#'.
    """
    s = str(u or "").strip()
    if re.match(r"^(https?://|mailto:|/|#)", s, re.I) and "\n" not in s:
        return s
    return "#"


def _strip(html):
    """Fallback text for a block that only supplied HTML. Not used for whole
    emails — every block contributes its own written text line."""
    t = re.sub(r"<br\s*/?>", "\n", html or "")
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()


# ------------------------------------------------------------------- blocks

def _paragraph(b):
    html = (f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;'
            f'color:{INK};background:{PAPER}">{esc(b["text"])}</p>')
    return html, b["text"]


def _card(b):
    link_html = ""
    if b.get("link"):
        label, url = b["link"]
        link_html = (f'<a href="{esc(safe_url(url))}" style="color:{BLUE};font-weight:600;'
                     f'font-size:14px;text-decoration:none">{esc(label)} &rarr;</a>')
    html = (f'<div style="border:1px solid {LINE};border-radius:10px;padding:14px 16px;'
            f'margin:0 0 12px;background:{PAPER}">'
            f'<div style="font-weight:700;font-size:16px;color:{INK}">{esc(b["heading"])}</div>'
            + (f'<div style="color:{INK2};font-size:13px;margin:2px 0 8px">{esc(b["meta"])}</div>'
               if b.get("meta") else "")
            + (f'<div style="color:{INK};font-size:14px;line-height:1.55;margin:0 0 8px">'
               f'{esc(b["body"])}</div>' if b.get("body") else "")
            + link_html + "</div>")
    text = b["heading"]
    if b.get("meta"):
        text += f"\n  {b['meta']}"
    if b.get("body"):
        text += f"\n  {b['body']}"
    if b.get("link"):
        text += f"\n  {b['link'][1]}"
    return html, text


def _steps(b):
    items = b["items"]
    lis = "".join(
        f'<li style="margin:0 0 8px;font-size:15px;line-height:1.55;color:{INK}">{esc(i)}</li>'
        for i in items)
    html = (f'<ol style="margin:0 0 14px;padding-left:22px;background:{PAPER}">{lis}</ol>')
    text = "\n".join(f"  {n}. {i}" for n, i in enumerate(items, 1))
    return html, text


def _quote(b):
    """A monospace block for things meant to be copied — a letter, an address."""
    html = (f'<pre style="margin:0 0 14px;padding:14px 16px;border:1px solid {LINE};'
            f'border-radius:10px;background:#fbfcfd;color:{INK};font-size:13px;'
            f'line-height:1.55;white-space:pre-wrap;font-family:ui-monospace,'
            f'SFMono-Regular,Menlo,Consolas,monospace">{esc(b["text"])}</pre>')
    return html, b["text"]


def _stats(b):
    """A row of numbers. Falls back to stacked lines on narrow screens because
    it is inline-block, not flex — flex is unreliable in Outlook."""
    cells = "".join(
        f'<span style="display:inline-block;min-width:120px;margin:0 14px 10px 0;'
        f'vertical-align:top">'
        f'<span style="display:block;font-size:22px;font-weight:700;color:{INK}">{esc(v)}</span>'
        f'<span style="display:block;font-size:12px;color:{INK2}">{esc(l)}</span></span>'
        for v, l in b["items"])
    html = f'<div style="margin:0 0 12px;background:{PAPER}">{cells}</div>'
    text = " · ".join(f"{v} {l}" for v, l in b["items"])
    return html, text


# --------------------------------------------------- report-shaped blocks
#
# A daily report is a dashboard, not a letter: sections, tiles, progress
# against a target, tables, pass/fail. These blocks exist so a report never
# has to hand-write markup, and so every report in the product looks alike.
#
# All of them lay out with <table>, not flex or grid. Outlook's word-based
# renderer drops both, and a report is exactly the kind of email people read
# in Outlook.

def _tbl(inner, style=""):
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="border-collapse:collapse;{style}">{inner}</table>')


def _section(b):
    """A ruled section heading. The rule is what makes a long report skimmable."""
    note = (f'<div style="font-size:12px;color:{INK3};margin:3px 0 0;line-height:1.5">'
            f'{esc(b["note"])}</div>') if b.get("note") else ""
    html = _tbl(
        f'<tr><td style="border-top:1px solid {LINE};padding:20px 0 10px">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:.09em;'
        f'text-transform:uppercase;color:{INK2}">{esc(b["label"])}</div>{note}</td></tr>',
        "margin:12px 0 0")
    text = "\n" + str(b["label"]).upper() + (f"  ({b['note']})" if b.get("note") else "")
    return html, text


def _tiles(b):
    """Headline numbers, two per row. Two — not four — because a 640px column
    becomes ~300px on a phone, and four tiles would each be unreadably narrow."""
    items = b["items"]
    rows, text = [], []
    for i in range(0, len(items), 2):
        cells = []
        for it in items[i:i + 2]:
            tone = TONES.get(it.get("tone") or "mute", (INK2, SOFT))
            delta = (f'<div style="font-size:12px;font-weight:600;color:{tone[0]};'
                     f'margin:4px 0 0">{esc(it["delta"])}</div>') if it.get("delta") else ""
            cells.append(
                f'<td width="50%" valign="top" style="padding:0 6px 12px 0">'
                f'<div style="background:{SOFT};border:1px solid {LINE};border-radius:10px;'
                f'padding:13px 14px">'
                f'<div style="font-size:11px;font-weight:700;letter-spacing:.06em;'
                f'text-transform:uppercase;color:{INK2}">{esc(it["label"])}</div>'
                f'<div style="font-size:26px;font-weight:800;color:{INK};line-height:1.15;'
                f'margin:5px 0 0">{esc(it["value"])}</div>{delta}</div></td>')
            text.append(f"  {it['label']}: {it['value']}"
                        + (f" ({it['delta']})" if it.get("delta") else ""))
        if len(items[i:i + 2]) == 1:
            cells.append('<td width="50%">&nbsp;</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    # table-layout:fixed, or an auto table refuses to shrink below the widest
    # tile's min-content and pushes the whole email off a phone screen.
    return _tbl("".join(rows), "margin:0 0 4px;table-layout:fixed"), "\n".join(text)


def _progress(b):
    """Distance to a target. The bar is a two-cell table with a percentage
    width — the only progress bar that survives every mail client."""
    pct = max(0.0, min(100.0, float(b.get("pct") or 0)))
    colour = TONES.get(b.get("tone") or "info", (BLUE, SOFT))[0]
    # Below half a percent, render an empty track rather than a sliver that
    # rounds up to something visible. The point is to be honest about zero.
    fill = (f'<td width="{pct:.1f}%" style="height:7px;line-height:7px;font-size:0;'
            f'background:{colour};border-radius:99px">&nbsp;</td>') if pct >= 0.5 else ""
    bar = _tbl(f'<tr>{fill}<td style="height:7px;line-height:7px;font-size:0">&nbsp;</td></tr>',
               f"background:{LINE};border-radius:99px")
    sub = (f'<div style="font-size:12px;color:{INK2};margin:5px 0 0;line-height:1.5">'
           f'{esc(b["sub"])}</div>') if b.get("sub") else ""
    # The gap below has to be clearly larger than the gap between a bar and its
    # own caption, or the caption reads as belonging to the next row.
    html = (
        f'<div style="margin:0 0 20px;background:{PAPER}">'
        + _tbl(f'<tr>'
               f'<td style="font-size:14px;font-weight:600;color:{INK};padding:0 8px 6px 0">'
               f'{esc(b["label"])}</td>'
               f'<td align="right" style="font-size:14px;color:{INK};padding:0 0 6px;'
               f'white-space:nowrap">{esc(b["value"])}</td></tr>')
        + bar + sub + "</div>")
    text = f"  {b['label']:<16} {b['value']}" + (f"\n      {b['sub']}" if b.get("sub") else "")
    return html, text


def _cell(c):
    """A cell is a string, a (text, tone) pair, or {text, tone, sub}. `sub` is a
    second muted line under the value — it keeps a narrow table from needing an
    extra column, which is what actually breaks the layout on a phone."""
    if isinstance(c, dict):
        return c.get("text"), c.get("tone"), c.get("sub")
    if isinstance(c, (tuple, list)):
        return c[0], (c[1] if len(c) > 1 else None), None
    return c, None, None


def _cell_text(c):
    return _cell(c)[0]


def _table(b):
    """Rows of `cols`, laid out to survive a 320px-wide phone: fixed layout with
    declared column widths, and long tokens wrap rather than forcing the whole
    message to scroll sideways. `widths` are percentages; the default gives the
    label column the slack and splits the rest evenly."""
    aligns = b.get("align") or ["left"] * len(b["cols"])
    n = len(b["cols"])
    widths = b.get("widths")
    if not widths:
        first = 46 if n > 2 else 60
        widths = [first] + [round((100 - first) / (n - 1))] * (n - 1) if n > 1 else [100]
    head = "".join(
        f'<th align="{a}" width="{w}%" style="font-size:11px;font-weight:700;'
        f'letter-spacing:.05em;text-transform:uppercase;color:{INK3};padding:0 8px 7px 0;'
        f'border-bottom:1px solid {LINE};word-break:break-word;line-height:1.35">{esc(c)}</th>'
        for c, a, w in zip(b["cols"], aligns, widths))
    body = []
    for r in b["rows"]:
        tds = []
        for c, a in zip(r, aligns):
            text, tone, sub = _cell(c)
            colour = TONES.get(tone, (INK, SOFT))[0] if tone else INK
            weight = "600" if tone else "400"
            mono = f"font-family:{MONO};" if b.get("mono") and a == "right" else ""
            sub_html = (f'<div style="font-size:11px;color:{INK3};font-weight:400;'
                        f'margin:2px 0 0;line-height:1.4">{esc(sub)}</div>') if sub else ""
            tds.append(f'<td align="{a}" style="font-size:13px;color:{colour};'
                       f'font-weight:{weight};{mono}padding:8px 8px 8px 0;'
                       f'border-bottom:1px solid #f0f3f7;line-height:1.45;'
                       f'word-break:break-word">{esc(text)}{sub_html}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    html = _tbl(f"<tr>{head}</tr>" + "".join(body), "margin:0 0 16px;table-layout:fixed")
    all_rows = [b["cols"]] + list(b["rows"])
    widths = [max(len(str(_cell_text(r[i]))) for r in all_rows) for i in range(len(b["cols"]))]
    lines = []
    for row in all_rows:
        lines.append("  " + "  ".join(str(_cell_text(c)).ljust(w)
                                      for c, w in zip(row, widths)).rstrip())
        for sub in (s for s in (_cell(c)[2] for c in row) if s):
            lines.append(f"      {sub}")
    return html, "\n".join(lines)


def _status(b):
    """Pass/fail lines for a batch of jobs. Failure is loud on purpose."""
    rows = []
    text = []
    for it in b["items"]:
        ok = it.get("ok")
        colour, bg = (GOOD, GOOD_BG) if ok else (BAD, BAD_BG)
        label = "OK" if ok else "FAIL"
        rows.append(
            f'<tr>'
            f'<td valign="top" width="44" style="padding:0 8px 9px 0">'
            f'<span style="display:inline-block;background:{bg};color:{colour};'
            f'font-size:10px;font-weight:800;letter-spacing:.06em;padding:3px 7px;'
            f'border-radius:5px">{label}</span></td>'
            f'<td valign="top" width="36%" style="padding:0 8px 9px 0;font-size:12.5px;'
            f'font-weight:600;color:{INK};font-family:{MONO};word-break:break-word">'
            f'{esc(it["name"])}</td>'
            f'<td valign="top" style="padding:0 0 9px;font-size:13px;color:{INK2};'
            f'line-height:1.5;word-break:break-word">{esc(it.get("detail") or "")}</td></tr>')
        text.append(f"  [{'ok  ' if ok else 'FAIL'}] {it['name']:<18} {it.get('detail', '')}")
    return _tbl("".join(rows), "margin:0 0 14px;table-layout:fixed"), "\n".join(text)


def _callout(b):
    """A tinted box for the things that need the reader to do something.
    `items` renders as a bulleted list; `body` as a single paragraph."""
    colour, bg = TONES.get(b.get("tone") or "warn", (WARN, WARN_BG))
    head = (f'<div style="font-size:14px;font-weight:700;color:{colour};margin:0 0 4px">'
            f'{esc(b["heading"])}</div>') if b.get("heading") else ""
    if b.get("items"):
        body_html = "".join(
            f'<div style="font-size:13px;color:{INK};line-height:1.55;margin:0 0 3px">'
            f'&bull;&nbsp;&nbsp;{esc(it)}</div>' for it in b["items"])
        body_text = "\n".join(f"      • {it}" for it in b["items"])
    else:
        body_html = (f'<div style="font-size:13px;color:{INK};line-height:1.55">'
                     f'{esc(b["body"])}</div>')
        body_text = f"      {b['body']}"
    html = (f'<div style="background:{bg};border-left:3px solid {colour};border-radius:8px;'
            f'padding:12px 14px;margin:0 0 12px">{head}{body_html}</div>')
    text = (f"  {b['heading']}\n{body_text}" if b.get("heading") else body_text.lstrip())
    return html, text


def _chips(b):
    """Short strings as pills — query lists, tags. Wraps naturally, no columns
    to get out of sync."""
    chips = "".join(
        f'<span style="display:inline-block;background:{SOFT};border:1px solid {LINE};'
        f'border-radius:99px;padding:5px 11px;margin:0 6px 7px 0;font-size:12px;'
        f'color:{INK2}">{esc(c)}</span>' for c in b["items"])
    return (f'<div style="margin:0 0 12px;background:{PAPER}">{chips}</div>',
            "\n".join(f"  · {c}" for c in b["items"]))


def _note(b):
    return (f'<p style="margin:0 0 14px;font-size:12px;color:{INK3};line-height:1.55;'
            f'background:{PAPER}">{esc(b["text"])}</p>', f"  {b['text']}")


RENDERERS = {"paragraph": _paragraph, "card": _card, "steps": _steps,
             "quote": _quote, "stats": _stats, "section": _section, "tiles": _tiles,
             "progress": _progress, "table": _table, "status": _status,
             "callout": _callout, "chips": _chips, "note": _note}


# ------------------------------------------------------------------- render

def render(title, blocks=None, intro=None, cta=None, footer_note=None, unsub_url=None,
           unsub_label="Unsubscribe", width=560, eyebrow=None):
    """Build (html, text). `blocks` is a list of dicts with a `type` key.

    `width` widens the column for reports — tables and progress bars need more
    room than a letter does. `eyebrow` is a small line above the title (a date,
    a run label) that keeps the headline itself short.
    """
    blocks = blocks or []
    body_html, body_text = [], []
    for b in blocks:
        fn = RENDERERS.get(b.get("type"))
        if not fn:
            continue
        h, t = fn(b)
        body_html.append(h)
        if t:
            body_text.append(t)

    cta_html = ""
    if cta:
        label, url = cta
        cta_html = (
            f'<div style="margin:4px 0 18px;background:{PAPER}">'
            f'<a href="{esc(safe_url(url))}" style="display:inline-block;background:{BLUE};'
            f'color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:11px 20px;'
            f'border-radius:9px">{esc(label)}</a></div>')
        body_text.append(f"{label}: {url}")

    foot_bits = []
    if footer_note:
        foot_bits.append(esc(footer_note))
    if unsub_url:
        foot_bits.append(f'<a href="{esc(safe_url(unsub_url))}" style="color:{INK3}">'
                         f'{esc(unsub_label)}</a>')
    foot_html = (f'<p style="margin:22px 0 0;padding-top:14px;border-top:1px solid {LINE};'
                 f'color:{INK3};font-size:12px;line-height:1.55;background:{PAPER}">'
                 + " ".join(foot_bits) + "</p>") if foot_bits else ""

    # The shell is a table, not a padded div. A div with max-width and padding
    # is content-box in mail clients, so on a 390px phone its own padding pushes
    # the card wider than the screen and the right-hand column is cut off.
    html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;background:#f6f7f9;margin:0;'
        f'-webkit-text-size-adjust:100%"><tr>'
        f'<td align="center" style="padding:24px 12px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;max-width:{int(width)}px;margin:0 auto">'
        f'<tr><td style="font-family:{FONT};padding:26px 22px;background:{PAPER};'
        f'border-radius:12px;color:{INK}">'
        f'<div style="font-weight:800;font-size:17px;color:{BLUE};margin:0 0 10px">{BRAND}</div>'
        + (f'<div style="font-size:12px;font-weight:600;letter-spacing:.07em;'
           f'text-transform:uppercase;color:{INK3};margin:0 0 4px">{esc(eyebrow)}</div>'
           if eyebrow else "")
        + f'<h1 style="font-size:21px;line-height:1.3;margin:0 0 8px;color:{INK}">'
          f'{esc(title)}</h1>'
        + (f'<p style="color:{INK2};font-size:14px;margin:0 0 18px;line-height:1.55">'
           f'{esc(intro)}</p>' if intro else "")
        + "".join(body_html) + cta_html + foot_html
        + "</td></tr></table></td></tr></table>")

    text_parts = [f"{eyebrow} — {title}" if eyebrow else title]
    if intro:
        text_parts.append(intro)
    text_parts += body_text
    if footer_note:
        text_parts.append(f"—\n{BRAND} · {SITE}\n{footer_note}")
    else:
        text_parts.append(f"—\n{BRAND} · {SITE}")
    if unsub_url:
        text_parts.append(f"{unsub_label}: {unsub_url}")
    text = "\n\n".join(p for p in text_parts if p) + "\n"
    return html, text


# --------------------------------------------------------------------- send

def smtp_configured():
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send(to, subject, html, text, unsub_url=None, from_name=BRAND):
    """multipart/alternative, with one-click unsubscribe headers when given.

    The text part goes first: multipart/alternative is ordered least- to
    most-preferred, so text-then-html is what tells a client the HTML is the
    richer alternative. Reversed, some clients show the raw markup.
    """
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASSWORD")
    if not (host and user and pw):
        raise RuntimeError("SMTP_HOST / SMTP_USER / SMTP_PASSWORD not set")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, user))
    msg["To"] = to
    if unsub_url:
        msg["List-Unsubscribe"] = f"<{unsub_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    return True
