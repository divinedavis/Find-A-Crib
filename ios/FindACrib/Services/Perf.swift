import Foundation
import os

/// Wall-clock spans for the paths that have to stay off the main thread's
/// critical section — screen pushes, pops and list rebuilds.
///
/// Off unless the app is launched with `--perf`, so nothing in a shipping
/// build pays for it. Read the output with:
///
///     xcrun simctl spawn booted log stream --predicate \
///       'subsystem == "com.divinedavis.findacrib" && category == "perf"'
///
/// or just watch the NSLog lines in the Xcode console.
enum Perf {
    static let on = CommandLine.arguments.contains("--perf")
    private static let log = Logger(subsystem: "com.divinedavis.findacrib", category: "perf")

    /// Times `work` and logs anything over `floorMs`. Returns the value, so it
    /// can wrap an existing expression without restructuring the caller.
    @inline(__always)
    static func span<T>(_ name: @autoclosure () -> String, floorMs: Double = 1,
                        _ work: () -> T) -> T {
        guard on else { return work() }
        let t0 = CFAbsoluteTimeGetCurrent()
        let out = work()
        let ms = (CFAbsoluteTimeGetCurrent() - t0) * 1000
        if ms >= floorMs {
            let label = name()
            log.notice("\(label, privacy: .public) \(ms, format: .fixed(precision: 1))ms")
        }
        return out
    }

    /// A bare timestamped mark, for pairing an event with the spans around it.
    @inline(__always)
    static func mark(_ name: @autoclosure () -> String) {
        guard on else { return }
        let label = name()
        log.notice("• \(label, privacy: .public)")
    }

    /// A main-thread watchdog. Ticks on the main run loop every 16ms and logs
    /// any gap longer than `stallMs` — which is exactly the thing a user calls
    /// "it takes long": not slow work somewhere, but the main thread not
    /// getting back to the run loop, so nothing draws.
    ///
    /// Registered in .common mode on purpose: the default mode is suspended
    /// while a scroll or a navigation transition is tracking, which is when the
    /// stalls that matter happen.
    @MainActor private static var last = CFAbsoluteTimeGetCurrent()
    @MainActor static func startWatchdog(stallMs: Double = 100) {
        guard on else { return }
        last = CFAbsoluteTimeGetCurrent()
        let t = Timer(timeInterval: 0.016, repeats: true) { _ in
            MainActor.assumeIsolated {
                let now = CFAbsoluteTimeGetCurrent()
                let gap = (now - last) * 1000
                last = now
                if gap >= stallMs { log.notice("!! main thread stalled \(gap, format: .fixed(precision: 0))ms") }
            }
        }
        RunLoop.main.add(t, forMode: .common)
        log.notice("watchdog on")
    }
}
