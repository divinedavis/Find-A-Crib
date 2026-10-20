import Foundation

/// What people type into the location search that isn't a place (owner,
/// 2026-10-19: "fix all" after a month of no-match searches — "rent", "rent
/// stabilized", "2 bedroom", "yonkers", "bronx ny", "bedford stuy", "voucher").
/// The web's index.html has the same rules (searchIntent / stripFiller); keep
/// the two in step.
enum SearchText {
    /// Words that only restate what the app is (rent-stabilized apartments in
    /// NYC). "rent stabilized apartments in brooklyn ny" is a search for Brooklyn.
    private static let filler = #"\b(?:please|search(?:ing)?|show(?: me)?|find(?: me)?|looking(?: for)?|i(?: am|'m)?|want|need|only|just|all|any|rent[\s-]*stab\w*|rent[\s-]*regulated|rent[\s-]*controll?ed|stabili[sz]ed|stabalized|rentals?|rent|for|apartments?|apts?|units?|homes?|buildings?|in|at|near(?: me)?|the|a|an|ny|nyc|new york(?: city)?|city|ny state)\b"#

    static func stripFiller(_ s: String) -> String {
        s.replacingOccurrences(of: #"[,.!?]+"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: filler, with: " ", options: [.regularExpression, .caseInsensitive])
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
    }

    /// Nicknames a plain "contains" can't reach, to the app's neighborhood names.
    static let aliases: [String: [String]] = [
        "bedstuy": ["Bed-Stuy (East)", "Bed-Stuy (West)"], "bedfordstuy": ["Bed-Stuy (East)", "Bed-Stuy (West)"],
        "bedfordstuyvesant": ["Bed-Stuy (East)", "Bed-Stuy (West)"], "bedstuyvesant": ["Bed-Stuy (East)", "Bed-Stuy (West)"],
        "ues": ["Upper East Side-Carnegie Hill", "Upper East Side-Lenox Hill-Roosevelt Island", "Upper East Side-Yorkville"],
        "uws": ["Upper West Side (Central)", "Upper West Side-Lincoln Square", "Upper West Side-Manhattan Valley"],
        "les": ["Lower East Side"], "fidi": ["Financial District-Battery Park City"], "lic": ["Long Island City-Hunters Point"],
        "stuytown": ["Stuyvesant Town-Peter Cooper Village"], "hellskitchen": ["Hell's Kitchen"],
        "dumbo": ["Downtown Brooklyn-DUMBO-Boerum Hill"],
    ]
    static let boroughAliases: [String: String] = ["bk": "Bk", "bklyn": "Bk", "bx": "Bx", "thebronx": "Bx", "si": "SI", "qns": "Q", "manh": "M"]

    static func flat(_ s: String) -> String { s.lowercased().filter { $0.isLetter || $0.isNumber } }

    /// "bronx 10453", "brooklyn 11221": the ZIP is the precise part.
    static func zipFromPlace(_ s: String) -> String? {
        guard let r = s.range(of: #"\b\d{5}\b"#, options: .regularExpression) else { return nil }
        let other = s.replacingCharacters(in: r, with: " ").trimmingCharacters(in: .whitespaces).lowercased()
        let boroughs = ["", "bronx", "the bronx", "brooklyn", "bklyn", "bk", "queens", "manhattan", "staten island", "si"]
        return boroughs.contains(other) ? String(s[r]) : nil
    }

    enum Elsewhere: Equatable { case westchester, outside(String) }
    /// A town another Find A Crib map covers, or one none covers yet.
    static func elsewhere(_ s: String) -> Elsewhere? {
        let t = s.lowercased()
        if t.range(of: #"\b(?:yonkers|mount vernon|mt\.? vernon|new rochelle|white plains|westchester|scarsdale|tarrytown|ossining|peekskill|port chester|mamaroneck)\b"#, options: .regularExpression) != nil
            || t.range(of: #"^10[5-8]\d\d$"#, options: .regularExpression) != nil { return .westchester }
        if t.range(of: #"\b(?:poughkeepsie|albany|buffalo|rochester|syracuse|newburgh|kingston)\b"#, options: .regularExpression) != nil { return .outside("upstate New York") }
        if t.range(of: #"\b(?:long island|hempstead|freeport|hicksville|levittown|nassau|suffolk)\b"#, options: .regularExpression) != nil { return .outside("Long Island") }
        return nil
    }

    /// Bedrooms, vouchers and a rent cap typed as words.
    struct Intent: Equatable {
        var beds: Set<Int> = []
        var vouchers = false
        var maxRent: Int?
        var rest = ""
        var isEmpty: Bool { beds.isEmpty && !vouchers && maxRent == nil }
        var summary: String {
            var parts: [String] = []
            if !beds.isEmpty {
                parts.append(beds.sorted().map { $0 == 0 ? String(localized: "studio") : $0 == 4 ? String(localized: "4+ beds") : ($0 == 1 ? String(localized: "1 bed") : String(localized: "\($0) beds")) }.joined(separator: " / "))
            }
            if vouchers { parts.append(String(localized: "voucher-friendly")) }
            if let maxRent { parts.append(String(localized: "under $\(maxRent.formatted())")) }
            return parts.joined(separator: " · ")
        }
    }

    static func intent(_ s: String) -> Intent? {
        var t = " " + s.lowercased() + " "
        var out = Intent()
        func take(_ pattern: String, _ each: (String) -> Void) {
            guard let re = try? NSRegularExpression(pattern: pattern) else { return }
            for m in re.matches(in: t, range: NSRange(t.startIndex..., in: t)).reversed() {
                let g = (1..<m.numberOfRanges).compactMap { Range(m.range(at: $0), in: t).map { String(t[$0]) } }.first ?? ""
                each(g)
                if let r = Range(m.range, in: t) { t.replaceSubrange(r, with: " ") }
            }
        }
        take(#"\b(\d)\s*-?\s*(?:br|bd|bdr|bdrm|bed|beds|bedroom|bedrooms|bedrm)\b"#) { out.beds.insert(min(Int($0) ?? 0, 4)) }
        take(#"\b(one|two|three|four)\s*-?\s*(?:bed|beds|bedroom|bedrooms|br)\b"#) { out.beds.insert(["one": 1, "two": 2, "three": 3, "four": 4][$0] ?? 1) }
        take(#"\b(studios?)\b"#) { _ in out.beds.insert(0) }
        take(#"\b(section\s*8|sec\s*8|s8|vouchers?|cityfheps|fheps|hasa|hcv)\b"#) { _ in out.vouchers = true }
        take(#"(?:\b(?:under|below|max|up to|less than|cheaper than|no more than)\s*\$?\s*(\d[\d,]{2,5})\b|\$\s*(\d[\d,]{2,5})\b|\b(\d[\d,]{2,5})\s*(?:\$|dollars|/\s*mo(?:nth)?|a month|per month))"#) {
            if let v = Int($0.replacingOccurrences(of: ",", with: "")), (300...20000).contains(v) { out.maxRent = v }
        }
        guard !out.isEmpty else { return nil }
        out.rest = t.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression).trimmingCharacters(in: .whitespaces)
        return out
    }
}
