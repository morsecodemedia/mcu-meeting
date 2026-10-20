// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "mcu-capture",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .target(
            name: "MCUAudioCore",
            path: "AudioCore"
        ),
        .executableTarget(
            name: "mcu-capture",
            dependencies: ["MCUAudioCore"],
            path: "Sources",
            linkerSettings: [
                .linkedFramework("ScreenCaptureKit"),
                .linkedFramework("AVFoundation"),
                .linkedFramework("CoreMedia"),
                .linkedFramework("AudioToolbox")
            ]
        ),
        .executableTarget(
            name: "mcu-mic-capture",
            dependencies: ["MCUAudioCore"],
            path: "Microphone",
            linkerSettings: [
                .linkedFramework("CoreAudio"),
                .linkedFramework("AVFoundation")
            ]
        )
    ]
)
