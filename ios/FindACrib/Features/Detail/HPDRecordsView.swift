import SwiftUI

/// The building's violations or complaints, one row each, on their own
/// screen. Reached from the two tiles in "Violations & complaints".
struct HPDRecordsView: View {
    enum Kind: String, Hashable { case violations, complaints }
    let building: Building
    let kind: Kind

    @State private var violations: [HPDRecords.Violation] = []
    @State private var complaints: [HPDRecords.Complaint] = []
    @State private var loading = true
    @State private var failed = false

    private var b: Building { building }
    private var title: String { kind == .violations ? "Violations" : "Complaints" }

    var body: some View {
        VStack(spacing: 0) {
            NavyBarBackdrop()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header
                    if loading {
                        HStack(spacing: 10) { ProgressView(); Text("Loading from NYC Open Data…").font(.se(17)).foregroundStyle(SE.ink2) }
                            .padding(16)
                    } else if failed {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Couldn't reach NYC Open Data just now.").font(.se(17)).foregroundStyle(SE.ink2)
                            Button("Try again") { Task { await load() } }.font(.se(17, .bold)).foregroundStyle(SE.royal)
                        }.padding(16)
                    } else {
                        rows
                    }
                    Color.clear.frame(height: 40)
                }
            }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .swipeBackEnabled()
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(title).font(.se(19, .bold)).foregroundStyle(.white)
                    Text(b.address).font(.se(13, .semibold)).foregroundStyle(.white.opacity(0.9)).lineLimit(1)
                }
                .frame(width: UIScreen.main.bounds.width - 150, alignment: .leading)
            }
        }
        .task(id: b.bbl) { await load() }
        .accessibilityIdentifier("hpd-records-\(kind.rawValue)")
    }

    private func load() async {
        loading = true; failed = false
        do {
            switch kind {
            case .violations: violations = try await HPDRecords.violations(bbl: b.bbl)
            case .complaints: complaints = try await HPDRecords.complaints(bbl: b.bbl)
            }
        } catch { failed = true }
        loading = false
    }

    // MARK: - header

    @ViewBuilder private var header: some View {
        let v = b.h?.violations, c = b.h?.complaints
        VStack(alignment: .leading, spacing: 6) {
            switch kind {
            case .violations:
                Text("\(v?.open ?? 0) open").font(.se(30, .black)).foregroundStyle(SE.ink)
                Text("NYC HPD's own Open/Close flag. HPD never closes a violation on its own — only the owner certifying the repair, or an inspector verifying it, does. So a violation nobody has touched in years is still \"open\" on the record; those rows say so.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
            case .complaints:
                Text("\(c?.open ?? 0) open").font(.se(30, .black)).foregroundStyle(SE.ink)
                Text("Problems tenants reported to 311 / HPD, newest first. A complaint is a report, not a finding — Violations are what inspectors confirmed.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white).padding(.bottom, 10)
    }

    // MARK: - rows

    @ViewBuilder private var rows: some View {
        switch kind {
        case .violations:
            if violations.isEmpty {
                note("Nothing open right now — everything HPD cited at this building has been closed out or dismissed.")
            } else {
                if violations.count >= HPDRecords.limit {
                    note("The \(HPDRecords.limit) most recent violations HPD still has open here — most serious first.")
                }
                LazyVStack(spacing: 0) { ForEach(violations) { violationRow($0) } }
                    .background(Color.white)
            }
        case .complaints:
            if complaints.isEmpty {
                note("No complaints on file — nobody has reported this building to 311 / HPD.")
            } else {
                if complaints.count >= HPDRecords.limit {
                    note("The \(HPDRecords.limit) most recent problems reported, newest first.")
                }
                LazyVStack(spacing: 0) { ForEach(complaints) { complaintRow($0) } }
                    .background(Color.white)
            }
        }
    }

    private func note(_ s: String) -> some View {
        Text(s).font(.se(15)).foregroundStyle(SE.ink2).padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
    }

    private func violationRow(_ r: HPDRecords.Violation) -> some View {
        let (cite, body) = HPDRecords.trimNotice(r.novdescription)
        let tone: Color = r.cls == "C" ? SE.bad : (r.cls == "B" ? SE.warn : SE.ink2)
        let meta = [r.issued.isEmpty ? "" : "Issued \(r.issued)",
                    (r.apartment ?? "").isEmpty ? "" : "Apt \(r.apartment!)",
                    HPDRecords.floorLabel(r.story), cite].filter { !$0.isEmpty }.joined(separator: " · ")
        let raw = (r.currentstatus ?? "").replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression).trimmingCharacters(in: .whitespaces)
        let word = HPDRecords.statusWord[raw] ?? raw.capitalized
        let years = HPDRecords.yearsSince(r.statusDate)
        let stale = (years ?? 0) >= 10
        return VStack(alignment: .leading, spacing: 5) {
            if !r.cls.isEmpty {
                Text("Class \(r.cls)" + (HPDRecords.classWord[r.cls].map { " — \($0)" } ?? ""))
                    .font(.se(13, .bold)).foregroundStyle(tone)
                    .padding(.horizontal, 8).padding(.vertical, 3).background(tone.opacity(0.1))
            }
            Text(body.isEmpty ? "No description on file." : body).font(.se(17)).foregroundStyle(SE.ink)
            if !meta.isEmpty { Text(meta).font(.se(14)).foregroundStyle(SE.ink2) }
            if !raw.isEmpty {
                if stale, let years {
                    Text("Open on record, never certified. Last HPD action: \(word.lowercased()), \(r.statusDate) — nothing since, \(years) years.")
                        .font(.se(14)).foregroundStyle(SE.warn)
                } else {
                    Text("Last HPD action: \(word)" + (r.statusDate.isEmpty ? "" : " · \(r.statusDate)")).font(.se(14)).foregroundStyle(SE.ink2)
                }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { Rectangle().fill(SE.line).frame(height: 1) }
    }

    private func complaintRow(_ r: HPDRecords.Complaint) -> some View {
        let what = [HPDRecords.titleCase(r.major_category), HPDRecords.titleCase(r.minor_category)].filter { !$0.isEmpty }.joined(separator: " — ")
        let code = HPDRecords.titleCase(r.problem_code)
        let apt = r.apartment ?? ""
        let whereTxt = (!apt.isEmpty && apt != "BLDG") ? "Apt \(apt)" : HPDRecords.titleCase(r.unit_type)
        let meta = [r.received.isEmpty ? "" : "Reported \(r.received)", whereTxt,
                    (r.type ?? "").uppercased() == "EMERGENCY" ? "Emergency" : ""].filter { !$0.isEmpty }.joined(separator: " · ")
        let note = (r.status_description ?? "").replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
            .components(separatedBy: ". ").first ?? ""
        return VStack(alignment: .leading, spacing: 5) {
            Text(r.isOpen ? "Open" : "Closed").font(.se(13, .bold)).foregroundStyle(r.isOpen ? SE.warn : SE.ink2)
                .padding(.horizontal, 8).padding(.vertical, 3).background((r.isOpen ? SE.warn : SE.ink2).opacity(0.1))
            Text((what.isEmpty ? "Complaint" : what) + (code.isEmpty || code == what ? "" : " · \(code)")).font(.se(17)).foregroundStyle(SE.ink)
            if !meta.isEmpty { Text(meta).font(.se(14)).foregroundStyle(SE.ink2) }
            if !note.isEmpty {
                Text(note + (note.hasSuffix(".") ? "" : ".") + (r.statusDate.isEmpty ? "" : " (\(r.statusDate))")).font(.se(14)).foregroundStyle(SE.ink2)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { Rectangle().fill(SE.line).frame(height: 1) }
    }
}
