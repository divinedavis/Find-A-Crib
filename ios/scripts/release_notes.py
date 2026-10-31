"""App Store release notes ("What's New") as short paragraphs with a blank line
between them, never bullets (owner, 2026-10-31: "lets use line breaks with a
space in between the sentences instead of bullets ... do this for all our
apps"). Write the notes that way; this turns any bullet lines that slip
through into paragraphs before they reach App Store Connect."""
import re

_BULLET = re.compile(r"^[•●▪◦·\-\*–]\s+")


def as_paragraphs(text):
    if not text:
        return text
    lines = (line.strip() for line in str(text).replace("\r\n", "\n").split("\n"))
    return "\n\n".join(_BULLET.sub("", line) for line in lines if line)
