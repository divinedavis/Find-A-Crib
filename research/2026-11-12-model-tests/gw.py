"""One way to call any model through Vercel AI Gateway for the 2026-11-12 model
tests (owner: "lets do a test", "which model best performs", "does an open
model perform better"). OpenAI-compatible chat completions, the gateway's own
per-call cost, retries on 429/5xx, and a hard dollar cap shared by every call
in the process so a test can't run past its budget.

Key: $AI_GATEWAY_API_KEY or ~/.config/vercel/ai_gateway_key.
"""
import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
_lock = threading.Lock()
SPENT = {"usd": 0.0}
CAP = {"usd": float(os.environ.get("TEST_BUDGET_USD", "1.00"))}


class OverBudget(Exception):
    pass


def key():
    return os.environ.get("AI_GATEWAY_API_KEY") or (Path.home() / ".config" / "vercel" / "ai_gateway_key").read_text().strip()


def image_part(url_or_bytes, mime="image/jpeg"):
    if isinstance(url_or_bytes, bytes):
        url_or_bytes = f"data:{mime};base64," + base64.b64encode(url_or_bytes).decode()
    return {"type": "image_url", "image_url": {"url": url_or_bytes}}


def pdf_part(data, name="file.pdf"):
    return {"type": "file", "file": {"filename": name,
                                     "file_data": "data:application/pdf;base64," + base64.b64encode(data).decode()}}


def chat(model, messages, max_tokens=2000, system=None, json_mode=False, attempts=4, timeout=180, extra=None):
    """-> {ok, text, cost, ms, in, out, error}. Never raises except OverBudget."""
    with _lock:
        if SPENT["usd"] >= CAP["usd"]:
            raise OverBudget(f"spent ${SPENT['usd']:.3f} of ${CAP['usd']:.2f}")
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "messages": msgs, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    body.update(extra or {})
    data = json.dumps(body).encode()
    err = None
    for i in range(attempts):
        t = time.time()
        req = urllib.request.Request(URL, data=data, method="POST",
                                     headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"
            if e.code in (408, 429, 500, 502, 503, 504, 529) and i < attempts - 1:
                time.sleep(3 * (i + 1))
                continue
            return {"ok": False, "error": err, "cost": 0.0}
        except (OSError, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            if i < attempts - 1:
                time.sleep(3 * (i + 1))
                continue
            return {"ok": False, "error": err, "cost": 0.0}
        ms = (time.time() - t) * 1000
        u = res.get("usage") or {}
        cost = float(u.get("cost") or 0)
        with _lock:
            SPENT["usd"] += cost
        msg = ((res.get("choices") or [{}])[0].get("message") or {})
        text = msg.get("content") or ""
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        return {"ok": bool(text.strip()), "text": text, "cost": cost, "ms": ms,
                "in": u.get("prompt_tokens"), "out": u.get("completion_tokens"),
                "error": None if text.strip() else "empty reply"}
    return {"ok": False, "error": err, "cost": 0.0}


def parse_json(text):
    """The first JSON object in a reply (models wrap it in prose or fences)."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    for blob in ([m.group(1)] if m else []) + [text[text.find("{"): text.rfind("}") + 1]]:
        try:
            return json.loads(blob)
        except ValueError:
            continue
    return None


def table(rows, cols):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join(out)
