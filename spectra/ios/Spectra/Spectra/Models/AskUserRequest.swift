import Foundation

struct AskUserRequest: Codable, Identifiable {
    var id: String { question }
    let question: String
    let options: [String]?
}
