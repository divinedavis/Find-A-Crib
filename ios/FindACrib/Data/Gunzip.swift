import Foundation

enum Gunzip {
    enum Error: Swift.Error { case notGzip, truncated }
    /// Inflate a .gz file. Foundation's `.zlib` algorithm is raw DEFLATE, so
    /// the gzip header (10 bytes + optional fields) and 8-byte trailer are
    /// stripped here rather than reaching for a third-party zlib wrapper.
    static func inflate(_ d: Data) throws -> Data {
        guard d.count > 18, d[d.startIndex] == 0x1f, d[d.startIndex + 1] == 0x8b else { throw Error.notGzip }
        let base = d.startIndex
        var i = base + 10
        let flg = d[base + 3]
        func need(_ n: Int) throws { if i + n > d.endIndex - 8 { throw Error.truncated } }
        if flg & 0x04 != 0 { try need(2); let xlen = Int(d[i]) | Int(d[i + 1]) << 8; i += 2 + xlen }
        if flg & 0x08 != 0 { while i < d.endIndex - 8, d[i] != 0 { i += 1 }; i += 1 }
        if flg & 0x10 != 0 { while i < d.endIndex - 8, d[i] != 0 { i += 1 }; i += 1 }
        if flg & 0x02 != 0 { i += 2 }
        try need(0)
        let body = d.subdata(in: i..<(d.endIndex - 8))
        return try (body as NSData).decompressed(using: .zlib) as Data
    }
}
