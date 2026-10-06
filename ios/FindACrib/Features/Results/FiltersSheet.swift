import SwiftUI

struct FiltersSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(DataStore.self) private var store
    @Binding var query: SearchQuery
    @State private var draft: SearchQuery = SearchQuery()
    @State private var count = 0
    @State private var counted = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    PriceRangeFields(minPrice: $draft.minPrice, maxPrice: $draft.maxPrice)
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: "Show")
                        ShowChecklist(query: $draft)
                    }
                    // Bedrooms narrow the re-rentals, which are New York's,
                    // so outside NYC every size matches nothing.
                    if store.city.hasNYCExtras {
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Bedrooms")
                            SESegmentRow(options: [(0, "Studio"), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: $draft.beds)
                            Text("Narrows the re-rentals to the sizes you pick. Building records don't say what sizes their apartments are.")

                                .font(.se(14)).foregroundStyle(SE.ink3)
                        }
                    }
                    if draft.vouchersOnly {
                        Toggle(isOn: $draft.voucherLiveOnly) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Accepting vouchers right now").font(.se(18, .semibold))
                                Text("Live listings on AffordableHousing.com only").font(.se(14)).foregroundStyle(SE.ink3)
                            }
                        }.tint(SE.royal).padding(14).overlay(Rectangle().stroke(SE.line))
                    }
                    // HPD violation counts ride on the New York building rows;
                    // the other cities publish their own records, not these.
                    if store.city.isNYC {
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Building condition")
                            Toggle(isOn: $draft.noOpenViolations) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("No open HPD violations").font(.se(18, .semibold))
                                    Text("Hide buildings with unresolved housing-code violations").font(.se(14)).foregroundStyle(SE.ink3)
                                }
                            }.tint(SE.royal).padding(14).overlay(Rectangle().stroke(SE.line))
                        }
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: "Sort")
                        Picker("Sort", selection: $draft.sort) {
                            ForEach(SortOrder.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                        }.pickerStyle(.menu).tint(SE.royal).font(.se(18))
                    }
                    Color.clear.frame(height: 80)
                }
                .padding(16)
            }
            .background(Color.white)
            .scrollDismissesKeyboard(.interactively)
            .safeAreaInset(edge: .bottom) {
                HStack(spacing: 12) {
                    // Reset takes only the width it needs; the Show button gets the rest.
                    SEOutlineButton(title: "Reset") {
                        let l = draft.locations
                        draft = SearchQuery(); draft.locations = l
                    }
                    .fixedSize(horizontal: true, vertical: false)
                    SEPrimaryButton(title: "Show \(count.formatted()) \(draft.noun)") {
                        var p = Analytics.shape(draft); p["results"] = count
                        Analytics.shared.track("filters_apply", p)
                        query = draft; dismiss()
                    }
                        .accessibilityIdentifier("filters-apply")
                }
                .padding(16).background(Color.white.shadow(.drop(color: .black.opacity(0.08), radius: 6, y: -2)))
            }
            .navigationTitle("Filters")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.foregroundStyle(SE.ink2) } }
            .onAppear { draft = query.normalized }
            // Each count is a scan of the whole city — now on a background
            // task across every core; quick taps still coalesce into one.
            .task(id: draft) {
                if counted { try? await Task.sleep(for: .milliseconds(150)) }
                guard !Task.isCancelled else { return }
                let n = await SearchEngine.countAsync(draft, store: store)
                if !Task.isCancelled { count = n; counted = true }
            }
        }
    }
}
