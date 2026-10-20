import Foundation
import AVFoundation
import CoreAudio
import Darwin
import MCUAudioCore

private final class MicStopFlag {
    private let lock = NSLock()
    private var value = false
    func request() { lock.lock(); value = true; lock.unlock() }
    var requested: Bool { lock.lock(); defer { lock.unlock() }; return value }
}

private final class MicCallbackState {
    private let lock = NSLock()
    private var errorMessage: String?
    private var callbacks = 0
    func failed(_ message: String) {
        lock.lock(); defer { lock.unlock() }
        if errorMessage == nil { errorMessage = message }
    }
    func received() { lock.lock(); callbacks += 1; lock.unlock() }
    var error: String? { lock.lock(); defer { lock.unlock() }; return errorMessage }
    var count: Int { lock.lock(); defer { lock.unlock() }; return callbacks }
}

enum MicrophoneRecorder {
    enum CaptureError: Error {
        case microphonePermissionDenied
        case invalidInputFormat
        case unsupportedInputFormat
        case noSamples
        case callbackFailure(String)
        case inputDeviceChanged
    }

    private static func authorizeMicrophone() -> Bool {
        let semaphore = DispatchSemaphore(value: 0)
        var allowed = false
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            allowed = granted
            semaphore.signal()
        }
        semaphore.wait()
        return allowed
    }

    static func record(output: String, duration: Double?) throws {
        guard authorizeMicrophone() else { throw CaptureError.microphonePermissionDenied }
        let selected = try AudioDiscovery.defaultInput()
        let selectedName = AudioDiscovery.stringProperty(selected, selector: kAudioObjectPropertyName)
        print("Default microphone: \(selectedName) (CoreAudio ID \(selected))")

        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate >= 1, format.sampleRate <= Double(UInt32.max / 2),
              format.channelCount > 0 else { throw CaptureError.invalidInputFormat }
        // The first adapter explicitly supports the common noninterleaved Float32 tap format.
        // Fail rather than silently misinterpret other formats.
        guard format.commonFormat == .pcmFormatFloat32, !format.isInterleaved else {
            throw CaptureError.unsupportedInputFormat
        }
        let sampleRate = UInt32(format.sampleRate.rounded())
        print("Input: \(format.channelCount) channel(s), \(format.sampleRate) Hz, Float32")
        let writer = try WAVStreamWriter(url: URL(fileURLWithPath: output), sampleRate: sampleRate)
        let queue = AudioWriteQueue(writer: writer, maxPendingFrames: Int(sampleRate) * 5)
        let callback = MicCallbackState()
        let channels = Int(format.channelCount)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            guard buffer.frameLength > 0 else { return }
            guard let channelData = buffer.floatChannelData else {
                callback.failed("Missing Float32 channel data")
                return
            }
            let count = Int(buffer.frameLength)
            var mono = [Float](repeating: 0, count: count)
            for channel in 0..<channels {
                let samples = channelData[channel]
                for frame in 0..<count { mono[frame] += samples[frame] }
            }
            if channels > 1 {
                let factor = Float(channels)
                for frame in 0..<count { mono[frame] /= factor }
            }
            queue.submit(mono)
            callback.received()
        }
        let stop = MicStopFlag()
        signal(SIGINT, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
        source.setEventHandler { stop.request() }
        source.resume()
        defer { source.cancel() }
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            throw error
        }
        print("Recording microphone. Press Ctrl+C to stop.")
        let started = ProcessInfo.processInfo.systemUptime
        while !stop.requested {
            if let duration, ProcessInfo.processInfo.systemUptime - started >= duration { break }
            if try AudioDiscovery.defaultInput() != selected {
                callback.failed("Default input device changed during recording")
                break
            }
            if callback.error != nil || queue.hasFailed { break }
            Thread.sleep(forTimeInterval: 0.1)
        }
        engine.stop()
        input.removeTap(onBus: 0)
        // The AVAudioEngine tap has been removed; queued WAV writes can now drain.
        if let error = callback.error { throw CaptureError.callbackFailure(error) }
        guard callback.count > 0 else { throw CaptureError.noSamples }
        let frames = try queue.finish()
        guard frames > 0 else { throw CaptureError.noSamples }
        print("WAV written: \(output) (mono PCM16, \(frames) frames)")
    }
}
