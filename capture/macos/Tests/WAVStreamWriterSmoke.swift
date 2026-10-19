import Foundation

@main struct WAVStreamWriterSmoke {
    static func main() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let writer = try WAVStreamWriter(url: url, sampleRate: 48000)
        try writer.append([0, 0.5])
        try writer.append([-0.5, 1])
        guard writer.framesWritten == 4 else { fatalError("wrong frame count") }
        try writer.finalize()
        let bytes = try Data(contentsOf: url)
        guard bytes.count == 52,
              String(data: bytes.prefix(4), encoding: .ascii) == "RIFF",
              String(data: bytes[8..<12], encoding: .ascii) == "WAVE",
              String(data: bytes[36..<40], encoding: .ascii) == "data",
              Array(bytes[40..<44]) == [8, 0, 0, 0] else { fatalError("invalid WAV") }
        do {
            try writer.append([0])
            fatalError("append after finalize accepted")
        } catch WAVStreamWriter.WriterError.alreadyFinalized { }
        print("WAV writer smoke test: PASS")
    }
}
