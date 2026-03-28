import Foundation

struct TaskStatus: Codable, Identifiable {
    var id: Int { step }
    let step: Int
    let total: Int
    let action: String
    let detail: String
    let app: String
}
