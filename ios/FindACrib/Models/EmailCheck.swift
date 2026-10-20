import Foundation

/// Sign-up address check (2026-10-20): a typo'd or made-up address signs up
/// fine and then bounces every alert forever — "gmail.ckm", testing@gmail.com.
/// Same list as emailFix() in the web's index.html.
enum EmailCheck {
    enum Problem: Equatable { case typo(String), fake }

    static let domainFix: [String: String] = [
        "gmail.ckm": "gmail.com", "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gmail.co": "gmail.com",
        "gmail.om": "gmail.com", "gmail.comm": "gmail.com", "gmial.com": "gmail.com", "gmai.com": "gmail.com",
        "gnail.com": "gmail.com", "gmal.com": "gmail.com", "gamil.com": "gmail.com", "gmaill.com": "gmail.com",
        "yahoo.con": "yahoo.com", "yaho.com": "yahoo.com", "yhoo.com": "yahoo.com", "hotmial.com": "hotmail.com",
        "hotmail.con": "hotmail.com", "hotmal.com": "hotmail.com", "outlook.con": "outlook.com", "outlok.com": "outlook.com",
        "iclod.com": "icloud.com", "icloud.con": "icloud.com", "icoud.com": "icloud.com", "aol.con": "aol.com",
    ]

    static func problem(_ raw: String) -> Problem? {
        let e = raw.trimmingCharacters(in: .whitespaces).lowercased()
        guard let at = e.lastIndex(of: "@"), at != e.startIndex else { return nil }
        let local = String(e[..<at]), dom = String(e[e.index(after: at)...])
        if let f = domainFix[dom] { return .typo("\(local)@\(f)") }
        if dom.range(of: #"\.(con|cmo|ckm|vom|xom|comm)$"#, options: .regularExpression) != nil {
            return .typo(local + "@" + dom.replacingOccurrences(of: #"\.[a-z]+$"#, with: ".com", options: .regularExpression))
        }
        if local.range(of: #"^(test|tests|testing|tester|testers|asdf|example|fake|none|noemail|abc)\d*$"#, options: .regularExpression) != nil
            || dom.range(of: #"^(example|test)\.(com|org|net)$"#, options: .regularExpression) != nil { return .fake }
        return nil
    }
}
