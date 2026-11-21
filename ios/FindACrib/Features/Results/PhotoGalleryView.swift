import SwiftUI
import UIKit

/// A listing's photos, full screen (owner, 2026-11-21: "If I touch on an
/// image it should bring up the gallery of images in full screen and u
/// should have ability to double tap to zoom and pinch to zoom").
///
/// Swipe sideways for the next photo; pinch, or double-tap a spot, to zoom
/// in on it and double-tap again to fit; tap once to hide the buttons. At
/// fit size, pull the photo down and it follows the thumb off the screen,
/// as the map's building card does. The X closes it too.
///
/// It is a see-through cover that fades itself in and out, so the page
/// stays behind the photo while it is pulled away.
struct PhotoGalleryView: View {
    let urls: [URL]
    /// A sharper copy of each photo, same order; nil where there is none.
    var sharp: [URL?] = []
    /// The photo showing; shared with the page, so closing lands on it.
    @Binding var index: Int
    let onClose: () -> Void

    @State private var shown = false
    @State private var chrome = true
    @State private var zoomed = false
    @State private var pull: CGFloat = 0
    @State private var leaving = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// How far the dark fades while the photo is pulled away.
    private var dim: Double { shown ? max(0.25, 1 - Double(pull) / 420) : 0 }

    var body: some View {
        ZStack {
            Color.black.opacity(dim).ignoresSafeArea()
            TabView(selection: $index) {
                ForEach(Array(urls.enumerated()), id: \.offset) { i, u in
                    GalleryPage(url: u, sharp: i < sharp.count ? sharp[i] : nil, active: i == index, animated: !reduceMotion,
                                onZoom: { if i == index { zoomed = $0 } },
                                onTap: { withAnimation(.easeInOut(duration: 0.18)) { chrome.toggle() } },
                                onPull: { if !leaving { pull = max(0, $0) } },
                                onRelease: release)
                        .ignoresSafeArea()      // a zoomed photo fills the screen, edge to edge
                        .tag(i)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(Text("Photo \(i + 1) of \(urls.count)"))
                        .accessibilityValue(i == index && zoomed ? Text("Zoomed in") : Text("Fits the screen"))
                        .accessibilityHint(Text("Double-tap to zoom"))
                        .accessibilityAddTraits(.isImage)
                        .accessibilityIdentifier("gallery-photo")
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .ignoresSafeArea()
            .offset(y: pull)
            .opacity(shown ? 1 : 0)
        }
        .overlay(alignment: .top) { bar.opacity(shown && chrome && pull < 8 ? 1 : 0) }
        .statusBarHidden()      // dark clock on a black screen otherwise
        .presentationBackground(.clear)
        .onChange(of: index) { _, _ in zoomed = false }
        .onAppear {
            Analytics.shared.track("photo_gallery_open", ["photos": urls.count, "start": index])
            if reduceMotion { shown = true } else { withAnimation(.easeOut(duration: 0.2)) { shown = true } }
        }
        .accessibilityAction(.escape) { close() }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("photo-gallery")
    }

    private var bar: some View {
        ZStack {
            if urls.count > 1 {
                Text("\(index + 1) / \(urls.count)").font(.se(16, .semibold)).foregroundStyle(.white)
                    .padding(.horizontal, 14).frame(height: 36)
                    .background(.black.opacity(0.45), in: Capsule())
                    .accessibilityHidden(true)
            }
            HStack {
                Button(action: close) {
                    Image(systemName: "xmark").font(.system(size: 17, weight: .semibold)).foregroundStyle(.white)
                        .frame(width: 44, height: 44).background(.black.opacity(0.45), in: Circle()).contentShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text("Close photos"))
                .accessibilityIdentifier("gallery-close")
                Spacer()
            }
        }
        .padding(.horizontal, 16).padding(.top, 6)
    }

    private func close() {
        guard !leaving else { return }
        leaving = true
        if reduceMotion { onClose(); return }
        withAnimation(.easeIn(duration: 0.16)) { shown = false } completion: { onClose() }
    }

    /// The thumb let go: far or fast enough and the photo carries on down
    /// and off the screen at the thumb's speed, otherwise it springs back.
    private func release(_ down: CGFloat, _ velocity: CGFloat) {
        guard !leaving else { return }
        guard down > 110 || velocity > 900 else {
            withAnimation(.spring(duration: 0.3)) { pull = 0 }
            return
        }
        leaving = true
        Analytics.shared.track("photo_gallery_swipe_close", ["pulled": Int(down)])
        if reduceMotion { onClose(); return }
        let target = max(UIScreen.main.bounds.height, down + 200)
        let seconds = min(0.3, max(0.14, Double((target - down) / max(velocity, 1400))))
        withAnimation(.easeOut(duration: seconds)) { pull = target; shown = false } completion: { onClose() }
    }
}

/// One photo of the gallery: the card's copy at once (it is already in
/// memory), then a sharper one worth zooming into.
private struct GalleryPage: View {
    let url: URL
    let sharp: URL?
    let active: Bool
    let animated: Bool
    let onZoom: (Bool) -> Void
    let onTap: () -> Void
    let onPull: (CGFloat) -> Void
    let onRelease: (CGFloat, CGFloat) -> Void
    @State private var image: UIImage?

    var body: some View {
        ZoomablePhoto(image: image ?? RemotePhotos.shared.cached(url), active: active, animated: animated,
                      onZoom: onZoom, onTap: onTap, onPull: onPull, onRelease: onRelease)
            // The sharp copy is only held for the photo in view (a 1600 px
            // photo is ~6 MB decoded); a page swiped away from goes back to
            // the card's copy.
            .task(id: active) {
                if image == nil || !active, let small = await RemotePhotos.shared.image(url) { image = small }
                if active, let sharp, let better = await RemotePhotos.shared.sharp(sharp) { image = better }
            }
    }
}

/// UIKit's scroll view does the zooming: its pinch tracks two fingers and
/// rubber-bands at the limits, which a SwiftUI gesture has to imitate.
private struct ZoomablePhoto: UIViewRepresentable {
    let image: UIImage?
    let active: Bool
    let animated: Bool
    let onZoom: (Bool) -> Void
    let onTap: () -> Void
    let onPull: (CGFloat) -> Void
    let onRelease: (CGFloat, CGFloat) -> Void

    func makeUIView(context: Context) -> ZoomScrollView { ZoomScrollView() }

    func updateUIView(_ v: ZoomScrollView, context: Context) {
        v.onZoom = onZoom; v.onTap = onTap; v.onPull = onPull; v.onRelease = onRelease
        v.animated = animated
        v.photo = image
        // Swiped away from: back to fit, so it is whole when swiped back to.
        if !active, v.zoomScale != v.minimumZoomScale { v.setZoomScale(v.minimumZoomScale, animated: false) }
    }
}

final class ZoomScrollView: UIScrollView, UIScrollViewDelegate, UIGestureRecognizerDelegate {
    var onZoom: (Bool) -> Void = { _ in }
    var onTap: () -> Void = {}
    var onPull: (CGFloat) -> Void = { _ in }
    var onRelease: (CGFloat, CGFloat) -> Void = { _, _ in }
    var animated = true
    var photo: UIImage? {
        didSet {
            guard photo !== oldValue else { return }
            // A sharper copy of the same photo keeps the zoom it arrives into.
            let sameShape = oldValue.map { o in photo.map { abs(o.size.width / o.size.height - $0.size.width / $0.size.height) < 0.01 } ?? false } ?? false
            imageView.image = photo
            if !sameShape { fitted = .zero; setNeedsLayout() }
        }
    }

    private let imageView = UIImageView()
    private var fitted: CGSize = .zero
    private var isZoomed = false
    private lazy var pullPan = UIPanGestureRecognizer(target: self, action: #selector(pulled(_:)))

    init() {
        super.init(frame: .zero)
        delegate = self
        showsVerticalScrollIndicator = false
        showsHorizontalScrollIndicator = false
        contentInsetAdjustmentBehavior = .never
        bouncesZoom = true
        decelerationRate = .fast
        minimumZoomScale = 1
        maximumZoomScale = 5
        backgroundColor = .clear
        imageView.contentMode = .scaleAspectFit
        addSubview(imageView)

        let double = UITapGestureRecognizer(target: self, action: #selector(doubleTapped(_:)))
        double.numberOfTapsRequired = 2
        addGestureRecognizer(double)
        let single = UITapGestureRecognizer(target: self, action: #selector(singleTapped))
        single.require(toFail: double)
        addGestureRecognizer(single)
        pullPan.delegate = self
        addGestureRecognizer(pullPan)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    /// The photo at fit size: as large as the screen allows, whole.
    private var fitSize: CGSize {
        guard let s = photo?.size, s.width > 0, s.height > 0, bounds.width > 0 else { return bounds.size }
        let k = min(bounds.width / s.width, bounds.height / s.height)
        return CGSize(width: s.width * k, height: s.height * k)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        if bounds.size != fitted, bounds.width > 0 {
            fitted = bounds.size
            zoomScale = 1
            imageView.frame = CGRect(origin: .zero, size: fitSize)
            contentSize = imageView.frame.size
        }
        // Smaller than the screen on an axis: centred on it.
        var f = imageView.frame
        f.origin.x = f.width < bounds.width ? (bounds.width - f.width) / 2 : 0
        f.origin.y = f.height < bounds.height ? (bounds.height - f.height) / 2 : 0
        imageView.frame = f
    }

    func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }

    func scrollViewDidZoom(_ scrollView: UIScrollView) {
        setNeedsLayout()
        let now = zoomScale > 1.02
        if now != isZoomed { isZoomed = now; onZoom(now) }
    }

    /// Double-tap: in on the spot that was tapped, far enough that the
    /// photo fills the screen's height; again, back to the whole photo.
    @objc private func doubleTapped(_ g: UITapGestureRecognizer) {
        if zoomScale > 1.02 {
            setZoomScale(1, animated: animated)
            return
        }
        let fit = fitSize
        let fill = fit.height > 0 ? bounds.height / fit.height : 1
        let scale = min(maximumZoomScale, max(2.5, fill))
        let p = g.location(in: imageView)
        let w = bounds.width / scale, h = bounds.height / scale
        zoom(to: CGRect(x: p.x - w / 2, y: p.y - h / 2, width: w, height: h), animated: animated)
        Analytics.shared.track("photo_gallery_zoom", ["how": "double_tap"])
    }

    @objc private func singleTapped() { onTap() }

    func scrollViewDidEndZooming(_ scrollView: UIScrollView, with view: UIView?, atScale scale: CGFloat) {
        if scale > 1.02, pinchGestureRecognizer?.state == .ended { Analytics.shared.track("photo_gallery_zoom", ["how": "pinch"]) }
    }

    // MARK: Pull down to close

    @objc private func pulled(_ g: UIPanGestureRecognizer) {
        let down = g.translation(in: self).y
        switch g.state {
        case .changed: onPull(down)
        case .ended: onRelease(max(0, down), g.velocity(in: self).y)
        case .cancelled, .failed: onRelease(0, 0)
        default: break
        }
    }

    /// Only a downward pull on the whole photo: a zoomed photo pans, and a
    /// sideways drag turns the page.
    override func gestureRecognizerShouldBegin(_ g: UIGestureRecognizer) -> Bool {
        guard g === pullPan else { return super.gestureRecognizerShouldBegin(g) }
        let v = pullPan.velocity(in: self)
        return zoomScale <= 1.02 && v.y > 0 && v.y > abs(v.x) * 1.2
    }

    /// The pager and this view's own pan wait for the pull to say no, so a
    /// pull never also drags the page sideways.
    func gestureRecognizer(_ g: UIGestureRecognizer, shouldBeRequiredToFailBy other: UIGestureRecognizer) -> Bool {
        g === pullPan && other is UIPanGestureRecognizer
    }
}
