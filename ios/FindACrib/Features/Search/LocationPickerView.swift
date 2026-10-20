import SwiftUI

struct LocationPickerView: View {
    @Environment(DataStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @Binding var selected: [LocationScope]
    /// Bedrooms, vouchers or a rent cap typed into the box ("2 bedroom",
    /// "voucher") turn on the matching filters through this (2026-10-19).
    var applyIntent: ((SearchText.Intent) -> Void)? = nil
    @State private var text = ""

    private var raw: String { text.trimmingCharacters(in: .whitespaces) }
    private var intent: SearchText.Intent? { store.city.isNYC ? SearchText.intent(raw) : nil }
    /// The place part of what was typed: filler ("rent stabilized", "ny")
    /// and filter words dropped, "bronx 10453" read as its ZIP.
    private var q: String {
        let place = SearchText.stripFiller(intent?.rest ?? raw).lowercased()
        return SearchText.zipFromPlace(place) ?? place
    }
    /// Only words that restate the app: "rent", "rent stabilized", "nyc".
    private var fillerOnly: Bool { !raw.isEmpty && q.isEmpty && intent == nil }
    private var elsewhere: SearchText.Elsewhere? { store.city.isNYC ? SearchText.elsewhere(q) : nil }
    private var boroughs: [(code: String, name: String)] {
        if q.isEmpty { return Borough.all }
        let alias = SearchText.boroughAliases[SearchText.flat(q)]
        return Borough.all.filter { $0.name.lowercased().contains(q) || $0.code == alias }
    }
    private var neighborhoods: [(name: String, borough: String, count: Int)] {
        if q.isEmpty { return store.neighborhoods }
        let alias = Set(SearchText.aliases[SearchText.flat(q)] ?? [])
        return store.neighborhoods.filter { alias.contains($0.name) || $0.name.lowercased().contains(q) }
    }
    private var zips: [String] {
        guard !q.isEmpty, q.allSatisfy(\.isNumber) else { return [] }
        return store.zips.filter { $0.hasPrefix(q) }
    }
    private var nothingMatches: Bool { !q.isEmpty && boroughs.isEmpty && neighborhoods.isEmpty && zips.isEmpty }
    /// Outside New York the register divides the city differently — named
    /// neighborhoods in SF and DC, ZIP areas in LA, whose parcel source has no
    /// neighborhood at all — so the picker offers whatever that city has.
    private var regions: [(name: String, sub: String, count: Int)] {
        q.isEmpty ? store.regions : store.regions.filter { $0.name.lowercased().contains(q) }
    }
    private var scopeKind: City.RegionKind { store.city.regionKind }
    private func scope(_ name: String) -> LocationScope {
        switch scopeKind {
        case .borough: return .borough(Borough.all.first { $0.name == name }?.code ?? name)
        case .neighborhood: return .neighborhood(name)
        case .zip: return .zip(name)
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "magnifyingglass").foregroundStyle(SE.ink3)
                    TextField(store.city.searchPlaceholder, text: $text).font(.se(18))
                        .textInputAutocapitalization(.words).autocorrectionDisabled()
                        .accessibilityIdentifier("location-search")
                    if !text.isEmpty { Button { text = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(SE.ink3) } }
                }
                .padding(12).background(Color.white).overlay(RoundedRectangle(cornerRadius: 1).stroke(SE.line))
                .padding(16)

                if !selected.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(selected, id: \.self) { loc in SEChip(text: loc.label) { selected.removeAll { $0 == loc } } }
                        }.padding(.horizontal, 16)
                    }.padding(.bottom, 8)
                }

                List {
                    if let i = intent, applyIntent != nil {
                        Section(header: header(String(localized: "Filters"))) {
                            Button {
                                applyIntent?(i)
                                Analytics.shared.track("search_intent", ["beds": i.beds.count, "s8": i.vouchers, "pmax": i.maxRent != nil, "rest": !i.rest.isEmpty])
                                text = i.rest
                            } label: {
                                Label(String(localized: "Turn on: \(i.summary)"), systemImage: "line.3.horizontal.decrease.circle.fill")
                                    .font(.se(17, .semibold)).foregroundStyle(SE.royal)
                            }
                            .accessibilityIdentifier("location-intent")
                        }
                    }
                    if fillerOnly {
                        Text("Every building here is rent-stabilized — that’s all Find A Crib shows. Pick an area below, or use Filters for bedrooms and price.")
                            .font(.se(15)).foregroundStyle(SE.ink2)
                            .accessibilityIdentifier("location-filler")
                    }
                    if let e = elsewhere {
                        switch e {
                        case .westchester:
                            Link(destination: URL(string: "https://findacrib.com/westchester/?q=\(q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")")!) {
                                Label(String(localized: "Westchester isn’t in the app yet — see the Yonkers & Westchester map on findacrib.com"), systemImage: "safari")
                                    .font(.se(16)).foregroundStyle(SE.royal)
                            }
                            .accessibilityIdentifier("location-westchester")
                        case .outside(let place):
                            Text("Find A Crib doesn’t cover \(place) yet.").font(.se(15)).foregroundStyle(SE.ink2)
                                .accessibilityIdentifier("location-outside")
                        }
                    } else if store.city.isNYC && nothingMatches && store.loaded {
                        Text("Nothing matches that. Try a borough, a neighborhood or a ZIP.").font(.se(15)).foregroundStyle(SE.ink3)
                            .accessibilityIdentifier("location-nomatch")
                    }
                    if store.city.isNYC {
                        if !boroughs.isEmpty {
                            Section(header: header(String(localized: "Boroughs"))) {
                                ForEach(boroughs, id: \.code) { b in row(.borough(b.code), title: b.name, sub: String(localized: "\((store.boroughCounts[b.code] ?? 0).formatted()) buildings")) }
                            }
                        }
                        if !zips.isEmpty {
                            Section(header: header(String(localized: "ZIP codes"))) {
                                ForEach(zips.prefix(20), id: \.self) { z in row(.zip(z), title: z, sub: nil) }
                            }
                        }
                        Section(header: header(String(localized: "Neighborhoods"))) {
                            ForEach(neighborhoods.prefix(q.isEmpty ? 400 : 60), id: \.name) { n in
                                row(.neighborhood(n.name), title: n.name, sub: "\(n.borough) · \(n.count.formatted())")
                            }
                        }
                    } else {
                        // Typing digits in a neighborhood city also finds ZIPs.
                        if scopeKind != .zip, !zips.isEmpty {
                            Section(header: header(String(localized: "ZIP codes"))) {
                                ForEach(zips.prefix(20), id: \.self) { z in row(.zip(z), title: String(localized: "ZIP \(z)"), sub: nil) }
                            }
                        }
                        Section(header: header(store.city.regionLabel + "s")) {
                            if regions.isEmpty {
                                Text(store.loaded ? String(localized: "Nothing matches that.") : String(localized: "Loading \(store.city.name)…"))
                                    .font(.se(16)).foregroundStyle(SE.ink3)
                            }
                            ForEach(regions.prefix(q.isEmpty ? 400 : 60), id: \.name) { r in
                                row(scope(r.name),
                                    title: scopeKind == .zip ? String(localized: "ZIP \(r.name)") : r.name,
                                    sub: String(localized: "\(r.count.formatted()) buildings"))
                            }
                        }
                    }
                }
                .listStyle(.plain)
            }
            .background(Color.white)
            .navigationTitle(store.city.isNYC ? String(localized: "Location") : store.city.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }.font(.se(18, .bold)).foregroundStyle(SE.royal).accessibilityIdentifier("location-done")
                }
                ToolbarItem(placement: .cancellationAction) {
                    if !selected.isEmpty { Button("Clear") { selected = [] }.font(.se(17)).foregroundStyle(SE.ink2) }
                }
            }
        }
    }

    private func header(_ t: String) -> some View {
        Text(t).font(.se(15, .bold)).foregroundStyle(SE.ink3).textCase(nil)
    }

    private func row(_ scope: LocationScope, title: String, sub: String?) -> some View {
        let on = selected.contains(scope)
        return Button {
            if on { selected.removeAll { $0 == scope } }
            else { selected.removeAll { if case .mapArea = $0 { return true }; return false }; selected.append(scope) }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.se(18, on ? .bold : .regular)).foregroundStyle(SE.ink)
                    if let sub { Text(sub).font(.se(14)).foregroundStyle(SE.ink3) }
                }
                Spacer()
                if on { Image(systemName: "checkmark").font(.system(size: 15, weight: .bold)).foregroundStyle(SE.royal) }
            }
            // A plain-style Button is only hittable on its opaque content, so a
            // tap in the gap between the name and the checkmark did nothing.
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("loc-\(title)")
    }
}
