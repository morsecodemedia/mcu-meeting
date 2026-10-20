import Foundation
import MCUAudioCore
import Darwin
import ScreenCaptureKit
import CoreMedia
import AudioToolbox

final class AudioCollector: NSObject, SCStreamOutput, SCStreamDelegate {
    private let lock = NSLock()
    private let writeQueue: AudioWriteQueue
    init(writeQueue: AudioWriteQueue) { self.writeQueue = writeQueue; super.init() }
    private var acceptedCallbacks = 0
    private var receivedCallbacks = 0
    private var errors: [String] = []
    private var nativeRate: Double = 0
    private var nativeChannels: UInt32 = 0

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        lock.lock(); receivedCallbacks += 1; lock.unlock()
        guard CMSampleBufferIsValid(sampleBuffer),
              let description = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(description) else {
            recordError("Missing or invalid audio format")
            return
        }
        let asbd = asbdPtr.pointee
        guard asbd.mFormatID == kAudioFormatLinearPCM,
              (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0,
              asbd.mBitsPerChannel == 32,
              (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0,
              asbd.mChannelsPerFrame > 0,
              asbd.mSampleRate > 0 else {
            recordError("Unsupported format: id=\(asbd.mFormatID) flags=\(asbd.mFormatFlags) bits=\(asbd.mBitsPerChannel) channels=\(asbd.mChannelsPerFrame)")
            return
        }

        var requiredBytes = 0
        var retainedBlock: CMBlockBuffer?
        let flags = UInt32(kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment)
        let sizeStatus = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer, bufferListSizeNeededOut: &requiredBytes,
            bufferListOut: nil, bufferListSize: 0,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: flags, blockBufferOut: &retainedBlock
        )
        // CoreMedia may report a size error for the sizing pass; requiredBytes is authoritative.
        guard requiredBytes >= MemoryLayout<AudioBufferList>.size else {
            recordError("Could not size audio buffer list: OSStatus \(sizeStatus)")
            return
        }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: requiredBytes, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        let list = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
        retainedBlock = nil
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer, bufferListSizeNeededOut: nil,
            bufferListOut: list, bufferListSize: requiredBytes,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: flags, blockBufferOut: &retainedBlock
        )
        guard status == noErr else { recordError("Audio buffer extraction failed: \(status)"); return }

        let buffers = UnsafeMutableAudioBufferListPointer(list)
        let channelCount = Int(asbd.mChannelsPerFrame)
        guard buffers.count >= channelCount else {
            recordError("Expected \(channelCount) planar buffers, got \(buffers.count)")
            return
        }
        let frameCount = CMSampleBufferGetNumSamples(sampleBuffer)
        guard frameCount > 0 else { return }
        var channels: [UnsafeBufferPointer<Float>] = []
        for channel in 0..<channelCount {
            let buffer = buffers[channel]
            guard let data = buffer.mData,
                  Int(buffer.mDataByteSize) >= frameCount * MemoryLayout<Float>.size else {
                recordError("Invalid channel buffer \(channel)")
                return
            }
            channels.append(UnsafeBufferPointer(start: data.assumingMemoryBound(to: Float.self), count: frameCount))
        }
        var mono = [Float](repeating: 0, count: frameCount)
        for i in 0..<frameCount {
            var sum: Float = 0
            for channel in channels { sum += channel[i] }
            mono[i] = sum / Float(channelCount)
        }
        lock.lock()
        if nativeRate == 0 { nativeRate = asbd.mSampleRate; nativeChannels = asbd.mChannelsPerFrame }
        if nativeRate == asbd.mSampleRate {
            writeQueue.submit(mono)
            acceptedCallbacks += 1
        } else if errors.count < 10 {
            errors.append("Sample rate changed during capture; dropped callback")
        }
        lock.unlock()
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        recordError("Capture stopped: \(error.localizedDescription)")
    }
    private func recordError(_ message: String) {
        lock.lock(); defer { lock.unlock() }
        if errors.count < 10 { errors.append(message) }
    }
    func finish() -> (rate: Double, channels: UInt32, received: Int, accepted: Int, errors: [String]) {
        lock.lock(); defer { lock.unlock() }
        return (nativeRate, nativeChannels, receivedCallbacks, acceptedCallbacks, errors)
    }
}

func writeWAV(samples: [Float], sampleRate: Int, path: String) throws {
    guard sampleRate > 0, !samples.isEmpty, samples.count <= Int(UInt32.max) / 2 else {
        throw NSError(domain: "MCUCapture", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid WAV parameters"])
    }
    var data = Data()
    func ascii(_ value: String) { data.append(contentsOf: value.utf8) }
    func u16(_ value: UInt16) { var v = value.littleEndian; withUnsafeBytes(of: &v) { data.append(contentsOf: $0) } }
    func u32(_ value: UInt32) { var v = value.littleEndian; withUnsafeBytes(of: &v) { data.append(contentsOf: $0) } }
    let payloadSize = UInt32(samples.count * 2)
    ascii("RIFF"); u32(36 + payloadSize); ascii("WAVE")
    ascii("fmt "); u32(16); u16(1); u16(1)
    u32(UInt32(sampleRate)); u32(UInt32(sampleRate * 2)); u16(2); u16(16)
    ascii("data"); u32(payloadSize)
    for sample in samples {
        let clamped = max(-1, min(1, sample.isFinite ? sample : 0))
        let scaled = Int16((clamped * 32767).rounded())
        u16(UInt16(bitPattern: scaled))
    }
    try data.write(to: URL(fileURLWithPath: path), options: .atomic)
}


final class StopFlag {
    private let lock = NSLock()
    private var value = false

    func request() {
        lock.lock()
        value = true
        lock.unlock()
    }

    var requested: Bool {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

@main
struct CaptureTest {
    static func main() async {
        let args = Array(CommandLine.arguments.dropFirst())
        if args == ["--help"] || args == ["-h"] {
            print("Usage: mcu-capture --bundle-id <id> --output <path.wav> [--duration <seconds>]")
            print("Records until Ctrl+C or --duration seconds; no display-wide fallback.")
            return
        }
        var options: [String: String] = [:]
        var i = 0
        while i < args.count {
            guard i + 1 < args.count,
                  ["--bundle-id", "--output", "--duration"].contains(args[i]),
                  options[args[i]] == nil else {
                fputs("Invalid arguments\n", stderr)
                Foundation.exit(2)
            }
            options[args[i]] = args[i + 1]
            i += 2
        }
        guard let bundleID = options["--bundle-id"], !bundleID.isEmpty,
              let path = options["--output"],
              path.lowercased().hasSuffix(".wav") else {
            fputs("Missing or invalid bundle ID/output\n", stderr)
            Foundation.exit(2)
        }
        let duration: Double?
        if let raw = options["--duration"] {
            guard let value = Double(raw), value.isFinite,
                  value > 0, value <= 86400 else {
                fputs("Invalid duration (0 < seconds <= 86400)\n", stderr)
                Foundation.exit(2)
            }
            duration = value
        } else {
            duration = nil
        }
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            guard let display = content.displays.first else {
                throw NSError(domain: "MCUCapture", code: 3, userInfo: [NSLocalizedDescriptionKey: "No display available"])
            }
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = 48000
            config.channelCount = 2
            config.width = 2
            config.height = 2
            config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            let targetApps = content.applications.filter {
                $0.bundleIdentifier == bundleID
            }
            guard !targetApps.isEmpty else {
                throw NSError(domain: "MCUCapture", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "Application not found in ScreenCaptureKit: \(bundleID)"
                ])
            }
            let filter = SCContentFilter(
                display: display,
                including: targetApps,
                exceptingWindows: []
            )
            print("Capture filter: \(bundleID) only")
            let writer = try WAVStreamWriter(url: URL(fileURLWithPath: path), sampleRate: 48000)
            let queue = AudioWriteQueue(writer: writer)
            let collector = AudioCollector(writeQueue: queue)
            let stream = SCStream(filter: filter, configuration: config, delegate: collector)
            try stream.addStreamOutput(collector, type: .audio, sampleHandlerQueue: DispatchQueue(label: "mcu.capture.audio"))
            print("Capturing application audio. Press Ctrl+C to stop.")
            try await stream.startCapture()
            // SIGINT requests a graceful stop rather than immediate termination.
            signal(SIGINT, SIG_IGN)
            let stopFlag = StopFlag()
            let interrupt = DispatchSource.makeSignalSource(
                signal: SIGINT, queue: .global()
            )
            interrupt.setEventHandler { stopFlag.request() }
            interrupt.resume()

            let started = ProcessInfo.processInfo.systemUptime
            while !stopFlag.requested {
                if let duration,
                   ProcessInfo.processInfo.systemUptime - started >= duration {
                    break
                }
                try await Task.sleep(nanoseconds: 100_000_000)
            }
            interrupt.cancel()
            try await stream.stopCapture()
            // Allow callbacks already queued before stop to finish.
            try await Task.sleep(nanoseconds: 300_000_000)
            let result = collector.finish()
            print("Callbacks received: \(result.received); decoded: \(result.accepted)")
            print("Sample rate: \(result.rate); source channels: \(result.channels)")
            for error in result.errors { fputs("Warning: \(error)\n", stderr) }
            guard result.accepted > 0 && !queue.hasFailed else {
                fputs("No usable audio captured; WAV not written.\n", stderr)
                Foundation.exit(1)
            }
            let frames = try queue.finish()
            guard frames > 0 else { throw NSError(domain: "MCUCapture", code: 5, userInfo: [NSLocalizedDescriptionKey: "No audio frames written"]) }
            print("WAV written: \(path) (mono PCM16, \(frames) frames)")
        } catch {
            fputs("Capture error: \(error.localizedDescription)\n", stderr)
            Foundation.exit(1)
        }
    }
}
