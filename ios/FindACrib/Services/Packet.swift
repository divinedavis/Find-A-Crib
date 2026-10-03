import Foundation
import Observation
import PDFKit
import UIKit

/// The application packet (owner, 2026-10-03: "lets build what we can
/// build"). Everything a re-rental agent asks for, kept ON THIS PHONE ONLY:
/// a profile filled in once and the documents scanned or imported, as PDFs
/// in Application Support with complete file protection (unreadable while
/// the phone is locked). Nothing is uploaded — the renter sends it to the
/// agent from their own Mail — so the App Privacy label doesn't change.
///
/// Deliberately NOT here: a Social Security number field, signing, or
/// submitting for them. Applicants certify their own application; a filled
/// form is left for them to check and sign.
@Observable @MainActor
final class Packet {
    static let shared = Packet()

    struct Member: Codable, Hashable, Identifiable {
        var id = UUID()
        var name = ""
        var relation = ""
        var yearlyIncome: Int?
    }

    struct Profile: Codable, Equatable {
        var firstName = ""
        var lastName = ""
        var email = ""
        var phone = ""
        var street = ""
        var city = ""
        var state = "NY"
        var zip = ""
        var employer = ""
        var jobTitle = ""
        var yearlyIncome: Int?
        var currentRent: Int?
        var landlord = ""
        var others: [Member] = []

        var fullName: String { [firstName, lastName].filter { !$0.isEmpty }.joined(separator: " ") }
        var householdSize: Int { 1 + others.count }
        var householdIncome: Int? {
            let all = [yearlyIncome] + others.map(\.yearlyIncome)
            let known = all.compactMap { $0 }
            return known.isEmpty ? nil : known.reduce(0, +)
        }
        var address: String {
            [street, [city, [state, zip].filter { !$0.isEmpty }.joined(separator: " ")].filter { !$0.isEmpty }.joined(separator: ", ")]
                .filter { !$0.isEmpty }.joined(separator: ", ")
        }
    }

    enum Kind: String, Codable, CaseIterable, Identifiable {
        case id, payStubs, taxReturn, employmentLetter, bankStatements, benefits, other
        var id: String { rawValue }
        var title: String {
            switch self {
            case .id: "Photo ID"
            case .payStubs: "Recent pay stubs"
            case .taxReturn: "Last year's tax return"
            case .employmentLetter: "Employment letter"
            case .bankStatements: "Bank statements"
            case .benefits: "Benefits or child-support letters"
            case .other: "Other document"
            }
        }
        var icon: String {
            switch self {
            case .id: "person.text.rectangle"
            case .payStubs: "banknote"
            case .taxReturn: "doc.text"
            case .employmentLetter: "briefcase"
            case .bankStatements: "building.columns"
            case .benefits: "envelope.open"
            case .other: "doc"
            }
        }
        /// Words an agent's document list uses for this kind.
        var words: [String] {
            switch self {
            case .id: ["photo id", "identification", "id", "ids", "government-issued", "driver", "passport", "state id"]
            case .payStubs: ["pay stub", "paystub", "pay stubs", "paycheck", "earnings statement"]
            case .taxReturn: ["tax return", "1040", "w-2", "w2", "tax transcript", "1099"]
            case .employmentLetter: ["employment letter", "employer letter", "letter from employer", "verification of employment", "employment verification"]
            case .bankStatements: ["bank statement", "bank statements", "assets", "checking", "savings"]
            case .benefits: ["benefit", "social security award", "ssi", "ssdi", "child support", "pension", "public assistance", "unemployment"]
            case .other: []
            }
        }
    }

    struct Doc: Codable, Hashable, Identifiable {
        var id = UUID()
        var kind: Kind
        var title: String
        var file: String
        var pages: Int
        var added: Date
    }

    private struct Saved: Codable { var profile: Profile; var docs: [Doc] }

    private(set) var profile = Profile()
    private(set) var docs: [Doc] = []

    nonisolated static var folder: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Packet", isDirectory: true)
    }
    private static var index: URL { folder.appendingPathComponent("packet.json") }

    init() {
        try? FileManager.default.createDirectory(at: Self.folder, withIntermediateDirectories: true,
                                                 attributes: [.protectionKey: FileProtectionType.complete])
        if let d = try? Data(contentsOf: Self.index), let s = try? JSONDecoder().decode(Saved.self, from: d) {
            profile = s.profile; docs = s.docs
        }
    }

    private func save() {
        guard let d = try? JSONEncoder().encode(Saved(profile: profile, docs: docs)) else { return }
        try? d.write(to: Self.index, options: [.atomic, .completeFileProtection])
    }

    func update(_ p: Profile) { profile = p; save() }

    func url(_ d: Doc) -> URL { Self.folder.appendingPathComponent(d.file) }

    /// Adds scanned pages or an imported image/PDF as one PDF document.
    @discardableResult
    func add(kind: Kind, images: [UIImage] = [], pdf: Data? = nil, title: String? = nil) -> Doc? {
        let doc: PDFDocument
        if let pdf, let d = PDFDocument(data: pdf) { doc = d }
        else {
            doc = PDFDocument()
            for (i, img) in images.enumerated() { if let page = PDFPage(image: img) { doc.insert(page, at: i) } }
        }
        guard doc.pageCount > 0, let data = doc.dataRepresentation() else { return nil }
        let n = docs.filter { $0.kind == kind }.count
        let name = "\(kind.rawValue)-\(UUID().uuidString.prefix(8)).pdf"
        do { try data.write(to: Self.folder.appendingPathComponent(name), options: [.atomic, .completeFileProtection]) } catch { return nil }
        let d = Doc(kind: kind, title: title ?? (n == 0 ? kind.title : "\(kind.title) \(n + 1)"), file: name, pages: doc.pageCount, added: Date())
        docs.append(d); save()
        Analytics.shared.track("packet_doc_added", ["kind": kind.rawValue, "pages": d.pages])
        return d
    }

    func remove(_ d: Doc) {
        try? FileManager.default.removeItem(at: url(d))
        docs.removeAll { $0.id == d.id }; save()
    }

    /// Deletes the whole packet (profile and every document).
    func eraseAll() {
        for d in docs { try? FileManager.default.removeItem(at: url(d)) }
        docs = []; profile = Profile(); save()
        Analytics.shared.track("packet_erased")
    }

    var isEmpty: Bool { docs.isEmpty && profile == Profile() }

    // MARK: matching a listing's document list

    /// The kind an agent's document line asks for, or nil when it's
    /// something the packet has no slot for (an application form, a fee).
    nonisolated static func kind(for item: String) -> Kind? {
        let t = item.lowercased()
        return Kind.allCases.first { k in
            k.words.contains { t.range(of: "\\b" + NSRegularExpression.escapedPattern(for: $0) + "\\b", options: .regularExpression) != nil }
        }
    }

    struct Need: Identifiable, Hashable { let item: String; let kind: Kind?; let have: Bool; var id: String { item } }

    func needs(_ items: [String]) -> [Need] {
        let kinds = Set(docs.map(\.kind))
        return items.map { i in
            let k = Self.kind(for: i)
            return Need(item: i, kind: k, have: k.map(kinds.contains) ?? false)
        }
    }

    // MARK: filling a fillable PDF form

    /// Profile value for a form field name, or nil to leave it blank.
    /// Never fills SSN, date of birth, signature or date fields.
    nonisolated static func value(forField raw: String, profile p: Profile) -> String? {
        let f = raw.lowercased().replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: ".", with: " ")
        let has = { (w: String) in f.contains(w) }
        if ["ssn", "social", "security", "birth", "dob", "sign", "date", "signature", "initial"].contains(where: has) { return nil }
        // Rows for other household members ("member 2 name") are theirs to fill.
        if f.range(of: #"(member|occupant|person|resident)\s*#?\s*[2-9]"#, options: .regularExpression) != nil { return nil }
        func nonEmpty(_ s: String) -> String? { s.isEmpty ? nil : s }
        if has("email") || has("e-mail") { return nonEmpty(p.email) }
        if has("phone") || has("tel") || has("cell") || has("mobile") { return nonEmpty(p.phone) }
        if has("household size") || has("number of persons") || has("household members") || has("# in household") || has("family size") { return String(p.householdSize) }
        if has("household income") || has("total income") || has("annual household") { return p.householdIncome.map(String.init) }
        if has("income") || has("salary") || has("annual") || has("wages") { return p.yearlyIncome.map(String.init) }
        if has("employer") || has("company") { return nonEmpty(p.employer) }
        if has("title") || has("position") || has("occupation") { return nonEmpty(p.jobTitle) }
        if has("landlord") { return nonEmpty(p.landlord) }
        if has("zip") || has("postal") { return nonEmpty(p.zip) }
        if has("city") || has("town") { return nonEmpty(p.city) }
        if f.range(of: #"\bstate\b"#, options: .regularExpression) != nil { return nonEmpty(p.state) }
        if has("street") || has("address") { return nonEmpty(p.street.isEmpty ? p.address : p.street) }
        // "rent" as a word: "current address" and "parent" contain it too.
        if f.range(of: #"\brent\b"#, options: .regularExpression) != nil { return p.currentRent.map(String.init) }
        if has("first") && has("name") { return nonEmpty(p.firstName) }
        if (has("last") || has("sur")) && has("name") { return nonEmpty(p.lastName) }
        if has("name") && !has("employer") && !has("landlord") { return nonEmpty(p.fullName) }
        return nil
    }

    /// Fills every text field the profile answers. Returns (filled, total).
    @discardableResult
    static func fill(_ doc: PDFDocument, profile: Profile) -> (filled: Int, total: Int) {
        var filled = 0, total = 0
        for i in 0..<doc.pageCount {
            guard let page = doc.page(at: i) else { continue }
            for a in page.annotations where a.widgetFieldType == .text {
                total += 1
                guard (a.widgetStringValue ?? "").isEmpty, let name = a.fieldName,
                      let v = value(forField: name, profile: profile) else { continue }
                a.widgetStringValue = v
                filled += 1
            }
        }
        return (filled, total)
    }
}
