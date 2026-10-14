"""The building page's "Housing legal help nearby" row is home and apartment
law only (owner, 2026-10-14). This reads the regexes straight out of
index.html's isLegalName and checks them against real Apple Maps names from
housing searches near three NYC buildings. The iOS twin is
ios/FindACribTests/NearbyPlacesTests.swift — keep the two lists in step."""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text()


def rx(name):
    m = re.search(r"const %s = /(.+?)/i;" % name, HTML)
    assert m, f"{name} is missing from index.html"
    return re.compile(m.group(1), re.I)


WORD, ORG, HOUSING, NO = rx("LEGAL_WORD"), rx("LEGAL_ORG"), rx("HOUSING_WORD"), rx("LEGAL_NO")


def is_legal(n):
    if NO.search(n) or (re.search("landlord", n, re.I) and not re.search("tenant", n, re.I)):
        return False
    return bool(ORG.search(n) or (HOUSING.search(n) and WORD.search(n)))


KEEP = ["The Legal Aid Society", "Harlem Legal Services", "Bronx Legal Services", "Legal Services NYC",
        "Legal Services for New York", "Brooklyn Legal Services Corporation A", "Mobilization for Justice",
        "Tenant Rights Law Group", "Eviction Defense Attorneys", "Landlord Tenant Law Office of J. Doe"]
DROP = ["The Portela Law Firm, P.C.", "Law Office of Patricia M Machado", "Personal Injury Lawyer Brooklyn",
        "Peter J. Schaffer Bronx Criminal Lawyer", "Commercial Tenant Landlord Lawyer", "Jersey Landlord Lawyer",
        "Landlord & Tenant Consultation Services", "Bronx Housing Court Office", "Neighborhood Defender Service",
        "The Brooklyn District Attorney’s Office", "Tato Legal Services", "Notary Public", "William Tax Solutions",
        "2125 Tenant Association", "Real Estate", "Starbucks Coffee Company"]


def test_keeps_housing_legal_help():
    assert [n for n in KEEP if not is_legal(n)] == []


def test_drops_everything_else():
    assert [n for n in DROP if is_legal(n)] == []


def test_js_filter_matches_this_model():
    # The page's own expression must be the one modelled above.
    assert "!LEGAL_NO.test(n) && !(/landlord/i.test(n) && !/tenant/i.test(n))" in HTML
    assert "(LEGAL_ORG.test(n) || (HOUSING_WORD.test(n) && LEGAL_WORD.test(n)))" in HTML
