import Foundation

struct PlanPreviewData: Codable {
    let steps: [String]
    let task: String
}

enum StepStatus {
    case done
    case current
    case upcoming
}
