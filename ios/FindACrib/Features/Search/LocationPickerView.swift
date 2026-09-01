import SwiftUI

struct LocationPickerView: View {
    @Environment(DataStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @Binding var selected: [LocationScope]
    @State private var text = ""

    private var q: String { text.trimmingCharacters(in: .whitespaces).lowercased() }
    private var boroughs: [(code: String, name: String)] {
        q.isEmpty ? Borough.all : Borough.all.filter { $0.name.lowercased().contains(q) }
    }
    private var neighborhoods: [(name: String, borough: String, count: Int)] {
        q.isEmpty ? store.neighborhoods : store.neighborhoods.filter { $0.name.lowercased().contains(q) }
    }
    private var zips: [String] {
        guard !q.isEmpty, q.allSatisfy(\.isNumber) else { return [] }
        return store.zips.filter { $0.hasPrefix(q) }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "magnifyingglass").foregroundStyle(SE.ink3)
                    TextField("Neighborhood, borough or ZIP", text: $text).font(.se(18))
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
                    if !boroughs.isEmpty {
                        Section(header: header("Boroughs")) {
                            ForEach(boroughs, id: \.code) { b in row(.borough(b.code), title: b.name, sub: "\(store.buildings.lazy.filter { $0.b == b.code }.count.formatted()) buildings") }
                        }
                    }
                    if !zips.isEmpty {
                        Section(header: header("ZIP codes")) {
                            ForEach(zips.prefix(20), id: \.self) { z in row(.zip(z), title: z, sub: nil) }
                        }
                    }
                    Section(header: header("Neighborhoods")) {
                        ForEach(neighborhoods.prefix(q.isEmpty ? 400 : 60), id: \.name) { n in
                            row(.neighborhood(n.name), title: n.name, sub: "\(n.borough) · \(n.count.formatted())")
                        }
                    }
                }
                .listStyle(.plain)
            }
            .background(Color.white)
            .navigationTitle("Location")
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
