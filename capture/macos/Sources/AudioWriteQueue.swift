import Foundation

/// Nonblocking bounded handoff from audio callbacks to a serialized WAV writer.
/// Overflow and I/O errors are fatal; never silently drop audio.
final class AudioWriteQueue {
    enum QueueError: Error { case overflow, closed }
    private let lock = NSLock()
    private let worker = DispatchQueue(label: "mcu.capture.wav-writer")
    private let writer: WAVStreamWriter
    private let maxPendingFrames: Int
    private var pendingFrames = 0
    private var closed = false
    private var failure: Error?

    init(writer: WAVStreamWriter, maxPendingFrames: Int = 48000 * 5) {
        self.writer = writer
        self.maxPendingFrames = maxPendingFrames
    }

    func submit(_ frames: [Float]) {
        lock.lock()
        if closed || failure != nil { lock.unlock(); return }
        if frames.count > maxPendingFrames - pendingFrames {
            failure = QueueError.overflow
            lock.unlock()
            return
        }
        pendingFrames += frames.count
        lock.unlock()
        worker.async { [self] in
            do { try writer.append(frames) }
            catch { lock.lock(); if failure == nil { failure = error }; lock.unlock() }
            lock.lock(); pendingFrames -= frames.count; lock.unlock()
        }
    }

    /// Call only after stopping SCStream and draining its callback queue.
    func finish() throws -> UInt64 {
        lock.lock(); closed = true; lock.unlock()
        worker.sync {}
        lock.lock(); let error = failure; lock.unlock()
        if let error { throw error }
        try writer.finalize()
        return writer.framesWritten
    }

    var hasFailed: Bool {
        lock.lock(); defer { lock.unlock() }
        return failure != nil
    }
}
