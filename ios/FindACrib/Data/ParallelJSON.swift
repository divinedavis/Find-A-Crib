import Foundation

/// Decodes a top-level JSON array on every core (2026-10-02).
///
/// The boot file is one 11 MB array of 47,165 buildings, and JSONDecoder walks
/// it on a single thread — the slowest step of launch. This finds the element
/// boundaries with one cheap byte scan (depth + string state, honouring
/// backslash escapes), cuts the array into one slice per core, decodes the
/// slices at the same time, and joins them in order. Any surprise — a slice
/// that fails, or a shape it does not recognise — falls back to the plain
/// single-threaded decode, so the answer is always the same array.
enum ParallelJSON {
    static func decodeArray<T: Decodable>(_ type: T.Type, from data: Data,
                                          parts: Int = ProcessInfo.processInfo.activeProcessorCount) throws -> [T] {
        guard parts > 1, data.count > 256 * 1024, let cuts = cutPoints(data, parts: parts) else {
            return try JSONDecoder().decode([T].self, from: data)
        }
        var slices = [[T]?](repeating: nil, count: cuts.count)
        slices.withUnsafeMutableBufferPointer { buf in
            DispatchQueue.concurrentPerform(iterations: cuts.count) { k in
                let r = cuts[k]
                var chunk = Data(capacity: r.count + 2)
                chunk.append(UInt8(ascii: "["))
                chunk.append(data[(data.startIndex + r.lowerBound)..<(data.startIndex + r.upperBound)])
                chunk.append(UInt8(ascii: "]"))
                buf[k] = try? JSONDecoder().decode([T].self, from: chunk)
            }
        }
        if slices.contains(where: { $0 == nil }) {
            return try JSONDecoder().decode([T].self, from: data)
        }
        return slices.flatMap { $0! }
}

    /// Byte ranges that split the array's elements into about `parts` runs,
    /// each a comma-separated list of whole elements with no leading or
    /// trailing comma. Nil if the data is not a JSON array or has too few
    /// elements to split.
    static func cutPoints(_ data: Data, parts: Int) -> [Range<Int>]? {
        data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) -> [Range<Int>]? in
            let p = raw.bindMemory(to: UInt8.self)
            let n = p.count
            var i = 0
            while i < n, p[i] == 0x20 || p[i] == 0x0A || p[i] == 0x0D || p[i] == 0x09 { i += 1 }
            guard i < n, p[i] == UInt8(ascii: "[") else { return nil }
            let open = i + 1
            var close = n - 1
            while close > open, p[close] != UInt8(ascii: "]") { close -= 1 }
            guard close > open else { return nil }
            let target = (close - open) / parts
            var commas: [Int] = []
            var depth = 0, inString = false, escaped = false
            var next = open + target
            i = open
            while i < close {
                let c = p[i]
                if inString {
                    if escaped { escaped = false }
                    else if c == 0x5C { escaped = true }          // backslash
                    else if c == 0x22 { inString = false }        // quote
                } else {
                    switch c {
                    case 0x22: inString = true
                    case 0x7B, 0x5B: depth += 1                   // { [
                    case 0x7D, 0x5D: depth -= 1                   // } ]
                    case 0x2C where depth == 0 && i >= next:      // , between elements
                        commas.append(i)
                        next = i + 1 + target
                    default: break
                    }
                }
                i += 1
            }
            guard depth == 0, !inString, !commas.isEmpty else { return nil }
            var out: [Range<Int>] = []
            var start = open
            for c in commas { out.append(start..<c); start = c + 1 }
            out.append(start..<close)
            return out
        }
    }
}
