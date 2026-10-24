#!/usr/bin/env python3
"""Keep the App Store's In-App Events filled without anyone remembering to
(owner, 2026-10-17: "do we dynamically update the events section?" — no,
"lets set it up").

Weekly (launchd, scripts/install_events_auto.sh), it:
  1. lays out the events due in the next weeks from a fixed calendar:
     - NO monthly "<Month> Lottery Deadlines": App Review rejected November
       2026's under 2.3.13 (2026-10-20, "does not introduce new features or
       content, or recurs too frequently"). Every event must be a yearly
       moment that changes something for renters;
     - every June, the Rent Guidelines Board vote;
     - every October, heat season;
     NYC housing calendar added 2026-10-20 (owner: "lets do these"):
     - December, landlords' annual bedbug filing (HPD, Local Law 69);
     - January, the lead paint / window guard notice (due back Feb 15),
       into the repair tool, which covers peeling paint and window guards;
     - May, the Rent Guidelines Board's preliminary vote;
     - June 11 - July 10, moving season under the FARE Act (Broker fee check,
       findacrib://broker-fee, Plus);
     - July, lease renewal season (Renewal coach, Plus);
     - October, the new rent guidelines take effect (Oct 1);
     Holidays (owner 2026-10-24: Halloween and Thanksgiving first, then
     "make sure it has an event for all events"): every day in
     holidays.json, from HOLIDAY_EVENTS, each opening a real tool with the
     day as the reason (the holiday looks alone would invite 2.3.13).
     Holiday events may be short (min_left) and may overlap another event
     with the same link;
  2. creates each one whose publish date is within HORIZON days, unless an
     event with the same name exists. When another event with the same deep
     link overlaps, the new one starts where that one ends, or is skipped if
     under a week would be left (the hand-made "Fall 2026 lottery deadlines"
     runs Oct 17-Nov 16: October 2026 is skipped, November starts Nov 16);
  3. sends every DRAFT event to App Review in a submission of its own. Events
     never ride with a version: a rejected event holds an accepted version
     back from release until it is removed (1.3.3, Oct 2026).

Apple's rules (developer.apple.com/help/app-store-connect, checked
2026-10-17): an event runs at most 31 days, shows at most 14 days before
it starts, 10 published and 15 approved at a time. Text can't change once
approved, so no counts or prices go in it. The art is the approved
fac-2026-10/event-lotteries card and details (a calendar, no words), reused
for every event so no new art waits on review. Since 2026-10-24 the art
is the logo art instead (see art()); run upload_event_art.py for a new look.

    ~/.venvs/spendcap/bin/python scripts/asc_events_auto.py            # plan only
    ~/.venvs/spendcap/bin/python scripts/asc_events_auto.py --apply    # create + submit
"""
import calendar
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from asc_creative_assets import _cfg, call
import asc_app_events

APP = _cfg()["ASC_APP_ID"]
HORIZON = 21           # days ahead to create an event, counted to its publish date
LEAD = 7               # publish this many days before the event starts (Apple: <= 14)
# The real logo, large, on every card and details page (owner, 2026-10-24:
# "we should always have our logo on the event card and event details").
# upload_event_art.py renders and uploads each look once; holidays wear
# their day's colours, the rest the everyday teal.


def art(look="everyday"):
    """Everyday events: the real logo on teal. Holidays: that day's holiday
    icon on its colours (owner 2026-10-24, "use the event logo/icons")."""
    base = "fac-events-logo/everyday" if look == "everyday" else f"fac-events-icon/{look}"
    return {"card": f"{base}/card-3840x2160.png", "details": f"{base}/details-2160x3840.png"}
NY_OFFSET = timedelta(hours=-5)   # midnight in New York, near enough across DST


def ny_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - NY_OFFSET


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def month_window(y, m):
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    return start, end


def thanksgiving(y):
    """The fourth Thursday of November."""
    first = date(y, 11, 1)
    return first + timedelta(days=(3 - first.weekday()) % 7 + 21)


def spec(ref, name, short, long_, link, badge, purpose, start, end, cost="NO_COST_ASSOCIATED", min_left=14, look="everyday"):
    assert len(name) <= 30 and len(short) <= 50 and len(long_) <= 120, ref
    s, e = ny_midnight(start), ny_midnight(end + timedelta(days=1)) - timedelta(minutes=1)
    return {"referenceName": ref, "badge": badge, "purpose": purpose, "priority": "NORMAL",
            "territories": ["USA"], "publishStart": iso(s - timedelta(days=LEAD)),
            "eventStart": iso(s), "eventEnd": iso(e), "deepLink": link,
            "purchaseRequirement": cost,
            "name": name, "shortDescription": short, "longDescription": long_,
            **art(look), "min_left": min_left}


# Every holiday in holidays.json gets an event (owner, 2026-10-24: "make
# sure it has an event for all events"), each opening a real tool with the
# day as the reason, never the colours alone (2.3.13). Windows follow
# Marracat's events. id: (name, short, long, deep link, from, to, cost)
P = "IN_APP_PURCHASE"   # Plus; Apple 409s "SUBSCRIPTION" (no longer supported, 10/24)
RIGHTS = "A plain-language guide to your rights as a New York renter, from repairs and heat to rent increases."
HOLIDAY_EVENTS = {
    "halloween": ("Is Your Building Haunted?", "See a building's violations and complaints",
                  "Strange noises, no heat, pests? Look up any NYC building's HPD violations and complaints before you sign.",
                  "findacrib://search", -6, 0, None),
    "veterans": ("Veterans: Use Your Voucher", "Find buildings that take housing vouchers",
                 "HUD-VASH and Section 8 holders: find NYC buildings that take vouchers, with their violations and rent.",
                 "findacrib://search", -3, 0, None),
    "thanksgiving": ("Hosting? Get the Heat On", "NYC landlords must heat your home through May",
                     "Cold apartment before guests arrive? NYC landlords must provide heat. Get a repair letter and file with 311.",
                     "findacrib://tool/repair", -6, 3, None),
    "black-friday": ("The Best Deal: A Fair Rent", "Find rent-stabilized buildings near you",
                     "Skip the doorbusters. See which NYC buildings are rent stabilized, with their violations and rent.",
                     "findacrib://search", 0, 2, None),
    "cyber-monday": ("Apply From Your Couch", "Housing lotteries open now",
                     "See every open NYC housing lottery, check if your income qualifies and set alerts for new ones.",
                     "findacrib://lotteries", 0, 1, None),
    "gift-guide": ("Gift Yourself a Fair Lease", "Check a broker fee or your lease before you sign",
                   "Broker fee check and Lease review look over a listing's fee and your lease before you sign.",
                   "findacrib://broker-fee", 0, 28, P),
    "christmas": ("Home for the Holidays", "Housing lotteries open over the holidays",
                  "Housing lotteries stay open over the holidays. See which ones you qualify for and set an alert.",
                  "findacrib://lotteries", -6, 0, None),
    "kwanzaa": ("Happy Kwanzaa", "See what's happening on your block",
                "Ujamaa starts at home. See 311 complaints and crime reported near your building in Your Crib.",
                "findacrib://casa", 0, 4, None),
    "watch-night": ("Freedom's Eve", "Know your rights as a NYC renter",
                    "Watch Night, Freedom's Eve: a plain-language guide to your rights as a New York renter.",
                    "findacrib://tool/rights", -1, 0, None),
    "new-year": ("New Year, New Lease", "Check your renewal before you sign",
                 "The Renewal coach checks a lease renewal against the Rent Guidelines Board's increases before you sign.",
                 "findacrib://tool/renewal", 0, 6, P),
    "mlk": ("Fair Housing Is a Right", "Know your rights as a NYC renter", RIGHTS, "findacrib://tool/rights", -3, 0, None),
    "bhm": ("Black History Month", "Know your rights as a renter",
            "Fair housing was won, not given. A plain-language guide to your rights as a New York renter.",
            "findacrib://tool/rights", 0, 27, None),
    "presidents": ("Long Weekend, No Heat?", "NYC landlords must heat your home through May",
                   "Cold apartment on the long weekend? NYC landlords must provide heat. Get a repair letter and file with 311.",
                   "findacrib://tool/repair", -3, 0, None),
    "emancipation": ("DC Emancipation Day", "Look up a DC building's rent record",
                     "DC renters: see a building's rent registry record and estimated rent before you sign a lease.",
                     "findacrib://search", -3, 0, None),
    "malcolm-x": ("Malcolm X Day", "Find rent-stabilized homes near you",
                  "Remembering Malcolm X. See which NYC buildings are rent stabilized, with their violations and rent.",
                  "findacrib://search", -3, 0, None),
    "ald": ("African Liberation Day", "Know your rights as a renter", RIGHTS, "findacrib://tool/rights", -3, 0, None),
    "memorial": ("Moving This Summer?", "Check a building before you sign a lease",
                 "Moving season is near. Look up any NYC building's violations, complaints and rent before you sign.",
                 "findacrib://search", -3, 0, None),
    "juneteenth": ("Juneteenth", "Know your rights as a renter",
                   "Freedom includes a fair home. A plain-language guide to your rights as a New York renter.",
                   "findacrib://tool/rights", -6, 0, None),
    "july4": ("Independence From Broker Fees", "The landlord's agent can't bill you in NYC",
              "Under the FARE Act, a landlord's broker can't charge NYC renters. Check a fee you were asked to pay.",
              "findacrib://broker-fee", -3, 0, P),
    "labor": ("Labor Day: Know Your Rights", "Repairs, heat and rent increases, explained", RIGHTS,
              "findacrib://tool/rights", -3, 0, None),
    "indigenous": ("Indigenous Peoples' Day", "Check this year's legal rent increase",
                   "New rent guidelines took effect Oct 1. Check whether your stabilized lease increase is legal.",
                   "findacrib://tool/rent-increase", -3, 0, None),
}
# holidays.json: next to this script in the launchd copy, else in the app.
HOLIDAYS_JSON = next(p for p in (Path(__file__).with_name("holidays.json"),
                                 Path(__file__).resolve().parent.parent / "FindACrib/Resources/holidays.json") if p.exists())


def holiday_day(h, y):
    """A holiday's date in year y: a fixed day, or the nth (-1 = last) ISO
    weekday of the month, plus an offset (Black Friday = Thanksgiving + 1)."""
    r = h["date"]
    if "day" in r:
        return date(y, r["month"], r["day"])
    days = [date(y, r["month"], d) for d in range(1, calendar.monthrange(y, r["month"])[1] + 1)
            if date(y, r["month"], d).isoweekday() == r["weekday"]]
    return days[r["nth"] - 1 if r["nth"] > 0 else r["nth"]] + timedelta(days=r.get("offset", 0))


def holiday_specs(today):
    out = []
    for h in json.loads(HOLIDAYS_JSON.read_text())["holidays"]:
        name, short, long_, link, a, b, cost = HOLIDAY_EVENTS[h["id"]]
        for y in (today.year, today.year + 1):
            day = holiday_day(h, y)
            start, end = day + timedelta(days=a), day + timedelta(days=b)
            if end < today or start > today + timedelta(days=120):
                continue
            s = spec(f"{h['name']} {day.year}", name, short, long_, link, "SPECIAL_EVENT",
                     "APPROPRIATE_FOR_ALL_USERS", start, end, cost=cost or "NO_COST_ASSOCIATED",
                     min_left=1, look=h["id"])
            s["holiday"] = True
            out.append(s)
    return out


def planned(today):
    """Every calendar event starting in the next two months."""
    out = []
    for k in range(0, 3):
        y, m = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
        start, end = month_window(y, m)
        if m == 6:
            out.append(spec(f"Rent Guidelines vote {y}", "Rent Guidelines Vote",
                            "What NYC's vote means for your lease",
                            "NYC's Rent Guidelines Board votes on rent-stabilized increases. See how much your renewal can legally go up.",
                            "findacrib://tool/rent-increase", "SPECIAL_EVENT", "APPROPRIATE_FOR_ALL_USERS", start, end))
        if m == 10:
            out.append(spec(f"Heat season {y}", "Heat Season: Get Heat Fixed",
                            "NYC landlords must keep your apartment warm",
                            "Oct 1 to May 31, NYC landlords must provide heat. No heat? Get a repair letter and file with 311 in minutes.",
                            "findacrib://tool/repair", "NEW_SEASON", "APPROPRIATE_FOR_ALL_USERS", start, end))
            out.append(spec(f"New rent guidelines {y}", "New Rent Guidelines Begin",
                            "NYC's new stabilized rent increases start Oct 1",
                            "From Oct 1, the Rent Guidelines Board's new increases apply to stabilized leases. Check if yours is legal.",
                            "findacrib://tool/rent-increase", "SPECIAL_EVENT", "APPROPRIATE_FOR_ALL_USERS", start, end))
        if m == 12:
            # HPD: owners file the annual bedbug report Dec 1-31 (nyc.gov/hpd bedbugs).
            out.append(spec(f"Bedbug reports {y}", "Bedbug Reports Are Due",
                            "NYC landlords report bedbugs every December",
                            "Every December, NYC landlords report bedbugs to the City. Check your building's bedbug and pest record.",
                            "findacrib://casa", "SPECIAL_EVENT", "APPROPRIATE_FOR_ALL_USERS", start, end))
        if m == 1:
            # NYC Health: notice delivered Jan 1-15, tenants return it by Feb 15.
            out.append(spec(f"Lead and window guard notice {y}", "Lead & Window Guard Notices",
                            "Your landlord's yearly NYC safety notice is due",
                            "NYC landlords must ask each January about kids, lead paint and window guards. Missing either? Get a repair letter.",
                            "findacrib://tool/repair", "SPECIAL_EVENT", "APPROPRIATE_FOR_ALL_USERS", start, end))
        if m == 5:
            out.append(spec(f"Rent Guidelines first vote {y}", "Rent Guidelines First Vote",
                            "NYC's first vote on stabilized rent increases",
                            "NYC's Rent Guidelines Board takes its first vote on stabilized increases. See what it could mean for you.",
                            "findacrib://tool/rent-increase", "SPECIAL_EVENT", "APPROPRIATE_FOR_ALL_USERS", start, end))
        if m == 6:
            # The FARE Act took effect June 11, 2025 (NYC DCWP).
            out.append(spec(f"Moving season broker fees {y}", "Moving? Skip the Broker Fee",
                            "FARE Act: the landlord's agent can't bill you",
                            "Since June 2025, a landlord's broker can't charge NYC renters a fee. Check a fee you were asked to pay.",
                            "findacrib://broker-fee", "SPECIAL_EVENT", "ATTRACT_NEW_USERS",
                            date(y, 6, 11), date(y, 7, 10), cost=P))
        if m == 7:
            out.append(spec(f"Lease renewal season {y}", "Lease Renewal Season",
                            "Plan your NYC lease renewal before you sign",
                            "Most NYC leases renew in the fall. Know what your landlord can raise and what to ask for before you sign.",
                            "findacrib://tool/renewal", "SPECIAL_EVENT", "APPROPRIATE_FOR_ALL_USERS", start, end,
                            cost=P))
    return out + holiday_specs(today)


def parse(t):
    return datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def covered_until(s, existing):
    """The latest end of any live, approved or draft event with the same deep
    link that overlaps this one, or None: the new event starts after it, so
    two lottery events never run side by side."""
    a, b = parse(s["eventStart"]), parse(s["eventEnd"])
    ends = [parse(t["eventEnd"]) for ev in existing
            if ev["attributes"].get("deepLink") == s["deepLink"]
            and ev["attributes"].get("eventState") not in ("ARCHIVED", "REJECTED")
            for t in ev["attributes"].get("territorySchedules") or []
            if parse(t["eventStart"]) < b and parse(t["eventEnd"]) > a]
    return max(ends) if ends else None


def submit_drafts(apply):
    drafts = [e for e in call("GET", f"/v1/apps/{APP}/appEvents?limit=200")["data"]
              if e["attributes"].get("eventState") == "DRAFT"]
    if not drafts:
        return
    names = ", ".join(e["attributes"]["referenceName"] for e in drafts)
    # No waiting on another open submission: on 2026-10-24 Apple took 1.3.5's
    # submission while an events one was WAITING_FOR_REVIEW, so the two run
    # side by side and events never queue behind a version's review.
    if not apply:
        print(f"would submit {names}")
        return
    # Apple 409s a draft whose publish or start date has passed
    # (TERRITORY_SCHEDULES_DATES_IN_PAST), e.g. one pulled back from review.
    soon = datetime.now(timezone.utc) + timedelta(hours=2)
    for e in drafts:
        ts = e["attributes"].get("territorySchedules") or []
        if any(parse(t[k]) < soon for t in ts for k in ("publishStart", "eventStart")):
            ts = [{**t, **{k: iso(soon) for k in ("publishStart", "eventStart") if parse(t[k]) < soon}} for t in ts]
            call("PATCH", f"/v1/appEvents/{e['id']}", {"data": {"type": "appEvents", "id": e["id"],
                 "attributes": {"territorySchedules": ts}}})
            print(f"moved    {e['attributes']['referenceName']} to start showing {iso(soon)}")
    sub = call("POST", "/v1/reviewSubmissions", {"data": {"type": "reviewSubmissions",
               "attributes": {"platform": "IOS"},
               "relationships": {"app": {"data": {"type": "apps", "id": APP}}}}})["data"]
    for e in drafts:
        call("POST", "/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
            "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}},
            "appEvent": {"data": {"type": "appEvents", "id": e["id"]}}}}})
    d = call("PATCH", f"/v1/reviewSubmissions/{sub['id']}", {"data": {"type": "reviewSubmissions", "id": sub["id"],
             "attributes": {"submitted": True}}})["data"]
    print(f"submitted {names} as {sub['id'][:8]} ({d['attributes'].get('state')})")


def main():
    apply = "--apply" in sys.argv
    today = datetime.now(timezone.utc)
    print(f"==> {today:%Y-%m-%d %H:%M} UTC ({'apply' if apply else 'plan only'})")
    existing = call("GET", f"/v1/apps/{APP}/appEvents?limit=200")["data"]
    names = {e["attributes"]["referenceName"] for e in existing}
    for s in planned(today.date()):
        pub = parse(s["publishStart"])
        if s["referenceName"] in names:
            continue
        holiday = s.pop("holiday", False)
        if parse(s["eventEnd"]) - max(parse(s["eventStart"]), today) < timedelta(days=s.pop("min_left")):
            continue   # over, or too little left to be worth a review (added 2026-10-20)
        if pub - today > timedelta(days=HORIZON):
            print(f"later    {s['referenceName']} (publishes {pub:%b %d})")
            continue
        # Holidays may overlap an event with the same link: each is its own day.
        if not holiday and (until := covered_until(s, existing)):
            if parse(s["eventEnd"]) - until < timedelta(days=7):
                print(f"covered  {s['referenceName']} (another event runs to {until:%b %d})")
                continue
            # Pick up where the other one ends.
            s["eventStart"] = iso(until + timedelta(minutes=1))
            s["publishStart"] = iso(until + timedelta(minutes=1) - timedelta(days=LEAD))
        if not apply:
            print(f"would create {s['referenceName']}: {s['eventStart'][:10]} to {s['eventEnd'][:10]}, shows from {s['publishStart'][:10]}")
            continue
        # A start already past (a missed week): begin now, keep the end.
        if parse(s["eventStart"]) < today:
            s["eventStart"] = iso(today + timedelta(hours=1))
        if parse(s["publishStart"]) < today:
            s["publishStart"] = iso(today + timedelta(hours=1))
        asc_app_events.create(APP, s)
    submit_drafts(apply)


if __name__ == "__main__":
    main()
