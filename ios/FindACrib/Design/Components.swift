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
                Text(title).font(.se(18, .bold))
            }
            .foregroundStyle(.white)
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

struct InfoDot: View {
    var body: some View {
        Image(systemName: "info.circle").font(.system(size: 15)).foregroundStyle(SE.ink3)
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
                Text(title).font(.se(20, .bold))
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
