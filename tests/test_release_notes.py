"""App Store release notes become paragraphs with a blank line between them
(ios/scripts/release_notes.py; owner, 2026-10-31)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/scripts"))
from release_notes import as_paragraphs  # noqa: E402


def test_bullets_become_paragraphs():
    notes = "• Building chat, redesigned.\n• Crime alerts near your building are free.\n- Faster maps."
    assert as_paragraphs(notes) == ("Building chat, redesigned.\n\n"
                                    "Crime alerts near your building are free.\n\nFaster maps.")


def test_paragraphs_and_hyphens_are_left_alone():
    assert as_paragraphs("One.\n\nTwo.") == "One.\n\nTwo."
    assert as_paragraphs("Rent-stabilized, -10%.") == "Rent-stabilized, -10%."
    assert as_paragraphs("") == "" and as_paragraphs(None) is None
