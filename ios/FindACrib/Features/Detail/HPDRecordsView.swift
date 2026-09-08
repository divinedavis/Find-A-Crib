import SwiftUI

/// The building's violations, complaints, bedbug filings or rodent
/// inspections, one row each, on their own screen. Reached from the four
/// tiles in "Violations & inspections" (signed-in only).
struct HPDRecordsView: View {
    enum Kind: String, Hashable { case violations, complaints, bedbugs, rodents }
    let building: Building
    let kind: Kind

    @State private var violations: [HPDRecords.Violation] = []
    @State private var complaints: [HPDRecords.Complaint] = []
    @State private var bedbugs: [HPDRecords.BedbugFiling] = []
    @State private var rodents: [HPDRecords.RodentInspection] = []
    @State private var loading = true
    @State private var failed = false

    private var b: Building { building }
    private var title: String {
        switch kind {
        case .violations: "Violations"
        case .complaints: "Complaints"
        case .bedbugs: "Bedbug inspections"
        case .rodents: "Rodent inspections"
        }
    }

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
            case .bedbugs: bedbugs = try await HPDRecords.bedbugs(bbl: b.bbl)
            case .rodents: rodents = try await HPDRecords.rodents(bbl: b.bbl)
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
            case .bedbugs:
                let s = HPDRecords.summary(bedbugs: bedbugs)
                if !loading {
                    Text(s.clean ? "None found this year" : "\(s.problemsThisYear) filing\(s.problemsThisYear == 1 ? "" : "s") with bedbugs this year")
                        .font(.se(30, .black)).foregroundStyle(s.clean ? SE.good : SE.bad)
                }
                Text("Every multiple dwelling must report its bedbug history to HPD once a year — how many units had bedbugs, how many were re-infested, how many were treated. Newest filing first.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
            case .rodents:
                let s = HPDRecords.summary(rodents: rodents)
                if !loading {
                    Text(s.clean ? "None failed this year" : "\(s.problemsThisYear) failed this year")
                        .font(.se(30, .black)).foregroundStyle(s.clean ? SE.good : SE.bad)
                }
                Text("Health Department rodent inspections, newest first. \"Rat activity\" or \"failed\" means the inspector found signs of rats; a passed compliance visit means the problem was fixed.")
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
        case .bedbugs:
            if bedbugs.isEmpty {
                note("No bedbug filings on record for this building.")
            } else {
                if bedbugs.count >= HPDRecords.limit { note("The \(HPDRecords.limit) most recent annual filings, newest first.") }
                LazyVStack(spacing: 0) { ForEach(bedbugs) { bedbugRow($0) } }
                    .background(Color.white)
            }
        case .rodents:
            if rodents.isEmpty {
                note("No rodent inspections on record for this building.")
            } else {
                if rodents.count >= HPDRecords.limit { note("The \(HPDRecords.limit) most recent inspections, newest first.") }
                LazyVStack(spacing: 0) { ForEach(rodents) { rodentRow($0) } }
                    .background(Color.white)
            }
        }
    }

    private func bedbugRow(_ r: HPDRecords.BedbugFiling) -> some View {
        let tone: Color = r.hadBedbugs ? SE.bad : SE.good
        let extras = [r.reinfested > 0 ? "\(r.reinfested) re-infested" : "", r.treated > 0 ? "\(r.treated) treated" : ""].filter { !$0.isEmpty }
        return VStack(alignment: .leading, spacing: 5) {
            Text(r.hadBedbugs ? "Bedbugs reported" : "None reported").font(.se(13, .bold)).foregroundStyle(tone)
                .padding(.horizontal, 8).padding(.vertical, 3).background(tone.opacity(0.1))
            Text("\(r.infested) of \(r.units) unit\(r.units == 1 ? "" : "s") infested" + (extras.isEmpty ? "" : " · " + extras.joined(separator: " · ")))
                .font(.se(17)).foregroundStyle(SE.ink)
            Text(["Filed \(r.filed)", r.periodStart.isEmpty ? "" : "covers \(r.periodStart) – \(r.periodEnd)"].filter { !$0.isEmpty }.joined(separator: " · "))
                .font(.se(14)).foregroundStyle(SE.ink2)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { Rectangle().fill(SE.line).frame(height: 1) }
    }

    private func rodentRow(_ r: HPDRecords.RodentInspection) -> some View {
        let tone: Color = r.failed ? SE.bad : SE.good
        return VStack(alignment: .leading, spacing: 5) {
            Text(r.result ?? "Inspection").font(.se(13, .bold)).foregroundStyle(tone)
                .padding(.horizontal, 8).padding(.vertical, 3).background(tone.opacity(0.1))
            Text(r.inspection_type ?? "Inspection").font(.se(17)).foregroundStyle(SE.ink)
            if !r.date.isEmpty { Text("Inspected \(r.date)").font(.se(14)).foregroundStyle(SE.ink2) }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { Rectangle().fill(SE.line).frame(height: 1) }
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
