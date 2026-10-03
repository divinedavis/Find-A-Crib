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

    /// Crashes, hangs, CPU and disk-write blowups from real phones (2026-10-02),
    /// delivered on the next launch after they happen (iOS 15+). One
    /// `app_diagnostic` event each — kind, the exception/signal or hang length,
    /// and our own top frames as binary offsets, which symbolicate against the
    /// archive's dSYM (`atos -o FindACrib.app.dSYM -l 0x0 <offset>`). No user
    /// content is in a diagnostic. Covered by the label: Crash Data, linked.
    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        for p in payloads {
            var rows: [[String: Any]] = []
            for d in p.crashDiagnostics ?? [] {
                var r: [String: Any] = ["kind": "crash", "frames": Self.ownFrames(d.callStackTree)]
                if let v = d.exceptionType { r["exception_type"] = v.intValue }
                if let v = d.signal { r["signal"] = v.intValue }
                if let v = d.terminationReason { r["reason"] = String(v.prefix(200)) }
                rows.append(Self.stamp(r, d.metaData, d.applicationVersion))
            }
            for d in p.hangDiagnostics ?? [] {
                let r: [String: Any] = ["kind": "hang", "hang_ms": Int(d.hangDuration.converted(to: .milliseconds).value.rounded()),
                                        "frames": Self.ownFrames(d.callStackTree)]
                rows.append(Self.stamp(r, d.metaData, d.applicationVersion))
            }
            for d in p.cpuExceptionDiagnostics ?? [] {
                let r: [String: Any] = ["kind": "cpu", "cpu_s": Int(d.totalCPUTime.converted(to: .seconds).value.rounded()),
                                        "frames": Self.ownFrames(d.callStackTree)]
                rows.append(Self.stamp(r, d.metaData, d.applicationVersion))
            }
            for d in p.diskWriteExceptionDiagnostics ?? [] {
                let r: [String: Any] = ["kind": "disk_writes", "mb": Int(d.totalWritesCaused.converted(to: .megabytes).value.rounded()),
                                        "frames": Self.ownFrames(d.callStackTree)]
                rows.append(Self.stamp(r, d.metaData, d.applicationVersion))
            }
            for r in rows { Task { @MainActor in Analytics.shared.track("app_diagnostic", r) } }
        }
    }

    private static func stamp(_ r: [String: Any], _ meta: MXMetaData, _ version: String) -> [String: Any] {
        var r = r
        r["app_version"] = version
        r["os"] = meta.osVersion
        return r
    }

    /// The first few frames inside our own binary, as "FindACrib+0x1a2b3c",
    /// walking the first thread's stack. Enough to group the same crash across
    /// phones and symbolicate it; the full tree is too big for an event row.
    static func ownFrames(_ tree: MXCallStackTree, limit: Int = 6) -> [String] {
        guard let json = try? JSONSerialization.jsonObject(with: tree.jsonRepresentation()) as? [String: Any],
              let stacks = json["callStacks"] as? [[String: Any]] else { return [] }
        let main = stacks.first { ($0["threadAttributed"] as? Bool) == true } ?? stacks.first
        var out: [String] = []
        var frame = (main?["callStackRootFrames"] as? [[String: Any]])?.first
        while let f = frame, out.count < limit {
            if let name = f["binaryName"] as? String, name == "FindACrib",
               let off = f["offsetIntoBinaryTextSegment"] as? Int {
                out.append("\(name)+0x\(String(off, radix: 16))")
            }
            frame = (f["subFrames"] as? [[String: Any]])?.first
        }
        return out
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
