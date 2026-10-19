import Foundation

@main struct WAVStreamWriterFailures {
    static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
        if !condition() { fatalError(message) }
    }

    static func expectError(_ expected: WAVStreamWriter.WriterError, _ body: () throws -> Void) {
        do {
            try body()
            fatalError("Expected \(expected), but operation succeeded")
        } catch let error as WAVStreamWriter.WriterError {
            switch (expected, error) {
            case (.invalidSampleRate, .invalidSampleRate),
                 (.alreadyFinalized, .alreadyFinalized),
                 (.emptyRecording, .emptyRecording),
                 (.riffSizeLimit, .riffSizeLimit): break
            default: fatalError("Expected \(expected), got \(error)")
            }
        } catch {
            fatalError("Expected \(expected), got \(error)")
        }
    }

    static func main() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("mcu-wav-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: folder) }

        expectError(.invalidSampleRate) {
            _ = try WAVStreamWriter(url: folder.appendingPathComponent("invalid.wav"), sampleRate: 0)
        }

        let empty = try WAVStreamWriter(url: folder.appendingPathComponent("empty.wav"), sampleRate: 48000)
        try empty.append([])
        expect(empty.framesWritten == 0, "Empty append changed frame count")
        expectError(.emptyRecording) { try empty.finalize() }
        // Do not retry finalization after an empty recording: current writer has no abort API.

        let url = folder.appendingPathComponent("complete.wav")
        let writer = try WAVStreamWriter(url: url, sampleRate: 48000)
        try writer.append([0, 0.25, -0.25])
        try writer.append([1, -1])
        expect(writer.framesWritten == 5, "Incorrect incremental frame count")
        try writer.finalize()
        let bytes = try Data(contentsOf: url)
        expect(bytes.count == 54, "Unexpected WAV length")
        expect(Array(bytes[4..<8]) == [46, 0, 0, 0], "Incorrect RIFF size")
        expect(Array(bytes[40..<44]) == [10, 0, 0, 0], "Incorrect data chunk size")
        expectError(.alreadyFinalized) { try writer.finalize() }
        expectError(.alreadyFinalized) { try writer.append([0]) }

        let missingParent = folder.appendingPathComponent("missing").appendingPathComponent("bad.wav")
        do {
            _ = try WAVStreamWriter(url: missingParent, sampleRate: 48000)
            fatalError("Expected file creation failure")
        } catch {
            // Expected: nonexistent parent directory prevents file creation.
        }
        expect(!FileManager.default.fileExists(atPath: missingParent.path), "Unexpected file created")
        print("WAV writer failure tests: PASS")
    }
}
