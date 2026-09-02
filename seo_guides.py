"""
Cornerstone SEO guide content for Find A Crib.

Editorial pages that target the high-intent informational queries around rent
regulation ("is my apartment rent stabilized", "how to find a rent stabilized
apartment", "rent stabilized vs rent controlled", tenant rights, lease renewal).
These build topical authority and internally link to the ~47k data pages.
build_seo.py renders each into /guide/<slug>/ plus a /guide/ hub.

Each guide declares a `city`. Until 2026-07-29 every guide was NYC, which left
San Francisco, Los Angeles and Washington DC — three of the four cities in the
dataset, and 42 of the 97 tracked queries — with no explanatory page at all;
their "explain" and "check" queries pointed at the city map, which is a listings
UI and cannot answer them. The city field also drives internal linking: related
links stay inside a city rather than sending an SF reader to six NYC pages.

Accuracy: content sticks to well-established, durable facts and links out to the
authoritative sources (DHCR/HCR, the Rent Guidelines Board, HPD, the SF Rent
Board, LAHD, DC's Rental Accommodations Division, tenant resources) for anything
that changes year to year (e.g. the annual RGB order, the AB 1482 CPI figure).
Guides never overstate what this site's own data proves — the SF layer is
anonymized to the block and the LA layer is derived from assessor criteria, and
both guides say so. Guides are informational, not legal advice.
"""

# Reusable snippets ----------------------------------------------------------
TOOL_CTA = (
    "<a class='cta' href='/'>🔎 Check any building on the Find A Crib map →</a>"
)
TOOL_CTA_SF = (
    "<a class='cta' href='/sf/'>🔎 Open the San Francisco rent-control map →</a>"
)
TOOL_CTA_LA = (
    "<a class='cta' href='/la/'>🔎 Open the Los Angeles RSO map →</a>"
)
TOOL_CTA_DC = (
    "<a class='cta' href='/dc/'>🔎 Open the Washington DC rent-control map →</a>"
)

SOURCES = (
    "<h2>Official sources</h2>"
    "<ul>"
    "<li><a href='https://hcr.ny.gov/rent-regulation' rel='nofollow noopener' target='_blank'>"
    "NYS Homes and Community Renewal (HCR/DHCR) — Rent Regulation</a></li>"
    "<li><a href='https://rentguidelinesboard.cityofnewyork.us/' rel='nofollow noopener' target='_blank'>"
    "NYC Rent Guidelines Board — current annual increase orders</a></li>"
    "<li><a href='https://www.nyc.gov/site/hpd/index.page' rel='nofollow noopener' target='_blank'>"
    "NYC Department of Housing Preservation &amp; Development (HPD)</a></li>"
    "<li><a href='https://www.metcouncilonhousing.org/' rel='nofollow noopener' target='_blank'>"
    "Met Council on Housing — tenant help</a></li>"
    "</ul>"
    "<p class='disclaimer'>Find A Crib is an informational tool, not a law firm. "
    "This guide is general information about NYC rent stabilization, not legal advice. "
    "For your specific situation, contact DHCR or a tenant attorney/legal-aid group.</p>"
)

SOURCES_SF = (
    "<h2>Official sources</h2>"
    "<ul>"
    "<li><a href='https://www.sf.gov/departments--rent-board' rel='nofollow noopener' target='_blank'>"
    "San Francisco Rent Board</a> — counselling, petitions, and the current annual allowable increase</li>"
    "<li><a href='https://www.sfrb.org/' rel='nofollow noopener' target='_blank'>"
    "sfrb.org — Rent Board fact sheets and forms</a></li>"
    "<li><a href='https://sfplanninggis.org/pim/' rel='nofollow noopener' target='_blank'>"
    "SF Property Information Map</a> — building records by address</li>"
    "<li><a href='https://sftu.org/' rel='nofollow noopener' target='_blank'>"
    "San Francisco Tenants Union</a> — tenant counselling</li>"
    "</ul>"
    "<p class='disclaimer'>Find A Crib is an informational tool, not a law firm. "
    "This guide is general information about the San Francisco Rent Ordinance and California state law, "
    "not legal advice. For your specific situation, contact the Rent Board or a tenant attorney/legal-aid group.</p>"
)

SOURCES_LA = (
    "<h2>Official sources</h2>"
    "<ul>"
    "<li><a href='https://housing.lacity.gov/residents/rso-overview' rel='nofollow noopener' target='_blank'>"
    "LAHD — Rent Stabilization Ordinance overview</a></li>"
    "<li><a href='https://housing.lacity.gov/residents/is-my-rental-unit-subject-to-the-rent-stabilization-ordinance' "
    "rel='nofollow noopener' target='_blank'>LAHD — Is my rental unit subject to the RSO?</a></li>"
    "<li><a href='https://housing.lacity.gov/residents/ab-1482' rel='nofollow noopener' target='_blank'>"
    "LAHD — AB 1482 (California statewide rent cap)</a></li>"
    "<li><a href='https://www.ladbs.org/' rel='nofollow noopener' target='_blank'>"
    "LA Department of Building and Safety</a> — certificate of occupancy records</li>"
    "</ul>"
    "<p class='disclaimer'>Find A Crib is an informational tool, not a law firm. "
    "This guide is general information about the Los Angeles RSO and California state law, not legal advice. "
    "For your specific situation, contact LAHD or a tenant attorney/legal-aid group.</p>"
)

SOURCES_DC = (
    "<h2>Official sources</h2>"
    "<ul>"
    "<li><a href='https://dhcd.dc.gov/rentcontrol' rel='nofollow noopener' target='_blank'>"
    "DC DHCD — Rent control (rent stabilization)</a></li>"
    "<li><a href='https://rentregistry.dc.gov/' rel='nofollow noopener' target='_blank'>"
    "DC Rent Registry</a></li>"
    "<li><a href='https://code.dccouncil.gov/us/dc/council/code/sections/42-3502.05' "
    "rel='nofollow noopener' target='_blank'>D.C. Code § 42-3502.05 — registration and coverage</a></li>"
    "<li><a href='https://ota.dc.gov/' rel='nofollow noopener' target='_blank'>"
    "DC Office of the Tenant Advocate</a> — free tenant advice</li>"
    "</ul>"
    "<p class='disclaimer'>Find A Crib is an informational tool, not a law firm. "
    "This guide is general information about the DC Rental Housing Act, not legal advice. "
    "For your specific situation, contact the Rental Accommodations Division, the Office of the Tenant Advocate, "
    "or a tenant attorney/legal-aid group.</p>"
)


def _related(current, guides):
    """Related links, city-first.

    A San Francisco reader is not served by six New York links, and sending
    every guide's link equity to every other guide flattens the topical signal
    the city clusters are there to create. So: every other guide in the same
    city, then one entry point per other city.
    """
    here = next((g for g in guides if g["slug"] == current), None)
    city = (here or {}).get("city", "nyc")

    same = [g for g in guides if g.get("city", "nyc") == city and g["slug"] != current]
    other, seen = [], {city}
    for g in guides:
        c = g.get("city", "nyc")
        if c not in seen:
            seen.add(c)
            other.append(g)

    def _links(items):
        return "".join(f"<a href='/guide/{g['slug']}/'>{g['h1']}</a>" for g in items)

    html = ""
    if same:
        html += f"<h2>Related guides</h2><div class='cols'>{_links(same)}</div>"
    if other:
        # A city with only one guide gets no empty "Related guides" box — the
        # other-city links are the related guides in that case.
        heading = "Other cities" if same else "Guides for other cities"
        html += f"<h2>{heading}</h2><div class='cols'>{_links(other)}</div>"
    return html


# The guides (order = hub display order) -------------------------------------
GUIDES = [
    {
        "city": "nyc",
        "slug": "is-my-apartment-rent-stabilized",
        "title": "Is My Apartment Rent Stabilized? How to Check (NYC)",
        "desc": "Four free ways to find out if your NYC apartment is rent stabilized — "
                "request your DHCR rent history, check the building, read your lease, and look it up on the map.",
        "h1": "Is my apartment rent stabilized?",
        "body": (
            "<p class='lead'>If your building was built before 1974 and has six or more apartments, "
            "there is a good chance your unit is rent stabilized — but the only way to know for certain is to check. "
            "Here are four free ways to find out, from fastest to most authoritative.</p>"

            "<h2>1. Look up the building</h2>"
            "<p>Rent stabilization is tied to the building, so the fastest first check is the building itself. "
            "Find A Crib maps every building that appears in the NYS DHCR rent-stabilized building registration files. "
            "Search your address — if it is listed, the building has registered stabilized units with the state.</p>"
            + TOOL_CTA +
            "<p>Being on the list means the <em>building</em> registers stabilized units; it does not by itself prove "
            "that <em>your specific unit</em> is stabilized today, which is why step 2 matters.</p>"

            "<h2>2. Request your rent history from DHCR (the definitive answer)</h2>"
            "<p>Every tenant has the right to request the official <strong>rent history</strong> for their apartment "
            "from NYS Homes and Community Renewal (HCR/DHCR), free of charge. The rent history shows the registered "
            "rent for each year and whether the unit has been registered as rent stabilized. This is the authoritative "
            "record. You can request it online through the "
            "<a href='https://hcr.ny.gov/rent-regulation' rel='nofollow noopener' target='_blank'>HCR rent-regulation portal</a> "
            "or by contacting DHCR directly. It typically arrives within a few weeks.</p>"

            "<h2>3. Read your lease</h2>"
            "<p>A rent-stabilized lease must include a <strong>Rent Stabilization Rider</strong> (in English and Spanish) "
            "explaining your rights, and renewals come on a DHCR renewal-lease form (RTP-8). If your lease has that rider "
            "or you receive an official renewal offer with 1- and 2-year options at a set percentage, your unit is almost "
            "certainly stabilized. The absence of a rider is not proof it is unregulated, though — some owners fail to "
            "provide required paperwork.</p>"

            "<h2>4. Look for the signs of coverage</h2>"
            "<p>Your apartment is more likely to be rent stabilized if:</p>"
            "<ul>"
            "<li>The building was <strong>built before January 1, 1974</strong> and has <strong>six or more units</strong>.</li>"
            "<li>The building received a tax benefit such as <strong>421-a</strong> or <strong>J-51</strong> "
            "(these can bring newer buildings into stabilization for the benefit period).</li>"
            "<li>You were offered a lease <strong>renewal</strong> rather than being asked to sign a brand-new market lease each year.</li>"
            "</ul>"
            "<p>Rent stabilization covers roughly one million apartments — the single largest source of below-market "
            "housing in New York City — so this is well worth checking before you sign or renew.</p>"

            "<h2>What if I think my rent is illegal?</h2>"
            "<p>If your rent history shows a large, unexplained jump, or you were never offered a stabilized lease you "
            "should have been, you may have an <strong>overcharge</strong> claim. Bring your rent history to a tenant "
            "attorney or a legal-aid group — do not rely on this page for a legal determination.</p>"
            + SOURCES
        ),
    },
    {
        "city": "nyc",
        "slug": "what-is-rent-stabilization",
        "title": "What Is Rent Stabilization in NYC? A Plain-English Guide",
        "desc": "Rent stabilization limits how much your rent can rise and gives you the right to renew your lease. "
                "Learn what it is, which NYC buildings are covered, and how it protects tenants.",
        "h1": "What is rent stabilization in NYC?",
        "body": (
            "<p class='lead'>Rent stabilization is New York City's largest tenant-protection program. "
            "It caps how much your rent can increase each year and gives you the right to renew your lease, "
            "covering roughly one million apartments across the five boroughs.</p>"

            "<h2>The basics</h2>"
            "<p>Rent stabilization is administered by New York State Homes and Community Renewal (HCR), through its "
            "Division of Housing and Community Renewal (DHCR). If your apartment is stabilized, three things are true:</p>"
            "<ul>"
            "<li><strong>Limited increases.</strong> The NYC Rent Guidelines Board (RGB) sets the maximum percentage your "
            "rent can rise on a 1-year or 2-year renewal, once per year. An owner cannot raise a stabilized rent above that.</li>"
            "<li><strong>Right to renew.</strong> Your landlord generally must offer you a lease renewal and cannot evict "
            "you simply to charge more. You choose a 1-year or 2-year term.</li>"
            "<li><strong>Succession &amp; services.</strong> Certain family members can take over the lease, and the owner "
            "must maintain the same services (heat, hot water, repairs).</li>"
            "</ul>"

            "<h2>Which buildings are covered?</h2>"
            "<p>The most common way an apartment becomes rent stabilized is the building's age and size: "
            "<strong>buildings built before January 1, 1974 with six or more units</strong> are generally covered. "
            "Buildings that received tax incentives like <strong>421-a</strong> or <strong>J-51</strong> can also be "
            "stabilized for the length of the benefit. Rent stabilization exists in all five boroughs, not just Manhattan.</p>"
            "<p>You can browse the registered buildings by borough:</p>"
            "<div class='cols'>"
            "<a href='/borough/manhattan/'>Manhattan rent-stabilized buildings</a>"
            "<a href='/borough/brooklyn/'>Brooklyn rent-stabilized buildings</a>"
            "<a href='/borough/queens/'>Queens rent-stabilized buildings</a>"
            "<a href='/borough/bronx/'>Bronx rent-stabilized buildings</a>"
            "<a href='/borough/staten-island/'>Staten Island rent-stabilized buildings</a>"
            "</div>"

            "<h2>How much can the rent go up?</h2>"
            "<p>The Rent Guidelines Board votes each June on the increases that apply to renewal leases beginning that "
            "October through the following September. Because the number changes every year, always check the "
            "<a href='https://rentguidelinesboard.cityofnewyork.us/' rel='nofollow noopener' target='_blank'>current RGB order</a> "
            "rather than assuming last year's figure.</p>"

            "<h2>Why the 2019 law matters</h2>"
            "<p>The <strong>Housing Stability and Tenant Protection Act of 2019 (HSTPA)</strong> substantially strengthened "
            "rent stabilization. It ended the practice of deregulating apartments once the rent crossed a high threshold, "
            "eliminated the automatic vacancy increase, and tightened the rules on how owners can raise rents after "
            "renovations. In practice, far fewer apartments leave stabilization than before.</p>"

            "<h2>Check a specific building</h2>"
            "<p>Rent stabilization is building-specific, so the practical next step is to look up an address.</p>"
            + TOOL_CTA + SOURCES
        ),
    },
    {
        "city": "nyc",
        "slug": "rent-stabilized-vs-rent-controlled",
        "title": "Rent Stabilized vs. Rent Controlled: What's the Difference?",
        "desc": "Rent control and rent stabilization are not the same thing. Learn how they differ in NYC, "
                "which is far more common, and how to tell which one (if any) applies to your apartment.",
        "h1": "Rent stabilized vs. rent controlled",
        "body": (
            "<p class='lead'>People use \"rent controlled\" as a catch-all, but in New York City it is a specific, rare "
            "status that is different from rent stabilization. Here is how the two compare.</p>"

            "<h2>The short version</h2>"
            "<table class='facts'>"
            "<tr><td class='k'>Rent stabilization</td><td>Roughly <strong>one million</strong> apartments. "
            "Generally pre-1974 buildings with 6+ units. Annual increases set by the Rent Guidelines Board; right to renew.</td></tr>"
            "<tr><td class='k'>Rent control</td><td>A much older program — only around <strong>16,000</strong> apartments remain. "
            "The tenant (or a successor) must have been in the unit continuously since before July 1, 1971, in a building "
            "built before 1947. Increases are governed by a separate state formula.</td></tr>"
            "</table>"

            "<h2>Rent control is disappearing</h2>"
            "<p>Rent control is a legacy program from the 1940s. Because it requires continuous occupancy stretching back "
            "more than fifty years, the number of controlled apartments shrinks every year. When a rent-controlled apartment "
            "becomes vacant, it usually converts to rent stabilization (or, in small buildings, to market rate) rather than "
            "staying controlled. So if someone tells you an apartment is \"rent controlled,\" it is far more often rent "
            "<em>stabilized</em>.</p>"

            "<h2>How to tell which one you have</h2>"
            "<p>The definitive answer is your DHCR rent history and paperwork:</p>"
            "<ul>"
            "<li><strong>Stabilized:</strong> you get DHCR renewal-lease offers (RTP-8), your lease has a Rent Stabilization "
            "Rider, and the RGB percentage applies.</li>"
            "<li><strong>Controlled:</strong> long-term tenancy from before 1971, no standard lease-renewal cycle, and DHCR "
            "issues a specific \"Maximum Base Rent\" / \"Maximum Collectible Rent.\"</li>"
            "</ul>"
            "<p>See our step-by-step guide on <a href='/guide/is-my-apartment-rent-stabilized/'>how to check if your apartment "
            "is rent stabilized</a>.</p>"

            "<h2>What about \"rent controlled apartments\" listed for rent?</h2>"
            "<p>An apartment advertised as available for rent is essentially never truly rent controlled — controlled status "
            "depends on decades of continuous occupancy and does not transfer to a new market tenant. An available "
            "\"affordable\" unit in an older building is much more likely to be rent stabilized. Use the map to check the "
            "building's actual registration status.</p>"
            + TOOL_CTA + SOURCES
        ),
    },
    {
        "city": "nyc",
        "slug": "how-to-find-a-rent-stabilized-apartment",
        "title": "How to Find a Rent-Stabilized Apartment in NYC",
        "desc": "A practical guide to finding rent-stabilized apartments in New York City: where to look, "
                "how to verify a building's status before you sign, and what to watch out for.",
        "h1": "How to find a rent-stabilized apartment",
        "body": (
            "<p class='lead'>Rent-stabilized apartments rarely come with a label on the listing, so finding one takes a "
            "little detective work. The key is to check the <em>building</em>, because stabilization follows the building, "
            "not the listing.</p>"

            "<h2>1. Start with the building, not the listing</h2>"
            "<p>Most rental listings never mention rent stabilization even when the unit is stabilized. Instead of relying "
            "on the ad, look up the address. Find A Crib maps every building in the DHCR rent-stabilized registration files "
            "across all five boroughs, so you can check a building's status in seconds — before you tour, and definitely "
            "before you sign.</p>"
            + TOOL_CTA +

            "<h2>2. Focus your search where stabilized housing is common</h2>"
            "<p>Because stabilization generally applies to pre-1974 buildings with six or more units, older mid-size "
            "apartment buildings are your best hunting ground. Browse by borough to see where the registered buildings are:</p>"
            "<div class='cols'>"
            "<a href='/borough/manhattan/'>Manhattan</a>"
            "<a href='/borough/brooklyn/'>Brooklyn</a>"
            "<a href='/borough/queens/'>Queens</a>"
            "<a href='/borough/bronx/'>Bronx</a>"
            "<a href='/borough/staten-island/'>Staten Island</a>"
            "</div>"
            "<p>You can also see buildings that have <a href='/available/'>recently advertised a unit for rent</a>.</p>"

            "<h2>3. Verify before you sign</h2>"
            "<p>Once you have a lead, confirm it:</p>"
            "<ul>"
            "<li>Ask the landlord or broker directly whether the unit is rent stabilized, in writing.</li>"
            "<li>Check that the lease includes a <strong>Rent Stabilization Rider</strong>.</li>"
            "<li>After you move in, request the apartment's <strong>rent history</strong> from DHCR (free) to confirm the "
            "registered rent and status. See <a href='/guide/is-my-apartment-rent-stabilized/'>how to check</a>.</li>"
            "</ul>"

            "<h2>4. Know your rights as a renter</h2>"
            "<p>Source-of-income discrimination is illegal in NYC — a landlord cannot refuse you for using a Section 8 or "
            "other housing voucher. And once you are in a stabilized unit, you have the right to renew and to capped "
            "increases. Learn more in our guide to <a href='/guide/rent-stabilized-tenant-rights/'>rent-stabilized tenant "
            "rights</a>.</p>"
            + TOOL_CTA + SOURCES
        ),
    },
    {
        "city": "nyc",
        "slug": "rent-stabilized-tenant-rights",
        "title": "Rent-Stabilized Tenant Rights in NYC",
        "desc": "If you live in a rent-stabilized apartment you have strong rights: lease renewal, capped increases, "
                "succession, and required services. Here's what those rights are and how to protect them.",
        "h1": "Rent-stabilized tenant rights",
        "body": (
            "<p class='lead'>Rent stabilization is not just about the rent — it is a bundle of protections that give "
            "tenants stability. If your apartment is stabilized, here are the core rights you have.</p>"

            "<h2>The right to renew your lease</h2>"
            "<p>Your landlord generally must offer you a renewal lease, on the same terms, with a choice of a 1-year or "
            "2-year term. They cannot refuse to renew simply to raise the rent or bring in a market tenant. Renewals come "
            "on an official DHCR renewal form.</p>"

            "<h2>Capped rent increases</h2>"
            "<p>Increases on renewal are limited to the percentage set each year by the NYC Rent Guidelines Board — not "
            "whatever the landlord wants. Check the "
            "<a href='https://rentguidelinesboard.cityofnewyork.us/' rel='nofollow noopener' target='_blank'>current RGB "
            "order</a> for this year's figure. See our guide to "
            "<a href='/guide/rent-stabilized-lease-renewal-and-rent-increases/'>lease renewals and rent increases</a>.</p>"

            "<h2>Succession rights</h2>"
            "<p>Certain family members who have lived with you can \"succeed\" to the lease when you move out or pass away — "
            "keeping the apartment and its stabilized status — if they meet the co-residency requirements. This is one of "
            "the most valuable and least-understood protections.</p>"

            "<h2>Required services and repairs</h2>"
            "<p>Your landlord must maintain the same services that came with the apartment: heat and hot water, working "
            "appliances, and timely repairs. A failure to maintain services can be the basis for a rent reduction through "
            "DHCR. You can look up a building's open <strong>HPD violations</strong> on its Find A Crib page to see its "
            "repair record.</p>"

            "<h2>Protection from overcharge</h2>"
            "<p>If a landlord charges more than the legal regulated rent, you may file an <strong>overcharge</strong> "
            "complaint with DHCR and can be entitled to a refund (and, in some cases, damages). Your rent history is the "
            "key document — learn <a href='/guide/is-my-apartment-rent-stabilized/'>how to request it</a>.</p>"

            "<h2>Where to get help</h2>"
            "<p>If you believe your rights are being violated, contact DHCR, a tenant attorney, or a legal-aid organization. "
            "Do not rely solely on this page — it is general information, not legal advice.</p>"
            + TOOL_CTA + SOURCES
        ),
    },
    {
        "city": "nyc",
        "slug": "rent-stabilized-lease-renewal-and-rent-increases",
        "title": "Rent-Stabilized Lease Renewals & Rent Increases (NYC)",
        "desc": "How rent-stabilized lease renewals work in NYC: the 1-year vs 2-year choice, how the Rent Guidelines "
                "Board sets increases, renewal timing, and what a landlord can and can't do.",
        "h1": "Rent-stabilized lease renewals & rent increases",
        "body": (
            "<p class='lead'>One of the biggest benefits of a rent-stabilized apartment is predictable renewals. Here is "
            "how the renewal and increase process works.</p>"

            "<h2>The renewal offer</h2>"
            "<p>Between 90 and 150 days before your lease ends, your landlord must offer you a renewal on an official DHCR "
            "renewal-lease form, giving you a choice of a <strong>1-year or 2-year</strong> term. You then have 60 days to "
            "return it. The apartment's services and terms stay the same — only the rent changes, and only by the allowed "
            "amount.</p>"

            "<h2>How the increase is set</h2>"
            "<p>The NYC Rent Guidelines Board (RGB) votes each June on the maximum percentage increase for 1-year and "
            "2-year renewal leases that begin on or after October 1 of that year. The 2-year figure is higher than the "
            "1-year figure because it locks the rate for longer. Because the numbers change annually, always confirm the "
            "current year's order at the "
            "<a href='https://rentguidelinesboard.cityofnewyork.us/' rel='nofollow noopener' target='_blank'>Rent "
            "Guidelines Board</a> rather than assuming.</p>"

            "<h2>1-year vs. 2-year: which should you choose?</h2>"
            "<ul>"
            "<li><strong>2-year</strong> gives you a higher increase now but locks your rent for two years — good when you "
            "expect increases to keep rising and you plan to stay.</li>"
            "<li><strong>1-year</strong> costs less this year but you renew again in twelve months at whatever the next "
            "RGB order is.</li>"
            "</ul>"

            "<h2>What a landlord cannot do</h2>"
            "<ul>"
            "<li>They cannot raise your rent above the RGB percentage on renewal.</li>"
            "<li>They cannot refuse to renew in order to charge a market rent.</li>"
            "<li>They cannot cut services or skip repairs to pressure you out.</li>"
            "</ul>"
            "<p>The 2019 HSTPA law also sharply limited the increases landlords can pass along after apartment renovations, "
            "closing loopholes that used to push rents up quickly. See "
            "<a href='/guide/what-is-rent-stabilization/'>what rent stabilization is</a> for the bigger picture, or "
            "<a href='/guide/rent-stabilized-tenant-rights/'>your full tenant rights</a>.</p>"
            + TOOL_CTA + SOURCES
        ),
    },

    # ---- San Francisco ------------------------------------------------------
    {
        "city": "nyc",
        "slug": "deed-theft-nyc",
        "title": "Deed Theft in NYC: Warning Signs and How to Report It",
        "desc": "Deed theft is when someone forges or tricks you into signing a deed and takes your home on paper. How it happens in New York City, the warning signs, who to call — the Sheriff, your DA, the Attorney General — and the free alert that catches it early.",
        "h1": "Deed theft: how it happens and how to report it",
        "body": (
            "<p class='lead'>Deed theft is the transfer of a home's title without the owner's real consent — "
            "a forged signature on a deed, or a document the owner was tricked into signing. Once the deed is "
            "recorded, the thief can borrow against the house or sell it, and the family living there can find "
            "itself facing eviction from a home it owns. New York's Attorney General counted roughly 3,000 "
            "deed-theft complaints in the city from 2014–2018, 45% of them from Brooklyn, and complaints have "
            "kept climbing since. It targets the same neighborhoods this site maps: older one- to four-family "
            "homes in central Brooklyn, southeast Queens and the Bronx, often owned outright by seniors.</p>"

            "<h2>How the scam usually works</h2>"
            "<ul>"
            "<li><strong>The forged deed.</strong> Someone records a deed transferring your property to themselves "
            "or a shell LLC, with a forged signature and a notary stamp. You find out when a tax bill stops "
            "coming, a stranger's mortgage shows up, or a marshal's notice arrives.</li>"
            "<li><strong>The 'rescue'.</strong> A homeowner behind on the mortgage, taxes or water bills is offered "
            "help — a refinance, a loan, a way to 'pause' foreclosure. Among the papers is a deed. The owner "
            "signs believing it is something else.</li>"
            "<li><strong>The estate grab.</strong> After an owner dies, a relative or stranger records a deed the "
            "owner supposedly signed before death, or exploits heirs who never formally transferred title.</li>"
            "<li><strong>The rent-to-own or sale-leaseback.</strong> The owner is told they can sell, stay as a "
            "tenant, and buy back later. The buy-back never happens; the eviction does.</li>"
            "</ul>"

            "<h2>Warning signs</h2>"
            "<ul>"
            "<li>Your property-tax bill or water bill stops arriving, or arrives in someone else's name.</li>"
            "<li>Mail about a mortgage, refinance or line of credit you never applied for.</li>"
            "<li>A notice of eviction, foreclosure or a court date on a home you own free and clear.</li>"
            "<li>Unsolicited offers to buy the house, 'help with' the mortgage, or 'take the property off your "
            "hands' — especially if you are behind on payments or the house is in an estate.</li>"
            "<li>Anyone asking you to sign papers at home, quickly, without your own lawyer.</li>"
            "</ul>"

            "<h2>Check your own deed right now</h2>"
            "<p>Every deed and mortgage recorded in Manhattan, Brooklyn, Queens and the Bronx is public in "
            "<a href='https://a836-acris.nyc.gov/' rel='nofollow noopener' target='_blank'>ACRIS</a>, the City "
            "Register's database (Staten Island records are with the "
            "<a href='https://www.richmondcountyclerk.com/' rel='nofollow noopener' target='_blank'>Richmond County Clerk</a>). "
            "Search by address or by the borough-block-lot on your tax bill and read the list of recorded "
            "documents. Anything you do not recognize — a deed, a mortgage, a power of attorney — is the "
            "moment to act. Find A Crib's building pages carry the BBL for every "
            "<a href='/buildings/'>rent-stabilized building in the city</a>, which is the number ACRIS wants.</p>"

            "<h2>The free alert that catches it early</h2>"
            "<p>The Department of Finance runs the <strong>Notice of Recorded Document Program</strong>: register "
            "your property once and the city emails, texts or mails you the day after any deed, mortgage or "
            "related document is recorded against it. It is free, and it is the single most effective "
            "protection there is, because a forged deed is far easier to undo in the first week than after a "
            "mortgage has been taken out on it. Sign up at "
            "<a href='https://a836-acrissds.nyc.gov/NRD/' rel='nofollow noopener' target='_blank'>a836-acrissds.nyc.gov/NRD</a>. "
            "Owners, heirs, executors, attorneys and managing agents can all register.</p>"

            "<h2>How to report deed theft</h2>"
            "<p>Report it to more than one place — the agencies below do different things, and the first "
            "days matter.</p>"
            "<ol>"
            "<li><strong>Mayor's Office of Deed Theft Prevention</strong> (in the Department of Finance) — complete the "
            "<a href='https://www.nyc.gov/site/finance/property/deed-fraud-protection.page' rel='nofollow noopener' target='_blank'>"
            "Deed Theft Prevention Intake Form</a> at nyc.gov/deedtheft. This office coordinates the city's "
            "response and will help you with the steps below.</li>"
            "<li><strong>NYC Sheriff's Office</strong>, Bureau of Criminal Investigation — <strong>(718) 707-2100</strong>. "
            "The Sheriff investigates recorded-document fraud citywide. If the theft involves a break-in, "
            "violence or threats, call the NYPD (911) first.</li>"
            "<li><strong>Your borough's District Attorney.</strong> Deed theft is a felony under New York's 2023 "
            "deed-theft law. Brooklyn's DA runs a dedicated line, the Action Center at <strong>(718) 250-2340</strong> "
            "(9am–5pm) and publishes a "
            "<a href='https://brooklynda.org/deedfraud/' rel='nofollow noopener' target='_blank'>deed-fraud guide</a>; "
            "the other four DAs take reports through their main offices.</li>"
            "<li><strong>New York State Attorney General</strong> — hotline <strong>1-800-771-7755</strong>, or the "
            "<a href='https://formsnym.ag.ny.gov/OAGOnlineSubmissionForm/faces/OAGDTBHome' rel='nofollow noopener' target='_blank'>"
            "online deed-theft complaint form</a>. The AG's Protect Our Homes initiative screens complaints and "
            "brings civil and criminal cases, and can move to void a fraudulent deed and pause a related "
            "eviction or foreclosure.</li>"
            "<li><strong>Get a certified copy of the fraudulent document</strong> from the City Register "
            "(call 311, or write to NYC Department of Finance, Office of the City Register, 66 John Street, "
            "13th Floor, New York, NY 10038). You will need it for every step above.</li>"
            "<li><strong>Get a lawyer.</strong> Free help is available: call the state's homeowner hotline at "
            "<strong>1-855-466-3456</strong> or visit "
            "<a href='https://homeownerhelpny.org/deed-theft' rel='nofollow noopener' target='_blank'>HomeownerHelpNY</a> "
            "to be matched with a legal-services or housing-counseling group near you.</li>"
            "</ol>"

            "<h2>If you are a tenant</h2>"
            "<p>Deed theft also lands on renters: a new 'owner' appears, demands rent, or starts an eviction. "
            "Do not pay anyone whose name is not on the deed in ACRIS. Your lease and your "
            "<a href='/guide/rent-stabilized-tenant-rights/'>rent-stabilized protections</a> survive a change in "
            "ownership, fraudulent or not — and if the deed was stolen, the eviction has no standing. Tell the "
            "real owner, and call the numbers above yourself.</p>"

            "<h2>Where to get help</h2>"
            "<p>The agencies above, a real-estate attorney, or a legal-aid organization. This page is general "
            "information about deed theft in New York City, not legal advice.</p>"
            + TOOL_CTA +
            "<h2>Official sources</h2>"
            "<ul>"
            "<li><a href='https://www.nyc.gov/site/finance/property/deed-fraud-protection.page' rel='nofollow noopener' target='_blank'>"
            "Mayor's Office of Deed Theft Prevention — NYC Department of Finance</a></li>"
            "<li><a href='https://a836-acrissds.nyc.gov/NRD/' rel='nofollow noopener' target='_blank'>"
            "Notice of Recorded Document Program — sign up for deed and mortgage alerts</a></li>"
            "<li><a href='https://portal.311.nyc.gov/article/?kanumber=KA-02936' rel='nofollow noopener' target='_blank'>"
            "NYC311 — Property Deed or Record Theft</a></li>"
            "<li><a href='https://ag.ny.gov/resources/individuals/tenants-homeowners/homeowners' rel='nofollow noopener' target='_blank'>"
            "New York State Attorney General — Homeowners and deed theft</a></li>"
            "<li><a href='https://brooklynda.org/deedfraud/' rel='nofollow noopener' target='_blank'>"
            "Brooklyn District Attorney — Deed Fraud Information and Resources</a></li>"
            "</ul>"
            "<p class='disclaimer'>Find A Crib is an informational tool, not a law firm. This guide is general "
            "information about deed theft in New York City, not legal advice. For your specific situation, "
            "contact the agencies above or an attorney.</p>"
        ),
    },
    {
        "city": "sf",
        "slug": "is-my-apartment-rent-controlled-san-francisco",
        "title": "Is My Apartment Rent Controlled in San Francisco? How to Check",
        "desc": "How to tell whether your San Francisco apartment is rent controlled: the June 13, 1979 "
                "certificate-of-occupancy rule, the Costa-Hawkins exemptions, just-cause eviction protection, "
                "and where to confirm it.",
        "h1": "Is my apartment rent controlled in San Francisco?",
        "body": (
            "<p class='lead'>San Francisco has two separate protections that people both call \"rent control\", and you "
            "can have one without the other. <strong>Price control</strong> — the cap on how much your rent can go up "
            "each year — generally applies to buildings of two or more units whose first certificate of occupancy was "
            "issued on or before <strong>June 13, 1979</strong>. <strong>Just-cause eviction protection</strong> under "
            "the same Rent Ordinance reaches much further. Here is how to work out which applies to you.</p>"

            "<h2>1. Find the building's certificate of occupancy date</h2>"
            "<p>San Francisco rent control is tied to when the <em>building</em> was first approved for occupancy, not "
            "to when you moved in or what your lease says. If the first certificate of occupancy was issued on or "
            "before June 13, 1979 and the building has two or more units, it is the standard case for coverage. You can "
            "look up building records by address on the "
            "<a href='https://sfplanninggis.org/pim/' rel='nofollow noopener' target='_blank'>SF Property Information "
            "Map</a>.</p>"

            "<h2>2. Check whether state law carves your unit out</h2>"
            "<p>California's <strong>Costa-Hawkins Rental Housing Act</strong>, in effect since January 1, 1996, removes "
            "some units from local price control even in old buildings:</p>"
            "<ul>"
            "<li><strong>Single-family homes and condominiums</strong> that can be sold separately from any other "
            "dwelling unit are generally exempt from the local rent cap.</li>"
            "<li>Units first certificated <strong>after</strong> the local cutoff date are exempt from the cap.</li>"
            "<li>It also allows <strong>vacancy decontrol</strong>: when a tenant moves out voluntarily, the owner may "
            "reset the rent to market for the next tenant. The annual cap then applies again to that new tenancy — so a "
            "high starting rent does not mean the unit is uncontrolled.</li>"
            "</ul>"

            "<h2>3. Even outside the rent cap, you probably still have just cause</h2>"
            "<p>The Rent Ordinance's <strong>just-cause eviction</strong> rules cover far more tenancies in San Francisco "
            "than the price cap does. A landlord generally needs one of the specific reasons listed in the ordinance to "
            "end a tenancy. Being outside price control is not the same as being outside the ordinance, and this is the "
            "single most common misunderstanding tenants arrive with.</p>"

            "<h2>4. Ask the Rent Board</h2>"
            "<p>The <a href='https://www.sf.gov/departments--rent-board' rel='nofollow noopener' target='_blank'>San "
            "Francisco Rent Board</a> counsels tenants by phone and in person, publishes the current annual allowable "
            "increase, and is where petitions are filed — including petitions over an increase you believe exceeds the "
            "limit. That is the authoritative answer for your address; this page is the orientation.</p>"

            "<h2>5. Look up the block on the map</h2>"
            "<p>Find A Crib maps San Francisco from official SF Rent Board owner reports. One caveat matters and we will "
            "not soften it: <strong>the San Francisco data is anonymized to the block, not the individual address.</strong> "
            "It shows you where rent-controlled units are reported across the city and what owners reported about them — "
            "it cannot tell you the status of your specific unit. Use it to orient yourself, then confirm with the "
            "certificate of occupancy date and the Rent Board.</p>"
            + TOOL_CTA_SF +

            "<h2>What if the rent cap doesn't cover me?</h2>"
            "<p>California's statewide law <strong>AB 1482</strong> caps annual increases for many units that local "
            "ordinances do not reach. The cap is tied to regional CPI and changes every year, so check the current figure "
            "with the Rent Board or the state rather than relying on a number you read somewhere — including here.</p>"
            + SOURCES_SF
        ),
    },

    # ---- Los Angeles --------------------------------------------------------
    {
        "city": "la",
        "slug": "is-my-apartment-rent-controlled-los-angeles",
        "title": "Is My Apartment Rent Controlled in Los Angeles? RSO Lookup Explained",
        "desc": "How to check whether your Los Angeles apartment is covered by the Rent Stabilization Ordinance "
                "(RSO): the October 1, 1978 rule, what LAHD's rent registry shows, and what still protects you "
                "if the RSO does not.",
        "h1": "Is my apartment rent controlled in Los Angeles?",
        "body": (
            "<p class='lead'>Los Angeles rent control is the <strong>Rent Stabilization Ordinance</strong>, or RSO. As a "
            "rule it covers rental units in the City of Los Angeles in buildings of <strong>two or more units</strong> "
            "with a certificate of occupancy issued <strong>on or before October 1, 1978</strong>. Two things trip people "
            "up: the City of Los Angeles is not Los Angeles County, and a building that misses the RSO date can still be "
            "covered by other law.</p>"

            "<h2>1. Confirm you are in the City of Los Angeles</h2>"
            "<p>The RSO is a City ordinance. Unincorporated Los Angeles County has its own separate rent rules, and "
            "neighbouring cities such as Santa Monica and West Hollywood have theirs. A Los Angeles mailing address is "
            "not proof you are inside the City limits — the parcel is what decides it.</p>"

            "<h2>2. Check the date and the unit count</h2>"
            "<p>The core test is build date plus unit count. Beyond ordinary apartment buildings, LAHD describes the RSO "
            "as reaching condominiums, duplexes, accessory dwelling units, and rooms occupied by the same tenant for 30 "
            "or more consecutive days in a hotel or rooming house. A lone single-family house on its own parcel is "
            "generally outside the RSO — but two or more dwellings on the same parcel can be inside it.</p>"

            "<h2>3. Check LAHD's records</h2>"
            "<p>Owners of RSO units must register them with the "
            "<a href='https://housing.lacity.gov/residents/rso-overview' rel='nofollow noopener' target='_blank'>Los "
            "Angeles Housing Department</a> and pay an annual fee, so LAHD holds a registration record for covered units. "
            "Asking LAHD whether your unit has one is the closest thing to a definitive answer available to a tenant. The "
            "certificate of occupancy itself is a "
            "<a href='https://www.ladbs.org/' rel='nofollow noopener' target='_blank'>LADBS</a> record.</p>"

            "<h2>4. What our Los Angeles map shows — and what it does not</h2>"
            "<p>This caveat is important enough to state before the map link, not after it. The Find A Crib Los Angeles "
            "layer is <strong>derived, not official</strong>: it flags buildings that meet the RSO's published criteria — "
            "build year and unit count, from county assessor data — and labels them <strong>\"likely RSO\"</strong>. It is "
            "not LAHD's list. A building can meet those criteria and still be exempt, and a building can be covered for a "
            "reason the assessor record does not show. Use it to narrow the question down, then confirm with LAHD before "
            "you act on it.</p>"
            + TOOL_CTA_LA +

            "<h2>5. Not RSO? Two other laws may still cover you</h2>"
            "<ul>"
            "<li><strong>AB 1482</strong>, the California statewide rent cap, limits annual increases for many units "
            "outside local rent control. The limit is tied to regional CPI and changes annually — check the current "
            "figure at <a href='https://housing.lacity.gov/residents/ab-1482' rel='nofollow noopener' target='_blank'>"
            "LAHD's AB 1482 page</a>.</li>"
            "<li>The City's <strong>Just Cause Ordinance</strong> extends eviction protections to many non-RSO rentals "
            "once the tenancy has passed an initial qualifying period, so \"my building is too new for the RSO\" does not "
            "mean you can be evicted without a reason.</li>"
            "</ul>"
            + SOURCES_LA
        ),
    },

    # ---- Washington DC ------------------------------------------------------
    {
        "city": "dc",
        "slug": "is-my-apartment-rent-controlled-washington-dc",
        "title": "Is My Apartment Rent Controlled in Washington DC? How to Check",
        "desc": "How to tell whether your DC apartment is rent stabilized: the pre-1976 rule, the common "
                "exemptions, and the registration rule that means an unregistered unit is treated as covered.",
        "h1": "Is my apartment rent controlled in Washington, DC?",
        "body": (
            "<p class='lead'>In Washington, DC, rent control is formally <strong>rent stabilization</strong> under the "
            "Rental Housing Act of 1985. As a rule it covers rental units in buildings <strong>built before 1976</strong>. "
            "But the rule that matters most to tenants is the registration rule: every rental unit in the District must be "
            "registered with the Rental Accommodations Division, and <strong>a unit that is not registered with an "
            "approved exemption is treated as covered</strong>.</p>"

            "<h2>1. Check when the building was built</h2>"
            "<p>Buildings first built in 1976 or later are generally exempt as new construction. Older buildings are the "
            "standard case for coverage, subject to the exemptions below.</p>"

            "<h2>2. Check the exemptions</h2>"
            "<p>The common ones are:</p>"
            "<ul>"
            "<li><strong>New construction</strong> — built 1976 or later.</li>"
            "<li><strong>Small landlords</strong> — units owned by a natural person (not a company) who owns four or "
            "fewer rental units in the District. Note the two halves: it must be a person, and the count is across the "
            "whole District, not just your building.</li>"
            "<li><strong>Subsidized housing</strong> — units under federal or District rent-subsidy programs, which have "
            "their own rent rules.</li>"
            "<li><strong>Vacant and substantially rehabilitated</strong> buildings, where the owner obtained approval.</li>"
            "</ul>"

            "<h2>3. The registration rule works in tenants' favour</h2>"
            "<p>An exemption is not automatic. The owner has to claim it on a registration filing with the "
            "<strong>Rental Accommodations Division (RAD)</strong> and have it approved. So if your landlord never "
            "registered your unit, that is not evidence you are unregulated — it points the other way. Ask RAD for the "
            "registration or exemption record for your address; that filing, not your landlord's description of it, is "
            "what governs.</p>"

            "<h2>4. Ask RAD or the Office of the Tenant Advocate</h2>"
            "<p>RAD holds the registration and exemption filings for every rental housing accommodation in the District. "
            "The <a href='https://ota.dc.gov/' rel='nofollow noopener' target='_blank'>Office of the Tenant Advocate</a> "
            "gives DC tenants free advice and can help you read what you get back.</p>"

            "<h2>5. Look up the building on the map</h2>"
            "<p>Find A Crib maps Washington DC from the District's own registration records, so — unlike our Los Angeles "
            "layer, which is derived from assessor criteria — the DC layer reflects an official registry. It still shows "
            "the <em>building</em> rather than the current status of your individual unit, and registrations change, so "
            "confirm with RAD before you act on it.</p>"
            + TOOL_CTA_DC +

            "<h2>If you are covered</h2>"
            "<p>Annual increases for rent-stabilized units are limited by a CPI-linked figure, with a lower cap for "
            "elderly tenants and tenants with disabilities. The figure is republished as the CPI changes, so take the "
            "current one from "
            "<a href='https://dhcd.dc.gov/rentcontrol' rel='nofollow noopener' target='_blank'>DHCD</a> rather than from "
            "any secondary source, including this page.</p>"
            + SOURCES_DC
        ),
    },
]
