import SwiftUI

// MARK: - Buttons

struct SEPrimaryButton: View {
    let title: String
    var icon: String? = nil
    var fill: Color = SE.royal
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if let icon { Image(systemName: icon).font(.system(size: 15, weight: .bold)) }
                // One line, shrinking to fit: "Show 1,234 voucher-friendly
                // buildings" was wrapping and clipping inside the 50pt button.
                Text(title).font(.se(18, .bold)).lineLimit(1).minimumScaleFactor(0.65)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity)
            .frame(height: 50)
            .background(fill)
            .clipShape(RoundedRectangle(cornerRadius: 2))
        }
        .buttonStyle(.plain)
    }
}

struct SEOutlineButton: View {
    let title: String
    var icon: String? = nil
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if let icon { Image(systemName: icon).font(.system(size: 15, weight: .semibold)) }
                Text(title).font(.se(18, .bold))
            }
            .foregroundStyle(SE.royal)
            .frame(maxWidth: .infinity)
            .frame(height: 50)
            .background(Color.white)
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Chips and fields

struct SEChip: View {
    let text: String
    let onRemove: () -> Void
    var body: some View {
        HStack(spacing: 8) {
            Text(text).font(.se(17)).foregroundStyle(SE.ink).lineLimit(1)
            Button(action: onRemove) {
                Image(systemName: "xmark").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.ink2)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Remove \(text)")
        }
        .padding(.horizontal, 14).padding(.vertical, 8)
        .background(SE.paleBlue)
        .clipShape(Capsule())
    }
}

struct SEFieldLabel: View {
    let text: String
    var body: some View { Text(text).font(.se(20, .bold)).foregroundStyle(SE.ink2) }
}

struct SEFieldBox<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
            .background(Color.white)
            .overlay(RoundedRectangle(cornerRadius: 1).stroke(SE.line, lineWidth: 1))
    }
}

/// The Studio / 1 / 2 / 3 / 4+ strip: joined bordered cells, pale-blue when
/// selected. Multi-select, like StreetEasy.
struct SESegmentRow<T: Hashable>: View {
    let options: [(T, String)]
    @Binding var selection: Set<T>
    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(options.enumerated()), id: \.offset) { i, opt in
                let on = selection.contains(opt.0)
                Button {
                    if on { selection.remove(opt.0) } else { selection.insert(opt.0) }
                } label: {
                    Text(opt.1)
                        .font(.se(18, on ? .semibold : .regular))
                        .foregroundStyle(SE.ink)
                        .frame(maxWidth: .infinity).frame(height: 50)
                        .background(on ? SE.paleBlue : Color.white)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("segment-\(opt.1)")
                .accessibilityAddTraits(on ? .isSelected : [])
                if i < options.count - 1 { Rectangle().fill(SE.line).frame(width: 1) }
            }
        }
        .overlay(Rectangle().stroke(SE.line, lineWidth: 1))
    }
}

/// Rent / Buy / Sell style underline tabs.
struct SEUnderlineTabs<T: Hashable>: View {
    let options: [(T, String)]
    @Binding var selection: T
    var body: some View {
        VStack(spacing: 0) {
            // Each tab is exactly as wide as its word (underline included) and
            // never wraps; the words spread out with spacers. A flexible
            // underline used to split the row into equal thirds, and at larger
            // text sizes "Stabilized" broke onto two lines.
            HStack(spacing: 0) {
                ForEach(Array(options.enumerated()), id: \.offset) { i, opt in
                    let on = selection == opt.0
                    if i > 0 { Spacer(minLength: 12) }
                    Button { withAnimation(.easeInOut(duration: 0.15)) { selection = opt.0 } } label: {
                        VStack(spacing: 8) {
                            Text(opt.1).font(.se(20, .bold)).foregroundStyle(on ? SE.ink : SE.ink3)
                                .lineLimit(1).minimumScaleFactor(0.6)
                            Rectangle().fill(on ? SE.royal : .clear).frame(height: 3)
                        }
                        .fixedSize(horizontal: true, vertical: false)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("mode-\(opt.1)")
                }
            }
            .padding(.horizontal, 8)
            Rectangle().fill(SE.lineSoft).frame(height: 1)
        }
    }
}

// MARK: - Badges

struct SEBadge: View {
    let text: String
    var icon: String? = nil
    var fill: Color = SE.badge
    var ink: Color = SE.ink
    var body: some View {
        HStack(spacing: 5) {
            if let icon { Image(systemName: icon).font(.system(size: 12, weight: .bold)) }
            Text(text).font(.se(15, .semibold))
        }
        .foregroundStyle(ink)
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(fill)
    }
}

struct HeartButton: View {
    let on: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: on ? "heart.fill" : "heart")
                .font(.system(size: 24, weight: .medium))
                .foregroundStyle(SE.royal)
                .frame(width: 44, height: 44)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(on ? "Unsave" : "Save")
        .accessibilityIdentifier("heart")
    }
}

/// The ⓘ beside a number. It used to be a bare image that did nothing when
/// tapped; now it is a button that pops the explanation up in place.
struct InfoDot: View {
    var title: String = "About this number"
    var text: String = ""
    @State private var showing = false
    var body: some View {
        Button { showing = true } label: {
            Image(systemName: "info.circle").font(.system(size: 15)).foregroundStyle(SE.ink3)
                .frame(width: 32, height: 32).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .popover(isPresented: $showing, arrowEdge: .top) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.se(17, .bold)).foregroundStyle(SE.ink)
                Text(text).font(.se(16)).foregroundStyle(SE.ink2).fixedSize(horizontal: false, vertical: true)
            }
            .padding(16).frame(maxWidth: 320)
            .presentationCompactAdaptation(.popover)
        }
    }
}

// MARK: - Navy header chrome

struct NavyHeader<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(spacing: 0) {
            content
        }
        .frame(maxWidth: .infinity)
        .background(SE.navy.ignoresSafeArea(edges: .top))
    }
}

// MARK: - Floating pills (Map / Save search)

struct FloatingPill: View {
    let title: String
    let icon: String
    var fill: Color = .white
    var ink: Color = SE.royal
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: icon).font(.system(size: 17, weight: .bold))
                Text(title).font(.se(20, .bold)).lineLimit(1).fixedSize()
            }
            .foregroundStyle(ink)
            .padding(.horizontal, 22).frame(height: 56)
            .background(fill)
            .clipShape(Capsule())
            .shadow(color: .black.opacity(0.18), radius: 8, y: 3)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("pill-\(title)")
    }
}

// MARK: - Skeleton

struct ImagePlaceholder: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [SE.navy.opacity(0.85), SE.navyDeep], startPoint: .topLeading, endPoint: .bottomTrailing)
            Image(systemName: "building.2.fill").font(.system(size: 44)).foregroundStyle(.white.opacity(0.25))
        }
    }
}

/// Aspect-fill an image WITHOUT letting it inflate the layout. A bare
/// `.scaledToFill()` reports a size larger than its proposal in one axis,
/// which widened the whole home screen past the display; an overlay on a
/// clear colour takes exactly the proposed size and clips the overflow.
struct FillImage: View {
    let image: UIImage
    var body: some View {
        Color.clear
            .overlay(Image(uiImage: image).resizable().scaledToFill())
            .clipped()
    }
}


/// Radio group in StreetEasy's bordered-row style: one selected at a time,
/// a filled royal dot for the pick, a hollow ring for the rest.
struct SERadioRow<T: Hashable>: View {
    let options: [(T, String, String)]   // value, title, subtitle
    @Binding var selection: T
    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(options.enumerated()), id: \.offset) { i, opt in
                let on = selection == opt.0
                Button { selection = opt.0 } label: {
                    HStack(spacing: 14) {
                        ZStack {
                            Circle().stroke(on ? SE.royal : SE.line, lineWidth: 2).frame(width: 22, height: 22)
                            if on { Circle().fill(SE.royal).frame(width: 12, height: 12) }
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Text(opt.1).font(.se(18, on ? .bold : .semibold)).foregroundStyle(SE.ink)
                            Text(opt.2).font(.se(14)).foregroundStyle(SE.ink3)
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 14).frame(minHeight: 60)
                    .background(on ? SE.paleBlue.opacity(0.55) : Color.white)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("radio-\(opt.1)")
                .accessibilityAddTraits(on ? .isSelected : [])
                if i < options.count - 1 { Rectangle().fill(SE.line).frame(height: 1) }
            }
        }
        .overlay(Rectangle().stroke(SE.line, lineWidth: 1))
    }
}


/// Checkbox list in the bordered-row style. `locked` rows draw checked and
/// don't toggle — used for the "Rent stabilized" baseline.
struct SECheckList: View {
    struct Row { let title: String; let subtitle: String; let isOn: Binding<Bool>; var locked = false }
    let rows: [Row]
    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                let on = r.isOn.wrappedValue
                Button { if !r.locked { r.isOn.wrappedValue.toggle() } } label: {
                    HStack(spacing: 14) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 4).stroke(on ? SE.royal : SE.line, lineWidth: 2).frame(width: 22, height: 22)
                            if on { RoundedRectangle(cornerRadius: 4).fill(SE.royal).frame(width: 22, height: 22)
                                Image(systemName: "checkmark").font(.system(size: 13, weight: .black)).foregroundStyle(.white) }
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.title).font(.se(18, on ? .bold : .semibold)).foregroundStyle(SE.ink)
                            Text(r.subtitle).font(.se(13)).foregroundStyle(SE.ink3).lineLimit(1).minimumScaleFactor(0.85)
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 14).padding(.vertical, 8).frame(minHeight: 52)
                    .background(on && !r.locked ? SE.paleBlue.opacity(0.55) : Color.white)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                // locked rows stay full-contrast: the action is a no-op, and
                // .disabled would grey the baseline out as if it were unavailable
                .accessibilityIdentifier("check-\(r.title)")
                .accessibilityAddTraits(on ? .isSelected : [])
                if i < rows.count - 1 { Rectangle().fill(SE.line).frame(height: 1) }
            }
        }
        .overlay(Rectangle().stroke(SE.line, lineWidth: 1))
    }
}
