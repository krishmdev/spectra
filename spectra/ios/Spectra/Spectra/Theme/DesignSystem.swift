import SwiftUI

enum DS {
    // MARK: - Brand Colors
    static let primary = Color(hex: 0x534AB7)
    static let primaryTint = Color(hex: 0xEEEDFE)
    static let success = Color(hex: 0x1D9E75)
    static let warning = Color(hex: 0xBA7517)
    static let warningLight = Color(hex: 0xFAEEDA)
    static let warningBadgeText = Color(hex: 0x854F0B)
    static let danger = Color(hex: 0xE24B4A)
    static let memoryTextDark = Color(hex: 0x3C3489)
    static let memoryTextDeep = Color(hex: 0x26215C)

    // MARK: - Dimensions
    static let cardRadius: CGFloat = 16
    static let buttonRadius: CGFloat = 12
    static let pillRadius: CGFloat = 8
    static let micSize: CGFloat = 56
    static let stepIndicatorSize: CGFloat = 18
}

extension Color {
    init(hex: UInt, alpha: Double = 1.0) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: alpha
        )
    }
}
