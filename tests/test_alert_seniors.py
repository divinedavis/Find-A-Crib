"""lottery_alerts senior-only filter (owner, 2026-10-06: alerted about Luna
Green, an HCR development for heads of household 62 or older)."""
import lottery_alerts as L

LUNA = {"id": "a0Y", "status": "Open", "ptype": "Rental", "boro": "Bk", "name": "Luna Green", "senior": True,
        "info": "Luna Green is a senior housing development. To qualify, the head of household "
                "or co-head of household must be 62 years of age or older."}
BAEZ = {"id": "b0Y", "status": "Open", "ptype": "Rental", "boro": "Bx", "name": "Baez Place", "senior": True,
        "desc": "There are 4 units at 80% AMI that are not senior specific units."}
SUB = {"email": "a@b.c", "kinds": ["lottery", "rerental"], "boroughs": ["Bk", "Bx"]}


def test_senior_only_lottery_skips_people_who_did_not_say_62_plus():
    item = L.hcr_items({"listings": [LUNA]})[0]
    assert item["senior_only"]
    assert not L.wants(SUB, item)
    assert L.wants(dict(SUB, seniors=True), item)


def test_mixed_senior_building_still_goes_to_everyone():
    item = L.hcr_items({"listings": [BAEZ]})[0]
    assert not item["senior_only"]
    assert L.wants(SUB, item)


def test_unflagged_lottery_unchanged():
    item = L.hcr_items({"listings": [dict(LUNA, senior=False)]})[0]
    assert L.wants(SUB, item)
