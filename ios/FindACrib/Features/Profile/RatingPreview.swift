import SwiftUI

/// TestFlight's stand-in for Apple's rating sheet, drawn to look like it:
/// the icon, "Enjoying Find A Crib?", five stars and Not Now, over the app.
/// Owner, 2026-09-25: the old stand-in's button sent people to the App Store —
/// "they should get the pop up that doesnt make them leave the app".
///
/// Apple's own sheet cannot appear in TestFlight at all (`requestReview` "has
/// no effect in apps distributed for beta testing using TestFlight"); App
/// Store builds show the real one (ReviewPrompt.ask). A TestFlight rating
/// cannot be submitted anywhere, so a star just closes this, and a small
/// line says it is the preview — a tester must not think it counted.
struct RatingPreview: View {
    @Binding var isPresented: Bool
    @State private var stars = 0

    var body: some View {
        ZStack {
            Color.black.opacity(0.3).ignoresSafeArea()
            VStack(spacing: 0) {
                VStack(spacing: 6) {
                    RoundedRectangle(cornerRadius: 13).fill(SE.royal)
                        .frame(width: 60, height: 60)
                        .overlay(BrandMark().frame(width: 36, height: 36))
                        .padding(.bottom, 6)
                    Text("Enjoying Find A Crib?").font(.system(size: 17, weight: .semibold))
                    Text("Tap a star to rate it on the App Store.").font(.system(size: 13))
                        .multilineTextAlignment(.center)
                    Text("TestFlight preview").font(.system(size: 11)).foregroundStyle(.secondary).padding(.top, 2)
                }
                .padding(.horizontal, 16).padding(.top, 20).padding(.bottom, 14)
                Divider()
                HStack(spacing: 22) {
                    ForEach(1...5, id: \.self) { i in
                        Button {
                            stars = i
                            Analytics.shared.track("review_standin_star", ["stars": i])
                            Task { try? await Task.sleep(for: .milliseconds(500)); isPresented = false }
                        } label: {
                            Image(systemName: i <= stars ? "star.fill" : "star")
                                .font(.system(size: 22)).foregroundStyle(Color.accentColor)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(i) star\(i == 1 ? "" : "s")")
                        .accessibilityIdentifier("rating-star-\(i)")
                    }
                }
                .padding(.vertical, 12)
                Divider()
                Button("Not Now") { isPresented = false }
                    .font(.system(size: 17)).frame(maxWidth: .infinity).padding(.vertical, 11)
                    .accessibilityIdentifier("rating-not-now")
            }
            .frame(width: 270)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("rating-preview")
        }
        .transition(.opacity)
    }
}
