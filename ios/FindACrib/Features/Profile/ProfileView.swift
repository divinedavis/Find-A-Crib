import SwiftUI

struct ProfileView: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(\.openURL) private var openURL
    @AppStorage("hereTo") private var hereTo = "Rent"
    @AppStorage("homeBorough") private var homeBorough = "Brooklyn"
    @State private var refreshing = false

    var body: some View {
        VStack(spacing: 0) {
            NavyHeader {
                HStack {
                    HStack(spacing: 8) {
                        Image(systemName: "gearshape.fill").font(.system(size: 15, weight: .bold))
                        Text("Settings").font(.se(20, .bold))
                    }.foregroundStyle(.white)
                    Spacer()
                    Text("Profile").font(.se(20, .semibold)).foregroundStyle(.white)
                    Spacer()
                    Spacer().frame(width: 90)
                }
                .padding(.horizontal, 16).padding(.bottom, 14)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text("Every rent-stabilized building in New York City, in your pocket.")
                        .font(.se(17)).foregroundStyle(SE.ink).frame(maxWidth: .infinity).padding(14).background(SE.paleBand)

                    // identity
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(alignment: .top, spacing: 16) {
                            ZStack {
                                Circle().fill(SE.badge).frame(width: 74, height: 74)
                                Image(systemName: "person.fill").font(.system(size: 34)).foregroundStyle(SE.ink3)
                            }
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Guest").font(.se(30, .bold))
                                Text("Saves and searches live on this phone.").font(.se(16)).foregroundStyle(SE.ink2)
                            }
                        }
                        Button { openURL(URL(string: "https://findacrib.com/")!) } label: {
                            Text("Sign in on findacrib.com").font(.se(18, .bold)).foregroundStyle(SE.royal)
                        }.buttonStyle(.plain)
                    }.padding(16)

                    Divider()
                    settingRow("I'm here to") {
                        Picker("", selection: $hereTo) { ForEach(["Rent", "Research a building", "Organize tenants"], id: \.self) { Text($0) } }
                            .pickerStyle(.menu).tint(SE.ink).font(.se(18))
                    }
                    settingRow("Home borough") {
                        Picker("", selection: $homeBorough) { ForEach(Borough.all.map(\.name), id: \.self) { Text($0) } }
                            .pickerStyle(.menu).tint(SE.royal).font(.se(18))
                    }
                    settingRow("Saved buildings") { Text("\(activity.saved.count)").font(.se(18, .bold)) }
                    settingRow("Saved searches") { Text("\(activity.savedSearches.count)").font(.se(18, .bold)) }

                    // data
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Data").font(.se(22, .bold))
                        dataRow("Rent-stabilized buildings", store.buildings.count.formatted())
                        dataRow("With a recent asking rent", store.listings.prices.count.formatted())
                        dataRow("Voucher-friendly buildings", (store.s8.bldg.count + store.s8.avail.count).formatted())
                        dataRow("Listings as of", store.dataAsOf.map(Formatters.long.string) ?? "–")
                        Button {
                            refreshing = true
                            Task { await store.refresh(); refreshing = false }
                        } label: {
                            HStack(spacing: 8) {
                                if refreshing { ProgressView().tint(SE.royal) }
                                Text(refreshing ? "Checking findacrib.com…" : "Refresh data").font(.se(18, .bold)).foregroundStyle(SE.royal)
                            }
                        }.buttonStyle(.plain).disabled(refreshing)
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(SE.canvas)

                    VStack(alignment: .leading, spacing: 0) {
                        Text("About").font(.se(22, .bold)).padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 6)
                        linkRow("findacrib.com", "https://findacrib.com/")
                        linkRow("What is rent stabilization?", "https://findacrib.com/guide/what-is-rent-stabilization/")
                        linkRow("Is my apartment rent stabilized?", "https://findacrib.com/guide/is-my-apartment-rent-stabilized/")
                        linkRow("Tenant rights", "https://findacrib.com/guide/rent-stabilized-tenant-rights/")
                        linkRow("Developer API", "https://findacrib.com/developers")
                    }
                    Text("Find A Crib \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "") (\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "")) · Not a broker. Building data from NYS HCR and NYC HPD open data.")
                        .font(.se(13)).foregroundStyle(SE.ink3).padding(16)
                    Color.clear.frame(height: 100)
                }
            }
            .background(Color.white)
        }
        .background(Color.white)
    }

    private func settingRow<C: View>(_ k: String, @ViewBuilder _ v: () -> C) -> some View {
        VStack(spacing: 0) {
            HStack { Text(k).font(.se(19, .semibold)).foregroundStyle(SE.ink2); Spacer(); v() }
                .padding(.horizontal, 16).frame(height: 54)
            Divider().padding(.leading, 16)
        }
    }
    private func dataRow(_ k: String, _ v: String) -> some View {
        HStack { Text(k).font(.se(17)).foregroundStyle(SE.ink2); Spacer(); Text(v).font(.se(17, .bold)) }
    }
    private func linkRow(_ t: String, _ url: String) -> some View {
        Button { openURL(URL(string: url)!) } label: {
            HStack { Text(t).font(.se(18)).foregroundStyle(SE.ink); Spacer(); Image(systemName: "arrow.up.right").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.ink3) }
                .padding(.horizontal, 16).frame(height: 50)
        }.buttonStyle(.plain)
    }
}
