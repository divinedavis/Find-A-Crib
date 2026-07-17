"""
Cornerstone SEO guide content for Find A Crib.

Editorial pages that target the high-intent informational queries around NYC
rent stabilization ("is my apartment rent stabilized", "how to find a rent
stabilized apartment", "rent stabilized vs rent controlled", tenant rights,
lease renewal). These build topical authority and internally link to the ~47k
data pages. build_seo.py renders each into /guide/<slug>/ plus a /guide/ hub.

Accuracy: content sticks to well-established, durable facts and links out to the
authoritative sources (DHCR/HCR, the Rent Guidelines Board, HPD, tenant
resources) for anything that changes year to year (e.g. the annual RGB
increase). Guides are informational, not legal advice.
"""

# Reusable snippets ----------------------------------------------------------
TOOL_CTA = (
    "<a class='cta' href='/'>🔎 Check any building on the Find A Crib map →</a>"
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


def _related(current, guides):
    links = "".join(
        f"<a href='/guide/{g['slug']}/'>{g['h1']}</a>"
        for g in guides if g["slug"] != current
    )
    return f"<h2>Related guides</h2><div class='cols'>{links}</div>"


# The guides (order = hub display order) -------------------------------------
GUIDES = [
    {
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
]
