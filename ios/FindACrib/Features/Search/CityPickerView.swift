import SwiftUI

/// Choose the city first; the Location field below then offers that city's own
/// divisions — boroughs in New York, neighborhoods in San Francisco and DC,
/// ZIP areas in Los Angeles, towns in a state.
///
/// Two kinds of place (owner, 2026-09-24): the rent-regulated cities, each
/// with its own register, and every state's income-restricted (tax-credit)
/// buildings. They are different things, so they are listed apart, and the
/// state list can be searched — 52 rows is too many to scroll for one.
///
/// Switching cities throws away the current location chips, because a Brooklyn
/// scope means nothing in a DC search and silently carrying it over would
/// return nothing with no explanation.
struct CityPickerView: View {
    @Environment(DataStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    var onSwitch: (City) -> Void
    @State private var query = ""

    private var states: [City] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return City.states }
        return City.states.filter { $0.name.lowercased().contains(q) || $0.short.lowercased() == q }
    }
    private var cities: [City] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return City.cities }
        return City.cities.filter { $0.name.lowercased().contains(q) || $0.short.lowercased() == q }
    }

    var body: some View {
        NavigationStack {
            List {
                if !cities.isEmpty {
                    Section {
                        ForEach(cities) { row($0, sub: $0.statusLabel) }
                    } header: { header("Rent-regulated cities") }
                }
                if !states.isEmpty {
                    Section {
                        ForEach(states) { row($0, sub: nil) }
                    } header: { header("Income-restricted housing by state") }
                }
            }
            .listStyle(.plain)
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search states")
            .navigationTitle("City or state")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.font(.se(17)).foregroundStyle(SE.ink2)
                }
            }
        }
    }

    private func header(_ t: String) -> some View {
        Text(t).font(.se(14, .bold)).foregroundStyle(SE.ink3).textCase(.uppercase)
    }

    private func row(_ c: City, sub: String?) -> some View {
        Button {
            let picked = c
            dismiss()
            onSwitch(picked)
        } label: {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(c.name).font(.se(19, c == store.city ? .bold : .semibold)).foregroundStyle(SE.ink)
                    if let sub { Text(sub).font(.se(14)).foregroundStyle(SE.ink3) }
                    if c == store.city, store.loaded {
                        Text("\(store.buildings.count.formatted()) buildings")
                            .font(.se(13)).foregroundStyle(SE.ink3)
                    }
                }
                Spacer()
                if c == store.city {
                    Image(systemName: "checkmark").font(.system(size: 15, weight: .bold)).foregroundStyle(SE.royal)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("city-\(c.id)")
    }
}
