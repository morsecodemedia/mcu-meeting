import Foundation
import CoreAudio

enum AudioDiscovery {
    static let system = AudioObjectID(kAudioObjectSystemObject)

    static func address(
        _ selector: AudioObjectPropertySelector,
        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal
    ) -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: scope,
            mElement: kAudioObjectPropertyElementMain
        )
    }

    static func defaultInput() throws -> AudioObjectID {
        var property = address(kAudioHardwarePropertyDefaultInputDevice)
        var device = AudioObjectID(0)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)

        let status = AudioObjectGetPropertyData(
            system, &property, 0, nil, &size, &device
        )

        guard status == noErr else {
            throw NSError(
                domain: "MCUMicrophone",
                code: Int(status),
                userInfo: [NSLocalizedDescriptionKey:
                    "Unable to determine default input device"]
            )
        }

        return device
    }

    static func devices() throws -> [AudioObjectID] {
        var property = address(kAudioHardwarePropertyDevices)
        var size: UInt32 = 0

        let status = AudioObjectGetPropertyDataSize(
            system, &property, 0, nil, &size
        )

        guard status == noErr else {
            throw NSError(
                domain: "MCUMicrophone",
                code: Int(status),
                userInfo: [NSLocalizedDescriptionKey:
                    "Unable to enumerate audio devices"]
            )
        }

        var result = [AudioObjectID](
            repeating: 0,
            count: Int(size) / MemoryLayout<AudioObjectID>.size
        )

        guard !result.isEmpty else {
            return []
        }

        let readStatus = result.withUnsafeMutableBufferPointer { buffer in
            AudioObjectGetPropertyData(
                system, &property, 0, nil, &size, buffer.baseAddress!
            )
        }

        guard readStatus == noErr else {
            throw NSError(
                domain: "MCUMicrophone",
                code: Int(readStatus),
                userInfo: [NSLocalizedDescriptionKey:
                    "Unable to read audio device list"]
            )
        }

        return result
    }

    static func stringProperty(
        _ device: AudioObjectID,
        selector: AudioObjectPropertySelector
    ) -> String {
        var property = address(selector)
        var value: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)

        let status = withUnsafeMutablePointer(to: &value) { pointer in
            AudioObjectGetPropertyData(
                device,
                &property,
                0,
                nil,
                &size,
                UnsafeMutableRawPointer(pointer)
            )
        }

        guard status == noErr, let value else {
            return "Unknown"
        }

        return value.takeUnretainedValue() as String
    }

    static func inputChannels(_ device: AudioObjectID) -> Int {
        var property = address(
            kAudioDevicePropertyStreamConfiguration,
            scope: kAudioDevicePropertyScopeInput
        )

        var size: UInt32 = 0

        guard AudioObjectGetPropertyDataSize(
            device, &property, 0, nil, &size
        ) == noErr, size >= UInt32(MemoryLayout<AudioBufferList>.size) else {
            return 0
        }

        let raw = UnsafeMutableRawPointer.allocate(
            byteCount: Int(size),
            alignment: MemoryLayout<AudioBufferList>.alignment
        )
        defer { raw.deallocate() }

        guard AudioObjectGetPropertyData(
            device, &property, 0, nil, &size, raw
        ) == noErr else {
            return 0
        }

        let list = raw.assumingMemoryBound(to: AudioBufferList.self)
        let buffers = UnsafeMutableAudioBufferListPointer(list)

        return buffers.reduce(0) {
            $0 + Int($1.mNumberChannels)
        }
    }

    static func printDevices() throws {
        let selected = try defaultInput()

        let inputs = try devices().compactMap { device -> (
            id: AudioObjectID,
            channels: Int
        )? in
            let channels = inputChannels(device)
            return channels > 0 ? (device, channels) : nil
        }

        guard !inputs.isEmpty else {
            throw NSError(
                domain: "MCUMicrophone",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey:
                    "No audio input devices discovered"]
            )
        }

        for input in inputs {
            let name = stringProperty(
                input.id,
                selector: kAudioObjectPropertyName
            )
            let uid = stringProperty(
                input.id,
                selector: kAudioDevicePropertyDeviceUID
            )
            let marker = input.id == selected ? " [DEFAULT]" : ""

            print("\(input.id): \(name) | channels=\(input.channels) | uid=\(uid)\(marker)")
        }
    }
}

@main
struct MicrophoneCapture {
    static func main() {
        guard Array(CommandLine.arguments.dropFirst()) == ["devices"] else {
            fputs("Usage: mcu-mic-capture devices\n", stderr)
            Foundation.exit(2)
        }

        do {
            try AudioDiscovery.printDevices()
        } catch {
            fputs("Device discovery error: \(error.localizedDescription)\n", stderr)
            Foundation.exit(1)
        }
    }
}
