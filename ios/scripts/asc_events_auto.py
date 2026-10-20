#!/usr/bin/env python3
"""Keep the App Store's In-App Events filled without anyone remembering to
(owner, 2026-10-17: "do we dynamically update the events section?" — no,
"lets set it up").

Weekly (launchd, scripts/install_events_auto.sh), it:
  1. lays out the events due in the next weeks from a fixed calendar:
     - every month, "<Month> Lottery Deadlines" (Housing Connect never stops);
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
  2. creates each one whose publish date is within HORIZON days, unless an
     event with the same name exists. When another event with the same deep
     link overlaps, the new one starts where that one ends, or is skipped if
     under a week would be left (the hand-made "Fall 2026 lottery deadlines"
     runs Oct 17-Nov 16: October 2026 is skipped, November starts Nov 16);
  3. sends every DRAFT event to App Review in a submission of its own — or,
     when a version's submission is open, leaves them for submit_for_review.py,
     which adds drafts to the next one (Apple allows one open submission).

Apple's rules (developer.apple.com/help/app-store-connect, checked
2026-10-17): an event runs at most 31 days, shows at most 14 days before
it starts, 10 published and 15 approved at a time. Text can't change once
approved, so no counts or prices go in it. The art is the approved
fac-2026-10/event-lotteries card and details (a calendar, no words), reused
for every event so no new art waits on review.

    ~/.venvs/spendcap/bin/python scripts/asc_events_auto.py            # plan only
    ~/.venvs/spendcap/bin/python scripts/asc_events_auto.py --apply    # create + submit
"""
import calendar
import sys
from datetime import date, datetime, timedelta, timezone

from asc_creative_assets import _cfg, call
import asc_app_events

APP = _cfg()["ASC_APP_ID"]
HORIZON = 21           # days ahead to create an event, counted to its publish date
LEAD = 7               # publish this many days before the event starts (Apple: <= 14)
ART = {"card": "fac-2026-10/event-lotteries/card-3840x2160.png",
       "details": "fac-2026-10/event-lotteries/details-2160x3840.png"}
NY_OFFSET = timedelta(hours=-5)   # midnight in New York, near enough across DST


def ny_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - NY_OFFSET


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def month_window(y, m):
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    return start, end


def spec(ref, name, short, long_, link, badge, purpose, start, end, cost="NO_COST_ASSOCIATED"):
    s, e = ny_midnight(start), ny_midnight(end + timedelta(days=1)) - timedelta(minutes=1)
    return {"referenceName": ref, "badge": badge, "purpose": purpose, "priority": "NORMAL",
            "territories": ["USA"], "publishStart": iso(s - timedelta(days=LEAD)),
            "eventStart": iso(s), "eventEnd": iso(e), "deepLink": link,
            "purchaseRequirement": cost,
            "name": name, "shortDescription": short, "longDescription": long_,
            "card": ART["card"], "details": ART["details"]}


def planned(today):
    """Every calendar event starting in the next two months."""
    out = []
    for k in range(0, 3):
        y, m = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
        start, end = month_window(y, m)
        mon = calendar.month_name[m]
        out.append(spec(f"Lottery deadlines {mon} {y}", f"{mon} Lottery Deadlines",
                        "NYC housing lotteries closing this month",
                        f"Every NYC housing lottery closing in {mon}, with its rent, income limits and deadline.",
                        "findacrib://lotteries", "SPECIAL_EVENT", "ATTRACT_NEW_USERS", start, end))
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
                            date(y, 6, 11), date(y, 7, 10), cost="SUBSCRIPTION"))
        if m == 7:
            out.append(spec(f"Lease renewal season {y}", "Lease Renewal Season",
                            "Plan your NYC lease renewal before you sign",
                            "Most NYC leases renew in the fall. Know what your landlord can raise and what to ask for before you sign.",
                            "findacrib://tool/renewal", "SPECIAL_EVENT", "APPROPRIATE_FOR_ALL_USERS", start, end,
                            cost="SUBSCRIPTION"))
    return out


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


def open_submission():
    """The app's open review submission, if any: (id, state)."""
    d = call("GET", f"/v1/reviewSubmissions?filter[app]={APP}&filter[platform]=IOS&limit=20")["data"]
    for r in d:
        st = r["attributes"].get("state")
        if st in ("READY_FOR_REVIEW", "WAITING_FOR_REVIEW", "IN_REVIEW", "UNRESOLVED_ISSUES"):
            return r["id"], st
    return None, None


def submit_drafts(apply):
    drafts = [e for e in call("GET", f"/v1/apps/{APP}/appEvents?limit=200")["data"]
              if e["attributes"].get("eventState") == "DRAFT"]
    if not drafts:
        return
    names = ", ".join(e["attributes"]["referenceName"] for e in drafts)
    sid, st = open_submission()
    if sid:
        # A version (or another event) is already with App Review; Apple
        # allows one open submission, and submit_for_review.py adds drafts
        # to the next one. Re-checked next week.
        print(f"wait     {names}: submission {sid[:8]} is {st}")
        return
    if not apply:
        print(f"would submit {names}")
        return
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
        if parse(s["eventEnd"]) - max(parse(s["eventStart"]), today) < timedelta(days=14):
            continue   # over, or too little left to be worth a review (added 2026-10-20)
        if pub - today > timedelta(days=HORIZON):
            print(f"later    {s['referenceName']} (publishes {pub:%b %d})")
            continue
        if (until := covered_until(s, existing)):
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
