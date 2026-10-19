// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "mcu-capture",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .executableTarget(
            name: "mcu-capture",
            path: "Sources",
            linkerSettings: [
                .linkedFramework("ScreenCaptureKit"),
                .linkedFramework("AVFoundation"),
                .linkedFramework("CoreMedia"),
                .linkedFramework("AudioToolbox")
            ]
        )
    ]
)
