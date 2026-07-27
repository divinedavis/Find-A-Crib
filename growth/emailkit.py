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


def esc(s):
    return (str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


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
        link_html = (f'<a href="{esc(url)}" style="color:{BLUE};font-weight:600;'
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


RENDERERS = {"paragraph": _paragraph, "card": _card, "steps": _steps,
             "quote": _quote, "stats": _stats}


# ------------------------------------------------------------------- render

def render(title, blocks=None, intro=None, cta=None, footer_note=None, unsub_url=None,
           unsub_label="Unsubscribe"):
    """Build (html, text). `blocks` is a list of dicts with a `type` key."""
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
            f'<a href="{esc(url)}" style="display:inline-block;background:{BLUE};color:#ffffff;'
            f'text-decoration:none;font-weight:600;font-size:15px;padding:11px 20px;'
            f'border-radius:9px">{esc(label)}</a></div>')
        body_text.append(f"{label}: {url}")

    foot_bits = []
    if footer_note:
        foot_bits.append(esc(footer_note))
    if unsub_url:
        foot_bits.append(f'<a href="{esc(unsub_url)}" style="color:{INK3}">{esc(unsub_label)}</a>')
    foot_html = (f'<p style="margin:22px 0 0;padding-top:14px;border-top:1px solid {LINE};'
                 f'color:{INK3};font-size:12px;line-height:1.55;background:{PAPER}">'
                 + " ".join(foot_bits) + "</p>") if foot_bits else ""

    html = (
        f'<div style="background:#f6f7f9;padding:24px 0;margin:0">'
        f'<div style="font-family:{FONT};max-width:560px;margin:0 auto;padding:26px 22px;'
        f'background:{PAPER};border-radius:12px;color:{INK}">'
        f'<div style="font-weight:800;font-size:17px;color:{BLUE};margin:0 0 10px">{BRAND}</div>'
        f'<h1 style="font-size:21px;line-height:1.3;margin:0 0 8px;color:{INK}">{esc(title)}</h1>'
        + (f'<p style="color:{INK2};font-size:14px;margin:0 0 18px;line-height:1.55">'
           f'{esc(intro)}</p>' if intro else "")
        + "".join(body_html) + cta_html + foot_html
        + "</div></div>")

    text_parts = [title]
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
