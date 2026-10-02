import Foundation
import MetricKit

/// Real-device launch and hang numbers from MetricKit (2026-10-02).
///
/// iOS hands the app one payload a day per device: how long launches took to
/// first draw, how long the main thread hung, how much CPU the app used. Each
/// one becomes a single `perf_metrics` event, so the speed of the app as
/// people actually run it shows up next to everything else — and a change that
/// makes it faster (or slower) is visible within a day or two of shipping.
/// Covered by the App Privacy label: Performance Data, Analytics, linked.
final class Metrics: NSObject, MXMetricManagerSubscriber {
    static let shared = Metrics()

    func start() { MXMetricManager.shared.add(self) }

    func didReceive(_ payloads: [MXMetricPayload]) {
        for p in payloads {
            var props: [String: Any] = [:]
            if let h = p.applicationLaunchMetrics?.histogrammedTimeToFirstDraw {
                props["launch_ms_median"] = Self.median(h)
            }
            if let h = p.applicationLaunchMetrics?.histogrammedApplicationResumeTime {
                props["resume_ms_median"] = Self.median(h)
            }
            if let h = p.applicationResponsivenessMetrics?.histogrammedApplicationHangTime {
                props["hang_ms_median"] = Self.median(h)
                props["hangs"] = Self.total(h)
            }
            if let c = p.cpuMetrics?.cumulativeCPUTime {
                props["cpu_s"] = Int(c.converted(to: .seconds).value.rounded())
            }
            if let m = p.memoryMetrics?.peakMemoryUsage {
                props["peak_mb"] = Int(m.converted(to: .megabytes).value.rounded())
            }
            props["app_version"] = p.latestApplicationVersion
            guard props.count > 1 else { continue }
            Task { @MainActor in Analytics.shared.track("perf_metrics", props) }
        }
    }

    /// The bucket that holds the middle sample, in milliseconds.
    static func median(_ h: MXHistogram<UnitDuration>) -> Int? {
        var buckets: [(Double, Int)] = []
        let e = h.bucketEnumerator
        while let b = e.nextObject() as? MXHistogramBucket<UnitDuration> {
            let mid = (b.bucketStart.converted(to: .milliseconds).value + b.bucketEnd.converted(to: .milliseconds).value) / 2
            buckets.append((mid, b.bucketCount))
        }
        let total = buckets.reduce(0) { $0 + $1.1 }
        guard total > 0 else { return nil }
        var seen = 0
        for (mid, n) in buckets.sorted(by: { $0.0 < $1.0 }) {
            seen += n
            if seen * 2 >= total { return Int(mid.rounded()) }
        }
        return nil
    }

    static func total(_ h: MXHistogram<UnitDuration>) -> Int {
        var n = 0
        let e = h.bucketEnumerator
        while let b = e.nextObject() as? MXHistogramBucket<UnitDuration> { n += b.bucketCount }
        return n
    }
}
