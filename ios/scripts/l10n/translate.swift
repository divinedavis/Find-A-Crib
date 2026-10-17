// Fills Shared/Localizable.xcstrings with on-device machine translations from
// Apple's Translation framework, on this Mac, at build time. Nothing leaves the
// machine and nothing bills: no Claude, DeepL or Google (owner, 2026-10-14:
// "lets do apple build in translation").
//
//   scripts/l10n/translate.sh                     # every installed language
//   scripts/l10n/translate.sh --langs de,ja       # some of them
//   scripts/l10n/translate.sh texts IN.json OUT.json --langs de,fr-CA
//                                                 # flat {id: text} (App Store copy)
//
// Apple documentation this follows:
// - TranslationSession.init(installedSource:target:preferredStrategy:), the
//   session an app or tool can create directly when the languages are already
//   on the device (macOS 26.4 / iOS 26.4):
//   https://developer.apple.com/documentation/translation/translationsession
// - translations(from:) — batch requests, matched back by clientIdentifier:
//   https://developer.apple.com/documentation/translation/translationsession/translations(from:)
// - LanguageAvailability.status(from:to:) — .installed / .supported / .unsupported:
//   https://developer.apple.com/documentation/translation/languageavailability
// - AttributeScopes.TranslationAttributes.skipsTranslation — runs the model
//   must copy through untouched (used on our placeholder tokens):
//   https://developer.apple.com/documentation/foundation/attributescopes/translationattributes
// - String catalogs (the .xcstrings format, states, plural variations):
//   https://developer.apple.com/documentation/xcode/localizing-and-varying-text-with-a-string-catalog
//
// What it does to every string:
// 1. Swaps format placeholders (%@, %lld, %1$@, %%) and protected terms
//    (Find A Crib, agency and borough names) for tokens T0, T1, … marked
//    skipsTranslation, translates, then restores them. When the translation
//    reorders arguments, the placeholders become positional (%2$@ … %1$@).
// 2. Refuses a translation whose placeholders don't match the English
//    (count, argument and type) — the string stays English in that language.
// 3. Writes the result with state "needs_review" (Xcode shows it as such);
//    a unit someone has marked "translated" is never overwritten.
// 4. Translates the result back into English and keeps that in
//    scripts/l10n/translation-state.json beside a hash of the English source.
//    A re-run only translates strings that are new or whose English changed.
//    scripts/l10n/review_flags.py reads the back-translations.
//
// Language assets: a language must be downloaded on this Mac first (System
// Settings › General › Language & Region › Translation Languages). A language
// that isn't installed is skipped and listed; it is never fetched silently.

import CryptoKit
import Foundation
import Translation

// MARK: - Configuration

/// Apple Translation language → String Catalog / iOS localization identifier.
/// Every language Apple Translation offers on macOS 26.4 that is also an iOS
/// app localization. English variants are the source language.
let catalogTargets: [(apple: String, catalog: String)] = [
    // New York's biggest non-English renter languages the App Store supports,
    // the same five as the listing (scripts/asc_localizations.py).
    ("es", "es"), ("zh", "zh-Hans"), ("zh-TW", "zh-Hant"), ("ko", "ko"), ("ru", "ru"),
]

/// Never translated: the app's name and its badge names (app, agency, program and place names stay English).
let fixedTerms = [
    "Find A Crib", "Your Crib", "Housing Connect", "NYC Housing Connect", "HousingSearch", "CityFHEPS",
    "Section 8", "HPD", "HCR", "DHCR", "NYCHA", "NYPD", "HUD", "LIHTC", "RGB", "AMI", "311", "Plus",
    "Apple Pay", "Apple", "Google", "iPhone", "iPad", "iOS", "Siri", "Look Around", "Mapillary",
    "Manhattan", "Brooklyn", "Queens", "The Bronx", "Bronx", "Staten Island", "New York", "NYC",
    "Los Angeles", "San Francisco", "Washington DC", "New Jersey",
]

/// CLDR plural categories each catalog language uses (the English "one"
/// form feeds "one"; every other category gets the translated "other").
func pluralCategories(_ lang: String) -> [String] {
    switch lang {
    case "ja", "ko", "zh-Hans", "zh-Hant", "vi", "th", "id": return ["other"]
    case "ru", "uk", "pl": return ["one", "few", "many", "other"]
    case "ar": return ["zero", "one", "two", "few", "many", "other"]
    case "fr", "es", "it", "pt-BR", "pt-PT": return ["one", "many", "other"]
    default: return ["one", "other"]
    }
}

// MARK: - Placeholders and protected terms

let placeholderRE = try! NSRegularExpression(
    // Flags limited to - + 0 #: a space flag would read "10% stretch" or
    // "5% or" as placeholders.
    pattern: #"%%|%#@[A-Za-z0-9_]+@|%(?:\d+\$)?[-+0#]*(?:\d+|\*)?(?:\.\d+)?(?:hh|h|ll|l|q|L|z|t|j)?[@dDiuUxXoOfFeEgGcCsSaAp]"#)
// A token may come back with a letter glued on ("T0s" for "%@'s" in German):
// only digits may not follow it.
let tokenRE = try! NSRegularExpression(pattern: #"(?<![A-Za-z0-9])T(\d+)(?!\d)"#)

struct Spec: Equatable {
    let arg: Int?        // 1-based argument number; nil for %%
    let type: String     // "@", "lld", "d", … ; "%" for %%
}

/// The arguments a format string consumes, in the order they appear.
func specs(_ s: String) -> [Spec] {
    var next = 1
    var out: [Spec] = []
    for m in placeholderRE.matches(in: s, range: NSRange(s.startIndex..., in: s)) {
        let t = String(s[Range(m.range, in: s)!])
        if t == "%%" { out.append(Spec(arg: nil, type: "%")); continue }
        if t.hasPrefix("%#@") { out.append(Spec(arg: next, type: t)); next += 1; continue }
        let body = t.dropFirst()
        if let dollar = body.firstIndex(of: "$"), let n = Int(body[..<dollar]) {
            out.append(Spec(arg: n, type: typeOf(String(body[body.index(after: dollar)...]))))
        } else {
            out.append(Spec(arg: next, type: typeOf(String(body)))); next += 1
        }
    }
    return out
}

func typeOf(_ conversion: String) -> String {
    // Drop flags/width/precision; keep length modifier + conversion ("lld", "@").
    String(conversion.drop { "-+0#*.123456789".contains($0) })
}

/// The comparable signature: each argument's number and type, %% counted.
func signature(_ s: String) -> [String] {
    specs(s).map { "\($0.arg.map(String.init) ?? "-"):\($0.type)" }.sorted()
}

/// One token: the English it stands for, and the argument number of each
/// placeholder inside it (adjacent hits such as "%lld%%" share one token,
/// because "T0T1" would not survive translation).
struct Token {
    var original: String
    var args: [Int?]          // per placeholder inside, in order; nil for %% and terms
    var hasPlaceholder: Bool { args.contains { $0 != nil } }
}

struct Protected {
    let text: String          // tokenised English
    let tokens: [Token]
}

func protect(_ english: String, terms: [String]) -> Protected {
    let ns = english as NSString
    var hits: [(range: NSRange, original: String, arg: Int?)] = []
    var next = 1
    for m in placeholderRE.matches(in: english, range: NSRange(location: 0, length: ns.length)) {
        let t = ns.substring(with: m.range)
        let spec = specs(t).first!
        var arg: Int? = nil
        if spec.arg != nil { if t.contains("$") { arg = spec.arg } else { arg = next; next += 1 } }
        hits.append((m.range, t, arg))
    }
    // Longest term first, whole words, case-sensitive, never inside another hit.
    for (term, re) in TermMatchers.shared.matchers(terms) where english.contains(term) {
        for m in re.matches(in: english, range: NSRange(location: 0, length: ns.length))
        where !hits.contains(where: { NSIntersectionRange($0.range, m.range).length > 0 }) {
            hits.append((m.range, term, nil))
        }
    }
    hits.sort { $0.range.location < $1.range.location }
    var out = ""
    var cursor = 0
    var tokens: [Token] = []
    for hit in hits {
        if hit.range.location == cursor, !tokens.isEmpty, out.hasSuffix("T\(tokens.count - 1)") {
            tokens[tokens.count - 1].original += hit.original      // glued to the previous hit
            tokens[tokens.count - 1].args.append(hit.arg)
        } else {
            out += ns.substring(with: NSRange(location: cursor, length: hit.range.location - cursor))
            out += "T\(tokens.count)"
            tokens.append(Token(original: hit.original, args: [hit.arg]))
        }
        cursor = hit.range.location + hit.range.length
    }
    out += ns.substring(from: cursor)
    return Protected(text: out, tokens: tokens)
}

/// One compiled whole-word matcher per term, longest first, built once.
final class TermMatchers: @unchecked Sendable {
    static let shared = TermMatchers()
    private var cache: [(String, NSRegularExpression)]?
    func matchers(_ terms: [String]) -> [(String, NSRegularExpression)] {
        if let cache { return cache }
        let built = Array(Set(terms)).sorted { $0.count > $1.count }.map { term in
            (term, try! NSRegularExpression(pattern: "(?<![\\p{L}\\p{N}])" + NSRegularExpression.escapedPattern(for: term) + "(?![\\p{L}\\p{N}])"))
        }
        cache = built
        return built
    }
}

func attributed(_ tokenised: String) -> AttributedString {
    var a = AttributedString(tokenised)
    let s = tokenised
    for m in tokenRE.matches(in: s, range: NSRange(s.startIndex..., in: s)) {
        let r = Range(m.range, in: s)!
        let lower = AttributedString.Index(r.lowerBound, within: a)!
        let upper = AttributedString.Index(r.upperBound, within: a)!
        a[lower..<upper].translation.skipsTranslation = true
    }
    return a
}

enum RestoreError: Error, CustomStringConvertible {
    case tokens(String)
    var description: String { switch self { case .tokens(let s): s } }
}

/// Puts the English placeholders and terms back. If the placeholders came
/// back in a different order and the English ones weren't positional, every
/// placeholder becomes positional so each still reads its own argument.
func restore(_ translated: String, _ p: Protected) throws -> String {
    let ns = translated as NSString
    let matches = tokenRE.matches(in: translated, range: NSRange(location: 0, length: ns.length))
    let found = matches.map { Int(ns.substring(with: $0.range(at: 1)))! }
    guard found.sorted() == Array(0..<p.tokens.count) else {
        throw RestoreError.tokens("tokens \(found) for \(p.tokens.count) expected")
    }
    let withArgs = p.tokens.indices.filter { p.tokens[$0].hasPlaceholder }
    let reordered = found.filter { p.tokens[$0].hasPlaceholder } != withArgs
    var out = ""
    var cursor = 0
    for (m, t) in zip(matches, found) {
        out += ns.substring(with: NSRange(location: cursor, length: m.range.location - cursor))
        let token = p.tokens[t]
        if reordered && token.hasPlaceholder {
            // Rewrite each non-positional placeholder inside as %n$….
            var i = 0
            let tns = token.original as NSString
            var piece = ""
            var c = 0
            for pm in placeholderRE.matches(in: token.original, range: NSRange(location: 0, length: tns.length)) {
                piece += tns.substring(with: NSRange(location: c, length: pm.range.location - c))
                let ph = tns.substring(with: pm.range)
                let arg = i < token.args.count ? token.args[i] : nil
                if let arg, !ph.contains("$"), !ph.hasPrefix("%#@") { piece += "%\(arg)$" + ph.dropFirst() } else { piece += ph }
                c = pm.range.location + pm.range.length
                i += 1
            }
            piece += tns.substring(from: c)
            out += piece
        } else {
            out += token.original
        }
        cursor = m.range.location + m.range.length
    }
    out += ns.substring(from: cursor)
    return out
}

func hash(_ s: String) -> String {
    SHA256.hash(data: Data(s.utf8)).prefix(8).map { String(format: "%02x", $0) }.joined()
}

func hasWords(_ english: String, terms: [String]) -> Bool {
    let p = protect(english, terms: terms)
    let rest = tokenRE.stringByReplacingMatches(in: p.text, range: NSRange(p.text.startIndex..., in: p.text), withTemplate: "")
    return rest.range(of: #"\p{L}{2}"#, options: .regularExpression) != nil
}

// MARK: - Translation

struct Job {
    let id: String          // key + "\u{1F}" + variation ("" for a plain string)
    let english: String
}

struct Result {
    var text: String?
    var back: String?
    var error: String?
}

/// Translates every segment into one language and back. Batches of 40.
func runSegments(_ jobs: [Job], apple: String, terms: [String]) async throws -> [String: Result] {
    let en = Locale.Language(identifier: "en")
    let target = Locale.Language(identifier: apple)
    let forward = TranslationSession(installedSource: en, target: target, preferredStrategy: .highFidelity)
    let backward = TranslationSession(installedSource: target, target: en, preferredStrategy: .highFidelity)
    var results: [String: Result] = [:]
    let protected = Dictionary(uniqueKeysWithValues: jobs.map { ($0.id, protect($0.english, terms: terms)) })
    for start in stride(from: 0, to: jobs.count, by: 40) {
        print("  \(apple): \(start)/\(jobs.count)"); fflush(stdout)
        let batch = Array(jobs[start..<min(start + 40, jobs.count)])
        let requests = batch.map { TranslationSession.Request(sourceText: attributed(protected[$0.id]!.text), clientIdentifier: $0.id) }
        var tokenised: [String: String] = [:]
        for r in try await forward.translations(from: requests) {
            guard let id = r.clientIdentifier else { continue }
            tokenised[id] = r.attributedTargetText.map { String($0.characters) } ?? r.targetText
        }
        for job in batch {
            let p = protected[job.id]!
            var raw = tokenised[job.id] ?? ""
            var restored = try? restore(raw, p)
            if restored == nil || signature(restored!) != signature(job.english) {
                // One retry without the attribute hints, then give up on it.
                raw = (try? await forward.translate(p.text).targetText) ?? ""
                restored = try? restore(raw, p)
            }
            if restored == nil, specs(job.english).isEmpty, !p.tokens.isEmpty,
               let plain = try? await forward.translate(job.english).targetText,
               p.tokens.allSatisfy({ plain.contains($0.original) }) {
                // Last try for plain prose: no tokens at all, accepted only if
                // every protected name came through letter for letter.
                raw = plain
                restored = plain
            }
            guard let text = restored, signature(text) == signature(job.english) else {
                results[job.id] = Result(text: nil, back: nil, error: "placeholders or terms lost: \(raw)")
                continue
            }
            tokenised[job.id] = raw
            results[job.id] = Result(text: text, back: nil, error: nil)
        }
        let backRequests = batch.compactMap { job -> TranslationSession.Request? in
            guard results[job.id]?.text != nil, let t = tokenised[job.id] else { return nil }
            return TranslationSession.Request(sourceText: attributed(t), clientIdentifier: job.id)
        }
        if !backRequests.isEmpty {
            for r in try await backward.translations(from: backRequests) {
                guard let id = r.clientIdentifier, let p = protected[id] else { continue }
                let t = r.attributedTargetText.map { String($0.characters) } ?? r.targetText
                results[id]?.back = (try? restore(t, p)) ?? t
            }
        }
    }
    return results
}

/// Languages written without spaces between sentences.
func joinsWithoutSpaces(_ apple: String) -> Bool { ["ja", "zh", "zh-TW", "th"].contains(apple) }
/// Languages without upper and lower case.
func caseless(_ apple: String) -> Bool { ["ja", "zh", "zh-TW", "ko", "th", "ar", "hi"].contains(apple) }

/// A string as the pieces the model reads best, and what goes between them.
/// A newline mid-phrase ("Out for\ndelivery", a forced break under a narrow
/// dot) becomes a space: the target language wraps on its own. Paragraph
/// breaks are kept. Long text without placeholders goes a sentence at a time
/// (one 3,000-character paragraph lost its tokens in one piece).
func segments(_ english: String) -> [(text: String, separator: String)] {
    let hasPlaceholders = !specs(english).isEmpty
    var paragraphs: [(String, String)] = []
    var current = ""
    var i = english.startIndex
    while i < english.endIndex {
        if english[i] == "\n" {
            var j = i
            while j < english.endIndex, english[j] == "\n" { j = english.index(after: j) }
            let run = String(english[i..<j])
            let last = current.last
            if run.count >= 2 || (last.map { ".!?:…)".contains($0) } ?? true) {
                if hasPlaceholders { current += run } else { paragraphs.append((current, run)); current = "" }
            } else {
                current += " "
            }
            i = j
        } else {
            current.append(english[i]); i = english.index(after: i)
        }
    }
    paragraphs.append((current, ""))
    var out: [(String, String)] = []
    let sentence = try! NSRegularExpression(pattern: #"(?<=[.!?])\s+(?=[A-Z“"(])"#)
    for (text, sep) in paragraphs {
        guard !hasPlaceholders, text.count > 280 else { out.append((text, sep)); continue }
        let ns = text as NSString
        var c = 0
        let ms = sentence.matches(in: text, range: NSRange(location: 0, length: ns.length))
        for m in ms {
            out.append((ns.substring(with: NSRange(location: c, length: m.range.location - c)), " "))
            c = m.range.location + m.range.length
        }
        out.append((ns.substring(from: c), sep))
    }
    return out
}

/// Translates every job into one language and back, piece by piece.
func run(_ jobs: [Job], apple: String, terms: [String]) async throws -> [String: Result] {
    var pieces: [Job] = []
    var layout: [String: [(String, String)]] = [:]
    for job in jobs {
        let parts = segments(job.english)
        layout[job.id] = parts.enumerated().map { ("\(job.id)\u{1D}\($0.offset)", $0.element.separator) }
        for (n, part) in parts.enumerated() where !part.text.isEmpty {
            pieces.append(Job(id: "\(job.id)\u{1D}\(n)", english: part.text))
        }
    }
    let done = try await runSegments(pieces, apple: apple, terms: terms)
    var results: [String: Result] = [:]
    for job in jobs {
        var text = "", back = "", errors: [String] = []
        for (id, sep) in layout[job.id]! {
            let joint = sep == " " && joinsWithoutSpaces(apple) ? "" : sep
            guard let r = done[id] else { text += joint; back += sep; continue }   // empty piece
            if let t = r.text { text += t + joint; back += (r.back ?? "") + sep } else { errors.append(r.error ?? "?") }
        }
        if !errors.isEmpty {
            results[job.id] = Result(text: nil, back: nil, error: errors.joined(separator: " | "))
            continue
        }
        // "you" for "You": a label that starts with a capital keeps one.
        if !caseless(apple), let f = job.english.first, f.isUppercase, let g = text.first, g.isLowercase {
            text = g.uppercased() + text.dropFirst()
        }
        results[job.id] = Result(text: text, back: back, error: nil)
    }
    return results
}

// MARK: - Files

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let catalogURL = root.appendingPathComponent("Shared/Localizable.xcstrings")
let stateURL = root.appendingPathComponent("scripts/l10n/translation-state.json")

func readJSON(_ url: URL) throws -> [String: Any] {
    try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any] ?? [:]
}

func writeJSON(_ object: Any, _ url: URL) throws {
    var data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    data.append(contentsOf: Array("\n".utf8))
    try data.write(to: url, options: .atomic)
}

func brandTerms() -> [String] {
    // Find A Crib has no brand catalog; fixedTerms covers the names.
    let url = root.appendingPathComponent("scripts/l10n/no-brands.json")
    guard let catalog = try? readJSON(url), let brands = catalog["brands"] as? [[String: Any]] else { return [] }
    let words = Set(((try? String(contentsOfFile: "/usr/share/dict/words", encoding: .utf8)) ?? "")
        .split(separator: "\n").map { $0.lowercased() })
    // A one-word brand that is also an English word ("Homebody") is left to
    // the translator: protecting it would freeze the ordinary word.
    return brands.compactMap { $0["name"] as? String }
        .filter { $0.count >= 3 && ($0.contains(" ") || !words.contains($0.lowercased())) }
}

func availability(_ apple: String) async -> LanguageAvailability.Status {
    await LanguageAvailability().status(from: Locale.Language(identifier: "en"), to: Locale.Language(identifier: apple))
}

// MARK: - Catalog mode

func translateCatalog(only: Set<String>?) async throws {
    var catalog = try readJSON(catalogURL)
    var strings = catalog["strings"] as? [String: Any] ?? [:]
    var state = (try? readJSON(stateURL)) ?? [:]
    let terms = fixedTerms + brandTerms()
    var skipped: [String] = []
    var summary: [String] = []

    // Strings with nothing to translate (only placeholders, numbers or
    // protected names) are marked so Xcode doesn't list them as missing.
    for (key, value) in strings {
        var entry = value as? [String: Any] ?? [:]
        if !hasWords(key, terms: terms), entry["shouldTranslate"] == nil {
            entry["shouldTranslate"] = false
            strings[key] = entry
        }
    }

    for (apple, lang) in catalogTargets where only == nil || only!.contains(lang) || only!.contains(apple) {
        let status = await availability(apple)
        guard status == .installed else {
            skipped.append("\(lang) (\(status == .supported ? "not downloaded" : "unsupported"))")
            continue
        }
        var langState = state[lang] as? [String: Any] ?? [:]
        var jobs: [Job] = []
        var sourceHash: [String: String] = [:]
        for (key, value) in strings {
            let entry = value as? [String: Any] ?? [:]
            if entry["shouldTranslate"] as? Bool == false { continue }
            let locs = entry["localizations"] as? [String: Any] ?? [:]
            let enUnit = locs["en"] as? [String: Any]
            // English: the key itself, or its plural variations.
            var forms: [(String, String)] = [("", key)]
            if let plural = (enUnit?["variations"] as? [String: Any])?["plural"] as? [String: Any] {
                forms = ["one", "other"].compactMap { cat in
                    ((plural[cat] as? [String: Any])?["stringUnit"] as? [String: Any])?["value"] as? String
                }.enumerated().map { (["one", "other"][$0.offset], $0.element) }
            } else if let v = (enUnit?["stringUnit"] as? [String: Any])?["value"] as? String {
                forms = [("", v)]
            }
            let h = hash(forms.map { "\($0.0)=\($0.1)" }.joined(separator: "\u{1E}"))
            sourceHash[key] = h
            let existing = locs[lang] as? [String: Any]
            let plainState = (existing?["stringUnit"] as? [String: Any])?["state"] as? String
            let pluralStates = ((existing?["variations"] as? [String: Any])?["plural"] as? [String: Any])?.values
                .compactMap { (($0 as? [String: Any])?["stringUnit"] as? [String: Any])?["state"] as? String } ?? []
            let reviewed = plainState == "translated" || (!pluralStates.isEmpty && pluralStates.allSatisfy { $0 == "translated" })
            if reviewed { continue }   // a person approved it: leave it alone
            let previous = (langState[key] as? [String: Any])?["src"] as? String
            if existing != nil && previous == h { continue }
            for (variation, text) in forms { jobs.append(Job(id: key + "\u{1F}" + variation, english: text)) }
        }
        guard !jobs.isEmpty else { summary.append("\(lang): up to date"); continue }
        let started = Date()
        let results = try await run(jobs, apple: apple, terms: terms)
        var written = 0, failed = 0
        let keys = Set(jobs.map { String($0.id.split(separator: "\u{1F}", omittingEmptySubsequences: false)[0]) })
        for key in keys {
            var entry = strings[key] as? [String: Any] ?? [:]
            var locs = entry["localizations"] as? [String: Any] ?? [:]
            let plain = results[key + "\u{1F}"]
            let one = results[key + "\u{1F}one"], other = results[key + "\u{1F}other"]
            var record: [String: Any] = ["src": sourceHash[key]!]
            if let plain {
                guard let text = plain.text else {
                    failed += 1; record["error"] = plain.error; langState[key] = record; continue
                }
                locs[lang] = ["stringUnit": ["state": "needs_review", "value": text]]
                record["back"] = plain.back ?? ""
            } else if let other, let otherText = other.text {
                var plural: [String: Any] = [:]
                for cat in pluralCategories(lang) {
                    let text = (cat == "one" ? one?.text : nil) ?? otherText
                    plural[cat] = ["stringUnit": ["state": "needs_review", "value": text]]
                }
                locs[lang] = ["variations": ["plural": plural]]
                record["back"] = other.back ?? ""
            } else {
                failed += 1; record["error"] = other?.error ?? "no result"; langState[key] = record; continue
            }
            entry["localizations"] = locs
            strings[key] = entry
            langState[key] = record
            written += 1
        }
        // Forget strings that left the catalog.
        for key in langState.keys where strings[key] == nil { langState[key] = nil }
        state[lang] = langState
        catalog["strings"] = strings
        try writeJSON(catalog, catalogURL)     // after each language: a crash keeps the work
        try writeJSON(state, stateURL)
        summary.append(String(format: "%@: %d translated, %d refused (placeholders) in %.0f s", lang, written, failed, Date().timeIntervalSince(started)))
        print(summary.last!)
    }
    catalog["strings"] = strings
    try writeJSON(catalog, catalogURL)
    print("done. " + summary.joined(separator: "; "))
    if !skipped.isEmpty {
        print("skipped (download in System Settings › General › Language & Region › Translation Languages, then re-run): " + skipped.joined(separator: ", "))
    }
}

// MARK: - Texts mode (App Store copy)

/// IN.json: {"id": "English text", …}; OUT.json: {"lang": {"id": {"text", "back"}}}.
/// `--langs` takes Apple Translation identifiers (de, fr-CA, es-MX, pt-PT, zh-TW, …).
func translateTexts(input: URL, output: URL, langs: [String]) async throws {
    let source = try readJSON(input) as? [String: String] ?? [:]
    var out = (try? readJSON(output)) ?? [:]
    let terms = fixedTerms + brandTerms()
    for apple in langs {
        guard await availability(apple) == .installed else { print("skipped \(apple): not downloaded"); continue }
        let jobs = source.sorted { $0.key < $1.key }.map { Job(id: $0.key, english: $0.value) }
        let results = try await run(jobs, apple: apple, terms: terms)
        var lang: [String: Any] = [:]
        for (id, r) in results {
            lang[id] = ["text": r.text ?? "", "back": r.back ?? "", "error": r.error ?? ""]
        }
        out[apple] = lang
        try writeJSON(out, output)
        print("\(apple): \(results.values.filter { $0.text != nil }.count)/\(jobs.count)")
    }
}

// MARK: - Main

let args = Array(CommandLine.arguments.dropFirst())
func option(_ name: String) -> String? {
    args.firstIndex(of: name).flatMap { $0 + 1 < args.count ? args[$0 + 1] : nil }
}
let langs = option("--langs")?.split(separator: ",").map(String.init)
do {
    if args.first == "texts", args.count >= 3 {
        try await translateTexts(input: URL(fileURLWithPath: args[1]), output: URL(fileURLWithPath: args[2]),
                                 langs: langs ?? catalogTargets.map(\.apple))
    } else if args.first == "status" {
        for (apple, lang) in catalogTargets { print(lang, await availability(apple)) }
    } else {
        try await translateCatalog(only: langs.map(Set.init))
    }
} catch {
    FileHandle.standardError.write(Data("error: \(error)\n".utf8))
    exit(1)
}
