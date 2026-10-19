import Foundation

@main struct AudioWriteQueueSmoke {
    static func main() throws {
        let path = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".wav")
        defer { try? FileManager.default.removeItem(at: path) }
        let writer = try WAVStreamWriter(url: path, sampleRate: 48000)
        let queue = AudioWriteQueue(writer: writer, maxPendingFrames: 48000)
        for _ in 0..<10 { queue.submit([Float](repeating: 0.25, count: 1000)) }
        let frames = try queue.finish()
        guard frames == 10000 else { fatalError("wrong frame count") }
        let bytes = try Data(contentsOf: path)
        guard bytes.count == 44 + 20000 else { fatalError("wrong WAV size") }
        print("Audio write queue smoke test: PASS")
    }
}
