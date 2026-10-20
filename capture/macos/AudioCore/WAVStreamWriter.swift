import Foundation

/// Incremental mono PCM16 RIFF/WAV writer. Not thread-safe: callers serialize append/finalize.
/// The output is only a valid WAV after finalize() succeeds.
public final class WAVStreamWriter {
    public enum WriterError: Error {
        case invalidSampleRate
        case alreadyFinalized
        case emptyRecording
        case riffSizeLimit
    }

    private let handle: FileHandle
    private let sampleRate: UInt32
    public private(set) var framesWritten: UInt64 = 0
    private var finalized = false
    private static let maxDataBytes = UInt64(UInt32.max) - 36

    public init(url: URL, sampleRate: UInt32) throws {
        guard sampleRate > 0, sampleRate <= UInt32.max / 2 else { throw WriterError.invalidSampleRate }
        self.sampleRate = sampleRate
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else {
            throw CocoaError(.fileWriteUnknown)
        }
        self.handle = try FileHandle(forWritingTo: url)
        do { try handle.write(contentsOf: Self.header(sampleRate: sampleRate, dataBytes: 0)) }
        catch { try? handle.close(); throw error }
    }

    public func append(_ samples: [Float]) throws {
        guard !finalized else { throw WriterError.alreadyFinalized }
        guard !samples.isEmpty else { return }
        let newBytes = UInt64(samples.count) * 2
        guard newBytes <= Self.maxDataBytes - framesWritten * 2 else { throw WriterError.riffSizeLimit }
        var bytes = Data(capacity: samples.count * 2)
        for value in samples {
            let clamped = max(-1, min(1, value.isFinite ? value : 0))
            var sample = Int16((clamped * 32767).rounded()).littleEndian
            withUnsafeBytes(of: &sample) { bytes.append(contentsOf: $0) }
        }
        try handle.write(contentsOf: bytes)
        framesWritten += UInt64(samples.count)
    }

    public func finalize() throws {
        guard !finalized else { throw WriterError.alreadyFinalized }
        guard framesWritten > 0 else { throw WriterError.emptyRecording }
        try handle.seek(toOffset: 0)
        try handle.write(contentsOf: Self.header(sampleRate: sampleRate, dataBytes: UInt32(framesWritten * 2)))
        try handle.synchronize()
        try handle.close()
        finalized = true
    }

    private static func header(sampleRate: UInt32, dataBytes: UInt32) -> Data {
        var data = Data()
        func ascii(_ value: String) { data.append(contentsOf: value.utf8) }
        func u16(_ value: UInt16) { var v = value.littleEndian; withUnsafeBytes(of: &v) { data.append(contentsOf: $0) } }
        func u32(_ value: UInt32) { var v = value.littleEndian; withUnsafeBytes(of: &v) { data.append(contentsOf: $0) } }
        ascii("RIFF"); u32(36 + dataBytes); ascii("WAVE")
        ascii("fmt "); u32(16); u16(1); u16(1)
        u32(sampleRate); u32(sampleRate * 2); u16(2); u16(16)
        ascii("data"); u32(dataBytes)
        return data
    }
}
