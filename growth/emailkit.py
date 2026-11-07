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
        title="A building you saved changed",
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


def mask_email(addr):
    """'jane.doe@gmail.com' -> 'j***@gmail.com', for cron logs.

    The alert jobs print one line per send. Until 2026-10-07 that put every
    subscriber's full address into /var/log/rentmap-alerts.log (~23k lines,
    world-readable). The domain stays: it is what tells a deliverability
    problem (all the aol.com sends bounced) apart from a code problem."""
    a = str(addr or "")
    local, at, domain = a.partition("@")
    if not at:
        return "***" if a else ""
    return (local[:1] or "") + "***@" + domain

SITE = "https://findacrib.com"
BRAND = "Find A Crib"
# CAN-SPAM (15 U.S.C. 7704(a)(5)) wants a valid physical postal address in
# every commercial email; we put it in EVERY email render() and
# render_alert() build, transactional ones too, so no caller can forget it.
# Owner approved this address on 2026-11-07.
POSTAL = "Find A Crib · 251 Dekalb Ave, Brooklyn, NY 11205"

INK = "#1a1f36"
INK2 = "#5b6472"
INK3 = "#9aa3af"
LINE = "#e3e8ef"
BLUE = "#1a63d6"
PAPER = "#ffffff"
# The grey page the white groups sit on (owner, 2026-10-27: design #2 of
# three, an iPhone-style grouped list readable on a phone).
PAGE = "#f2f2f7"
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
            f'color:{INK};background:{PAGE}">{esc(b["text"])}</p>')
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
    html = (f'<ol style="margin:0 0 14px;padding-left:22px;background:{PAGE}">{lis}</ol>')
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
    html = f'<div style="margin:0 0 12px;background:{PAGE}">{cells}</div>'
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
        f'<div style="margin:0 0 20px;background:{PAGE}">'
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
    `items` renders as a bulleted list; `body` as a single paragraph.

    An item may be a plain string or {"text": ..., "url": ..., "sub": ...}.
    With a url the text becomes a real link. This exists because mail clients
    auto-link anything that LOOKS like a street address — iOS Mail turned every
    listing in the re-rental digest into an Apple Maps link, which is the one
    destination the reader does not want. A real href beats the client's guess.

    A linked item is a BLOCK anchor, not an inline one, and that is the whole
    point. An inline link that wraps onto a second line is only reliably
    tappable on its first line in the iOS mail clients: the re-rental digest
    lists addresses long enough to wrap to two and three lines on a phone, so
    "some of these links don't open on mobile" was the row's continuation
    lines falling through the tap. As a block with padding, every pixel of the
    row — both lines, the gap, the `sub` caption — is one target. `sub` is a
    muted second line inside that same target, which is also somewhere safe to
    tap when a client's address detector has grabbed the address text itself.
    """
    colour, bg = TONES.get(b.get("tone") or "warn", (WARN, WARN_BG))
    if b.get("items") and any(isinstance(it, dict) and it.get("url") for it in b["items"]):
        return _group(b)
    head = (f'<div style="font-size:14px;font-weight:700;color:{colour};margin:0 0 4px">'
            f'{esc(b["heading"])}</div>') if b.get("heading") else ""
    if b.get("items"):
        def _one(it, first=False):
            if isinstance(it, dict):
                txt, url, sub = it.get("text", ""), it.get("url"), it.get("sub")
            else:
                txt, url, sub = it, None, None
            if not url:
                one = (f'<div style="font-size:13px;color:{INK};line-height:1.55;'
                       f'margin:0 0 3px">&bull;&nbsp;&nbsp;{esc(txt)}</div>')
                if sub:
                    one += (f'<div style="font-size:12px;color:{INK3};line-height:1.5;'
                            f'margin:0 0 6px 16px">{esc(sub)}</div>')
                return one
            # 9px of padding either side of a 13px/1.5 line clears Apple's
            # 44px minimum touch target on a one-line row without a min-height
            # that Outlook would ignore anyway. The negative margin lets the
            # target run to the callout's own padding edge. A hairline between
            # rows because the bullets are gone: with none, two stacked
            # addresses read as one four-line paragraph.
            rule = "" if first else f"border-top:1px solid {LINE};"
            return (f'<a href="{esc(safe_url(url))}" style="display:block;{rule}'
                    f'color:{BLUE};text-decoration:none;font-size:13px;line-height:1.5;'
                    f'padding:9px 10px;margin:0 -10px;border-radius:7px">'
                    f'<span style="text-decoration:underline">{esc(txt)}</span>'
                    + (f'<span style="display:block;font-size:12px;color:{INK2};'
                       f'text-decoration:none;margin:3px 0 0">{esc(sub)}</span>'
                       if sub else "")
                    + '</a>')

        def _one_text(it):
            if isinstance(it, dict):
                return (f"      • {it.get('text','')}"
                        + (f"\n        {it['sub']}" if it.get("sub") else "")
                        + (f"\n        {it['url']}" if it.get("url") else ""))
            return f"      • {it}"

        body_html = "".join(_one(it, i == 0) for i, it in enumerate(b["items"]))
        body_text = "\n".join(_one_text(it) for it in b["items"])
    else:
        body_html = (f'<div style="font-size:13px;color:{INK};line-height:1.55">'
                     f'{esc(b["body"])}</div>')
        body_text = f"      {b['body']}"
    html = (f'<div style="background:{bg};border-left:3px solid {colour};border-radius:8px;'
            f'padding:12px 14px;margin:0 0 12px">{head}{body_html}</div>')
    text = (f"  {b['heading']}\n{body_text}" if b.get("heading") else body_text.lstrip())
    return html, text


def _group(b):
    """Linked items as an iPhone-style grouped list (owner, 2026-10-27, design
    #2): a grey caps label, then one white rounded group with a row per item.
    Each row is one table whose cells are all links to the same place, so the
    whole row is the tap target (see _callout on why a wrapped inline link
    is not). An item may add `right` (a price) and `right_sub` (beds) for the
    right-hand column; a chevron says the row opens something."""
    def cell(url, inner, style):
        return (f'<td valign="middle" style="{style}"><a href="{esc(safe_url(url))}" '
                f'style="display:block;text-decoration:none;color:{INK}">{inner}</a></td>')
    rows = []
    for i, it in enumerate(b["items"]):
        if not isinstance(it, dict):
            it = {"text": it}
        url = it.get("url") or "#"
        rule = f"border-top:1px solid {LINE};" if i else ""
        left = (f'<span style="display:block;font-size:17px;font-weight:700;line-height:1.3;color:{INK}">{esc(it.get("text", ""))}</span>'
                + (f'<span style="display:block;font-size:14px;line-height:1.4;color:{INK2};margin-top:3px">{esc(it["sub"])}</span>'
                   if it.get("sub") else ""))
        right = ""
        if it.get("right") or it.get("right_sub"):
            right = ((f'<span style="display:block;font-size:18px;font-weight:800;color:{INK}">{esc(it["right"])}</span>' if it.get("right") else "")
                     + (f'<span style="display:block;font-size:12px;color:{INK2}">{esc(it["right_sub"])}</span>' if it.get("right_sub") else ""))
        rows.append('<tr>'
                    + cell(url, left, f"{rule}padding:14px 0 14px 16px")
                    + cell(url, right, f"{rule}padding:14px 4px 14px 8px;text-align:right;white-space:nowrap")
                    + cell(url, f'<span style="font-size:22px;color:#c7cbd1">&rsaquo;</span>', f"{rule}padding:14px 14px 14px 2px;width:12px")
                    + '</tr>')
    head = (f'<div style="font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
            f'color:{INK2};margin:0 4px 8px">{esc(b["heading"])}</div>') if b.get("heading") else ""
    html = (f'<div style="margin:0 0 18px">{head}'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:separate;background:{PAPER};border-radius:14px;font-family:{FONT}">'
            + "".join(rows) + '</table></div>')
    lines = []
    for it in b["items"]:
        it = it if isinstance(it, dict) else {"text": it}
        lines.append(f"      • {it.get('text', '')}"
                     + (f" — {it['right']}" if it.get("right") else "")
                     + (f"\n        {it['sub']}" if it.get("sub") else "")
                     + (f"\n        {it['url']}" if it.get("url") else ""))
    text = "\n".join(lines)
    return html, (f"  {b['heading']}\n{text}" if b.get("heading") else text.lstrip())


def _counts(b):
    """Up to three numbers in white tiles across the top of an alert: "3 new
    this week · 2 Brooklyn · 1 Manhattan". items: [(number, label), ...]."""
    items = list(b["items"])[:3]
    w = f"{100 // max(1, len(items))}%"
    tds = "".join(
        f'<td width="{w}" align="center" style="padding:0 0 0 {0 if i == 0 else 8}px">'
        f'<div style="background:{PAPER};border-radius:12px;padding:14px 4px">'
        f'<div style="font-size:26px;font-weight:800;color:{BLUE};line-height:1.1">{esc(n)}</div>'
        f'<div style="font-size:12px;color:{INK2};margin-top:2px">{esc(label)}</div></div></td>'
        for i, (n, label) in enumerate(items))
    html = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:collapse;margin:0 0 20px;font-family:{FONT}"><tr>{tds}</tr></table>')
    return html, " · ".join(f"{n} {label}" for n, label in items)


def _chips(b):
    """Short strings as pills — query lists, tags. Wraps naturally, no columns
    to get out of sync."""
    chips = "".join(
        f'<span style="display:inline-block;background:{SOFT};border:1px solid {LINE};'
        f'border-radius:99px;padding:5px 11px;margin:0 6px 7px 0;font-size:12px;'
        f'color:{INK2}">{esc(c)}</span>' for c in b["items"])
    return (f'<div style="margin:0 0 12px;background:{PAGE}">{chips}</div>',
            "\n".join(f"  · {c}" for c in b["items"]))


def _note(b):
    return (f'<p style="margin:0 0 14px;font-size:13px;color:{INK2};line-height:1.55;'
            f'background:{PAGE}">{esc(b["text"])}</p>', f"  {b['text']}")


def _upsell(b):
    """A short pitch with its own button inside the box (2026-10-06, the
    8 AM alert digest's "get real-time alerts"): heading, one line, and a
    rectangular button. {"heading", "text", "button": (label, url)}."""
    label, url = b["button"]
    html = (f'<div style="margin:0 0 18px;padding:16px 18px;border:1px solid #c4b5fd;border-radius:10px;'
            f'background:#f5f3ff">'
            f'<div style="font-weight:700;font-size:16px;color:#3b0764;line-height:1.35;margin:0 0 6px">{esc(b["heading"])}</div>'
            f'<div style="font-size:14px;color:#4c1d95;line-height:1.5;margin:0 0 12px">{esc(b["text"])}</div>'
            f'<a href="{esc(safe_url(url))}" style="display:block;text-align:center;background:#5b21b6;color:#ffffff;'
            f'text-decoration:none;font-weight:700;font-size:15px;padding:12px 16px;border-radius:4px">{esc(label)}</a>'
            f'</div>')
    return html, f"{b['heading']}\n  {b['text']}\n  {label}: {url}"


RENDERERS = {"paragraph": _paragraph, "card": _card, "steps": _steps,
             "quote": _quote, "stats": _stats, "section": _section, "tiles": _tiles,
             "progress": _progress, "table": _table, "status": _status,
             "callout": _callout, "counts": _counts, "chips": _chips, "note": _note, "upsell": _upsell}


# ------------------------------------------------------------ alert card
#
# The look every alert a USER gets (owner, 2026-11-05, picked "rent dropped"
# of five designs and said "lets use it"): one white card on the grey page,
# the logo and a coloured label on top, a big headline over a hairline, the
# building as a row with a coloured square, one big number with pills under
# it, an optional comparison bar, a full-width blue button and a quieter
# link. Internal reports keep render()'s plain style.
#
# The same constraints as above: inline CSS, tables for anything side by
# side, no images (the coloured square is a filled cell, its gradient a
# progressive extra a client without background-image support shows flat).
# Blocks only ever show numbers the caller has; a block with nothing real to
# say is left out, never filled with a guess.

PURPLE, PURPLE_BG = "#6a3df0", "#f0ebff"
TEAL, TEAL_BG = "#0e7490", "#e0f5f8"
TONES.update({"lottery": (PURPLE, PURPLE_BG), "voucher": (TEAL, TEAL_BG)})
RULE = "#eef2f7"
# Square colour per tone, and the order rows in a list cycle through.
SQUARES = {"good": ("#34c48b", "#0b7a4b"), "bad": ("#f87171", "#dc2626"),
           "warn": ("#fbbf24", "#d97706"), "info": ("#7cb4ff", "#3b82f6"),
           "lottery": ("#c4b5fd", "#7c3aed"), "voucher": ("#67d4e4", "#0e7490"),
           "mute": ("#f6c08b", "#d9734e")}
CYCLE = ["mute", "lottery", "info", "good", "voucher", "warn"]


def _square(tone, size=52):
    a, b = SQUARES.get(tone or "mute", SQUARES["mute"])
    return (f'<td width="{size}" valign="middle" style="width:{size}px;padding:0 14px 0 0">'
            f'<div style="width:{size}px;height:{size}px;border-radius:{size // 4}px;background:{b};'
            f'background-image:linear-gradient(135deg,{a},{b});font-size:1px;line-height:{size}px">'
            f'&nbsp;</div></td>')


def _a_building(b, tone=None):
    """A building (or anything with a name): square, name, a muted line under
    it, and optionally a value on the right. `body` and `link` from a plain
    card follow under the row, so every existing card renders in the new look."""
    right = ""
    if b.get("right") or b.get("right_sub"):
        rt = TONES.get(b.get("right_tone"), (INK, None))[0] if b.get("right_tone") else INK
        right = (f'<td align="right" valign="middle" style="padding:0 0 0 10px;white-space:nowrap">'
                 + (f'<div style="font-size:17px;font-weight:800;color:{rt}">{esc(b["right"])}</div>'
                    if b.get("right") else "")
                 + (f'<div style="font-size:12px;font-weight:600;color:{INK2}">{esc(b["right_sub"])}</div>'
                    if b.get("right_sub") else "") + "</td>")
    row = _tbl(f'<tr>{_square(b.get("tone") or tone)}'
               f'<td valign="middle"><div style="font-size:16px;font-weight:700;color:{INK};line-height:1.3">'
               f'{esc(b["heading"])}</div>'
               + (f'<div style="font-size:14px;color:{INK2};margin-top:2px;line-height:1.4">{esc(b["meta"])}</div>'
                  if b.get("meta") else "")
               + f'</td>{right}</tr>', "margin:0 0 14px")
    body = (f'<p style="margin:0 0 12px;font-size:15px;line-height:1.55;color:{INK};background:{PAPER}">'
            f'{esc(b["body"])}</p>') if b.get("body") else ""
    link = ""
    if b.get("link"):
        label, url = b["link"]
        link = (f'<p style="margin:0 0 16px"><a href="{esc(safe_url(url))}" style="color:{BLUE};'
                f'font-weight:600;font-size:15px;text-decoration:none">{esc(label)} &rarr;</a></p>')
    return row + body + link, _card(b)[1]


def _a_big(b):
    """The one number that matters: $2,195 with $2,450 struck through, or
    "3 new this week". {value, was?, sub?, tone?}"""
    colour = TONES.get(b.get("tone"), (INK, None))[0] if b.get("tone") else INK
    html = (f'<div style="margin:4px 0 8px;line-height:1.1">'
            f'<span style="font-size:42px;font-weight:800;letter-spacing:-1px;color:{colour}">{esc(b["value"])}</span>'
            + (f'&nbsp;&nbsp;<span style="font-size:21px;font-weight:600;color:{INK3};'
               f'text-decoration:line-through">{esc(b["was"])}</span>' if b.get("was") else "")
            + (f'&nbsp;&nbsp;<span style="font-size:16px;font-weight:600;color:{INK2}">{esc(b["sub"])}</span>'
               if b.get("sub") else "") + "</div>")
    text = str(b["value"]) + (f" (was {b['was']})" if b.get("was") else "") + (f" {b['sub']}" if b.get("sub") else "")
    return html, text


def _a_pills(b):
    """Toned pills: [(text, tone)] or plain strings."""
    items = [(i, None) if isinstance(i, str) else (i[0], i[1] if len(i) > 1 else None)
             for i in b["items"] if i and (i if isinstance(i, str) else i[0])]
    if not items:
        return "", ""
    spans = "".join(
        f'<span style="display:inline-block;background:{TONES.get(t, (INK2, "#f1f5f9"))[1] if t else "#f1f5f9"};'
        f'color:{TONES.get(t, ("#334155", None))[0] if t else "#334155"};border-radius:99px;'
        f'padding:6px 11px;margin:0 6px 7px 0;font-size:13px;font-weight:600">{esc(x)}</span>'
        for x, t in items)
    return f'<div style="margin:0 0 12px">{spans}</div>', " · ".join(x for x, _ in items)


def _a_compare(b):
    """A labelled bar: {label, pct, tone, caption}. Only for a real
    comparison the caller computed; there is no default number."""
    pct = max(0.0, min(100.0, float(b.get("pct") or 0)))
    colour = TONES.get(b.get("tone") or "info", (BLUE, None))[0]
    fill = (f'<td width="{pct:.1f}%" style="height:10px;line-height:10px;font-size:0;'
            f'background:{colour};border-radius:99px">&nbsp;</td>') if pct >= 0.5 else ""
    html = (f'<div style="margin:4px 0 14px">'
            f'<div style="font-size:14px;color:{INK2};margin:0 0 7px">{esc(b["label"])}</div>'
            + _tbl(f'<tr>{fill}<td style="height:10px;line-height:10px;font-size:0">&nbsp;</td></tr>',
                   f"background:{RULE};border-radius:99px")
            + (f'<div style="font-size:14px;color:{INK2};margin:7px 0 0;line-height:1.5">{esc(b["caption"])}</div>'
               if b.get("caption") else "") + "</div>")
    return html, f"{b['label']}: {b.get('caption') or ''}".rstrip(": ")


def _a_section(b):
    html = (f'<div style="font-size:12px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;'
            f'color:{INK2};margin:20px 0 8px">{esc(b["label"])}</div>')
    return html, "\n" + str(b["label"]).upper()


def _a_list(b):
    """Linked items as rows: square, name, line under it, price on the right.
    Every cell is the same link, so the whole row is the tap target (see
    _callout for why a wrapped inline link is not)."""
    tone = b.get("tone")
    head = _a_section({"label": b["heading"]})[0] if b.get("heading") else ""
    rows = []
    for n, it in enumerate(b["items"]):
        it = it if isinstance(it, dict) else {"text": it}
        url = esc(safe_url(it.get("url") or "#"))
        rule = f"border-top:1px solid {RULE};" if n else ""
        sq = (it.get("tone") or (tone if tone in SQUARES and tone not in ("good", "info", "warn")
                                 else CYCLE[n % len(CYCLE)]))
        a, c = SQUARES.get(sq, SQUARES["mute"])

        def cell(inner, style):
            return (f'<td valign="middle" style="{rule}{style}"><a href="{url}" style="display:block;'
                    f'text-decoration:none;color:{INK}">{inner}</a></td>')
        right = ""
        if it.get("right") or it.get("right_sub"):
            right = ((f'<span style="display:block;font-size:16px;font-weight:800;color:{INK}">{esc(it["right"])}</span>'
                      if it.get("right") else "")
                     + (f'<span style="display:block;font-size:12px;font-weight:600;color:{INK2}">{esc(it["right_sub"])}</span>'
                        if it.get("right_sub") else ""))
        rows.append(
            "<tr>"
            + cell(f'<span style="display:block;width:44px;height:44px;border-radius:12px;background:{c};'
                   f'background-image:linear-gradient(135deg,{a},{c})">&nbsp;</span>', "width:44px;padding:12px 12px 12px 0")
            + cell(f'<span style="display:block;font-size:15px;font-weight:700;line-height:1.3;color:{INK}">'
                   f'{esc(it.get("text", ""))}</span>'
                   + (f'<span style="display:block;font-size:13px;line-height:1.4;color:{INK2};margin-top:2px">'
                      f'{esc(it["sub"])}</span>' if it.get("sub") else ""), "padding:12px 0")
            + cell(right, "padding:12px 0 12px 8px;text-align:right;white-space:nowrap")
            + "</tr>")
    html = (f'<div style="margin:0 0 10px">{head}'
            + _tbl("".join(rows), "table-layout:auto") + "</div>")
    return html, _group(b)[1]


def _a_callout(b):
    if b.get("items") and any(isinstance(it, dict) and it.get("url") for it in b["items"]):
        return _a_list(b)
    return _callout(b)


def _a_counts(b):
    """Counts tiles become the big number and pills: "4 new" over
    "2 Brooklyn · 1 Manhattan"."""
    items = list(b["items"])[:3]
    if not items:
        return "", ""
    n, label = items[0]
    big = _a_big({"value": n, "sub": label})
    pills = _a_pills({"items": [(f"{c} {l}", "info") for c, l in items[1:]]})
    return big[0] + pills[0], " · ".join(f"{c} {l}" for c, l in items)


def _a_note(b):
    return (f'<p style="margin:0 0 12px;font-size:13px;color:{INK2};line-height:1.55;'
            f'background:{PAPER}">{esc(b["text"])}</p>', f"  {b['text']}")


def _a_stats(b):
    """A row of up to three numbers as soft tiles, one table row, so they
    sit side by side on a phone too (inline-blocks stacked raggedly)."""
    items = list(b["items"])[:3]
    w = f"{100 // max(1, len(items))}%"
    tds = "".join(
        f'<td width="{w}" valign="top" style="padding:0 0 0 {0 if i == 0 else 8}px">'
        f'<div style="background:#f8fafc;border:1px solid #e9eef5;border-radius:14px;padding:12px">'
        f'<div style="font-size:22px;font-weight:800;color:{INK};line-height:1.1">{esc(v)}</div>'
        f'<div style="font-size:12px;color:{INK2};margin-top:3px;line-height:1.3">{esc(l)}</div></div></td>'
        for i, (v, l) in enumerate(items))
    return _tbl(f"<tr>{tds}</tr>", "margin:0 0 14px;table-layout:fixed"), " · ".join(f"{v} {l}" for v, l in items)


ALERT_RENDERERS = dict(RENDERERS, stats=_a_stats, card=_a_building, building=_a_building, big=_a_big,
                       pills=_a_pills, compare=_a_compare, section=_a_section,
                       callout=_a_callout, counts=_a_counts, note=_a_note)


def _postal_html():
    """The postal line for an HTML footer. Apple Mail and Gmail turn a street
    address into a blue Maps link; the span keeps our grey where they allow."""
    return f'<span style="color:{INK3};text-decoration:none">{esc(POSTAL)}</span>'


def postal_text():
    """The postal line for a hand-built email (one that doesn't go through
    render() / render_alert()), so every sender prints the same address."""
    return POSTAL


def render_alert(title, blocks=None, intro=None, cta=None, link=None, tag=None,
                 footer_note=None, unsub_url=None, unsub_label="Unsubscribe", eyebrow=None):
    """(html, text) in the alert-card look. `tag` is (label, tone) for the
    pill top right; `link` a (label, url) under the button. `eyebrow` is
    kept for the text part only; the tag carries it in the HTML."""
    body_html, body_text = [], []
    for b in blocks or []:
        fn = ALERT_RENDERERS.get(b.get("type"))
        if not fn:
            continue
        h, t = fn(b)
        # Text blocks shared with render() paint the grey page behind
        # themselves (the dark-mode rule above); on the card it is white.
        body_html.append(h.replace(f"background:{PAGE}", f"background:{PAPER}"))
        if t:
            body_text.append(t)
    tag_html = ""
    if tag:
        label, tone = tag
        c, bg = TONES.get(tone, (BLUE, "#e8f0fe"))
        tag_html = (f'<td align="right" valign="middle"><span style="display:inline-block;background:{bg};'
                    f'color:{c};font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;'
                    f'padding:6px 11px;border-radius:99px;white-space:nowrap">{esc(label)}</span></td>')
    cta_html = ""
    if cta:
        label, url = cta
        cta_html = (f'<a href="{esc(safe_url(url))}" style="display:block;text-align:center;background:{BLUE};'
                    f'color:#ffffff;text-decoration:none;font-weight:700;font-size:16px;padding:16px 20px;'
                    f'border-radius:14px;margin:20px 0 4px">{esc(label)}</a>')
        body_text.append(f"{label}: {url}")
    link_html = ""
    if link:
        label, url = link
        link_html = (f'<a href="{esc(safe_url(url))}" style="display:block;text-align:center;color:{BLUE};'
                     f'text-decoration:none;font-weight:600;font-size:15px;padding:12px 10px 0">'
                     f'{esc(label)} &rarr;</a>')
        body_text.append(f"{label}: {url}")
    foot = []
    if footer_note:
        foot.append(esc(footer_note))
    if unsub_url:
        foot.append(f'<a href="{esc(safe_url(unsub_url))}" style="color:{INK2}">{esc(unsub_label)}</a>')
    foot.append(_postal_html())
    html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;background:{PAGE};margin:0;-webkit-text-size-adjust:100%"><tr>'
        f'<td align="center" style="padding:24px 10px 32px;background:{PAGE}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;max-width:600px;margin:0 auto">'
        f'<tr><td style="font-family:{FONT};background:{PAPER};color:{INK};border-radius:22px;'
        f'padding:24px 24px 26px;box-shadow:0 8px 28px rgba(15,23,42,.06)">'
        + _tbl(f'<tr><td width="30" valign="middle" style="width:30px;padding:0 10px 0 0">'
               f'<div style="width:30px;height:30px;line-height:30px;border-radius:9px;background:{BLUE};'
               f'color:#ffffff;font-size:12px;font-weight:800;text-align:center">FAC</div></td>'
               f'<td valign="middle" style="font-size:15px;font-weight:700;color:{INK}">{BRAND}</td>'
               f'{tag_html}</tr>')
        + f'<h1 style="font-size:26px;line-height:1.18;letter-spacing:-.4px;font-weight:800;color:{INK};'
          f'margin:20px 0 14px;padding:0 0 14px;border-bottom:1px solid {RULE}">{esc(title)}</h1>'
        + (f'<p style="color:{INK2};font-size:15px;margin:0 0 16px;line-height:1.5">{esc(intro)}</p>'
           if intro else "")
        + "".join(body_html) + cta_html + link_html
        + f'</td></tr><tr><td align="center" style="font-family:{FONT};padding:18px 16px 0;'
          f'color:{INK3};font-size:12px;line-height:1.7;background:{PAGE}">'
        + "<br>".join(foot) + "</td></tr></table></td></tr></table>")
    parts = [f"{eyebrow} — {title}" if eyebrow else title]
    if intro:
        parts.append(intro)
    parts += body_text
    parts.append(f"—\n{BRAND} · {SITE}" + (f"\n{footer_note}" if footer_note else ""))
    if unsub_url:
        parts.append(f"{unsub_label}: {unsub_url}")
    parts.append(POSTAL)
    return html, "\n\n".join(p for p in parts if p) + "\n"


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
            f'<div style="margin:4px 0 18px;background:{PAGE}">'
            f'<a href="{esc(safe_url(url))}" style="display:block;text-align:center;background:{BLUE};'
            f'color:#ffffff;text-decoration:none;font-weight:700;font-size:17px;padding:15px 20px;'
            f'border-radius:14px">{esc(label)}</a></div>')
        body_text.append(f"{label}: {url}")

    foot_bits = []
    if footer_note:
        foot_bits.append(esc(footer_note))
    if unsub_url:
        foot_bits.append(f'<a href="{esc(safe_url(unsub_url))}" style="color:{INK3}">'
                         f'{esc(unsub_label)}</a>')
    foot_html = (f'<p style="margin:22px 0 0;padding-top:14px;border-top:1px solid {LINE};'
                 f'color:{INK3};font-size:12px;line-height:1.55;background:{PAGE}">'
                 + (" ".join(foot_bits) + "<br>" if foot_bits else "")
                 + _postal_html() + "</p>")

    # The shell is a table, not a padded div. A div with max-width and padding
    # is content-box in mail clients, so on a 390px phone its own padding pushes
    # the card wider than the screen and the right-hand column is cut off.
    # Since 2026-10-27 (owner picked design #2 of three) the page is grey and
    # the content sits on it like an iPhone settings screen: brand and date on
    # one line, a big title, then white groups. Text blocks carry the page
    # grey as their own background so dark-mode clients cannot invert one
    # and not the other.
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo as _Z
        today = _dt.datetime.now(_Z("America/New_York"))
        today = f"{today:%a}, {today:%b} {today.day}"
    except Exception:
        today = ""
    html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;background:{PAGE};margin:0;'
        f'-webkit-text-size-adjust:100%"><tr>'
        f'<td align="center" style="padding:22px 12px 32px;background:{PAGE}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse;max-width:{int(width)}px;margin:0 auto">'
        f'<tr><td style="font-family:{FONT};padding:0 4px;background:{PAGE};color:{INK}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse">'
        f'<tr><td style="font-family:{FONT};font-weight:800;font-size:17px;color:{BLUE}">{BRAND}</td>'
        f'<td align="right" style="font-family:{FONT};font-size:13px;color:{INK2}">{esc(today)}</td></tr></table>'
        + (f'<div style="font-size:13px;font-weight:700;letter-spacing:.06em;'
           f'text-transform:uppercase;color:{INK2};margin:18px 0 4px">{esc(eyebrow)}</div>'
           if eyebrow else '<div style="height:14px;line-height:14px;font-size:1px">&nbsp;</div>')
        + f'<h1 style="font-size:26px;line-height:1.2;font-weight:800;margin:0 0 10px;color:{INK}">'
          f'{esc(title)}</h1>'
        + (f'<p style="color:{INK2};font-size:16px;margin:0 0 20px;line-height:1.5">'
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
    text_parts.append(POSTAL)
    text = "\n\n".join(p for p in text_parts if p) + "\n"
    return html, text


# --------------------------------------------------------------------- send

def smtp_configured():
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


# Addresses that bounced for good, or three times (db/0068, filled by
# mail_bounce_sort.py). Owner, 2026-10-20, about the bounce notices filling
# divine@findacrib.com: every alert job kept mailing testing@gmail.com,
# a gmail.ckm typo and a dead maio.com address every single day.
_SUPPRESSED = {"at": 0.0, "set": frozenset()}


def suppressed(addr):
    """True when `addr` is on the suppression list. Loaded once per 10 min per
    process; with no Supabase env or no answer, nothing is suppressed."""
    import json, time, urllib.request
    now = time.time()
    if now - _SUPPRESSED["at"] > 600:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        _SUPPRESSED["at"] = now
        if url and key:
            try:
                req = urllib.request.Request(f"{url}/rest/v1/email_suppressions?select=email&suppressed=is.true&limit=10000",
                                             headers={"apikey": key, "Authorization": f"Bearer {key}"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    _SUPPRESSED["set"] = frozenset(row["email"] for row in json.load(r))
            except Exception:
                pass   # keep the last list we had
    return (addr or "").strip().lower() in _SUPPRESSED["set"]


def send(to, subject, html, text, unsub_url=None, from_name=BRAND):
    """multipart/alternative, with one-click unsubscribe headers when given.

    The text part goes first: multipart/alternative is ordered least- to
    most-preferred, so text-then-html is what tells a client the HTML is the
    richer alternative. Reversed, some clients show the raw markup.

    Returns False without sending to a suppressed address (see suppressed()).
    """
    if suppressed(to):
        print(f"emailkit: skipped suppressed {mask_email(to)}")
        return False
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
