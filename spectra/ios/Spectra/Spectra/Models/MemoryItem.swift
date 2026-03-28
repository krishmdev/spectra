import Foundation

struct MemoryItem: Codable, Identifiable {
    var id: String { key }
    let key: String
    let value: String
}

struct TaskResult: Codable, Equatable {
    let success: Bool
    let summary: String
    let steps: Int
    let duration: Double
}

struct CompletedTask: Identifiable {
    let id = UUID()
    let summary: String
    let steps: Int
    let duration: Double
    let app: String
    let success: Bool
}
