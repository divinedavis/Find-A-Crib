import SwiftUI

/// Choose the city first; the Location field below then offers that city's own
/// divisions — boroughs in New York, neighborhoods in San Francisco and DC,
/// ZIP areas in Los Angeles.
///
/// Switching cities throws away the current location chips, because a Brooklyn
/// scope means nothing in a DC search and silently carrying it over would
/// return nothing with no explanation.
struct CityPickerView: View {
    @Environment(DataStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    var onSwitch: (City) -> Void

    var body: some View {
        NavigationStack {
            List(City.all) { c in
                Button {
                    let picked = c
                    dismiss()
                    onSwitch(picked)
                } label: {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(c.name).font(.se(19, c == store.city ? .bold : .semibold)).foregroundStyle(SE.ink)
                            Text(c.statusLabel).font(.se(14)).foregroundStyle(SE.ink3)
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
            .listStyle(.plain)
            .navigationTitle("City")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.font(.se(17)).foregroundStyle(SE.ink2)
                }
            }
        }
    }
}
