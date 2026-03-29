import Foundation

struct ContextTrigger: Identifiable {
    let id = UUID()
    let type: String   // "time", "location", "app"
    let label: String
    let detail: String
}

struct StoredTask: Identifiable {
    let id: String
    let taskDescription: String
    let stepCount: Int
    let occurrenceCount: Int
    let createdAt: Double
    let hourOfDay: Int
    let dayOfWeek: Int
    let triggers: [ContextTrigger]
}

struct ActionLogEntry: Identifiable {
    let id: String
    let timestamp: Double
    let app: String
    let action: String
}

struct LearnedSequence: Identifiable {
    let id: String
    let actions: [String]
    let occurrenceCount: Int
    let createdAt: Double
}

struct SequenceSuggestion: Identifiable {
    var id: String { sequenceId }
    let sequenceId: String
    let nextAction: String
    let prefix: [String]
    let occurrenceCount: Int
}
