import Foundation

struct ConfirmationRequest: Codable, Identifiable {
    var id: String { "\(action)-\(label)" }
    let action: String
    let label: String
    let app: String
    let detail: String
}

struct HandoffRequest: Codable, Identifiable {
    var id: String { reason }
    let reason: String
}
