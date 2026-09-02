import SwiftUI

struct FiltersSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(DataStore.self) private var store
    @Binding var query: SearchQuery
    @State private var draft: SearchQuery = SearchQuery()
    @State private var count = 0

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    PriceRangeFields(minPrice: $draft.minPrice, maxPrice: $draft.maxPrice)
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: "Show")
                        ShowChecklist(query: $draft)
                    }
                    if draft.availableOnly {
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Bedrooms")
                            SESegmentRow(options: [(0, "Studio"), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: $draft.beds)
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
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: "Building condition")
                        Toggle(isOn: $draft.noOpenViolations) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("No open HPD violations").font(.se(18, .semibold))
                                Text("Hide buildings with unresolved housing-code violations").font(.se(14)).foregroundStyle(SE.ink3)
                            }
                        }.tint(SE.royal).padding(14).overlay(Rectangle().stroke(SE.line))
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
                    SEOutlineButton(title: "Reset") {
                        let l = draft.locations
                        draft = SearchQuery(); draft.locations = l
                    }
                    SEPrimaryButton(title: "Show \(count.formatted()) \(draft.noun)") { query = draft; dismiss() }
                        .accessibilityIdentifier("filters-apply")
                }
                .padding(16).background(Color.white.shadow(.drop(color: .black.opacity(0.08), radius: 6, y: -2)))
            }
            .navigationTitle("Filters")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.foregroundStyle(SE.ink2) } }
            .onAppear { draft = query.normalized; recount() }
            .onChange(of: draft) { _, _ in recount() }
        }
    }
    private func recount() { count = SearchEngine.count(draft, store: store) }
}
