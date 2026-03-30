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
    let initialState: String?
    let goalState: String?
}

struct SequenceSuggestion: Identifiable {
    var id: String { sequenceId }
    let sequenceId: String
    let nextAction: String
    let prefix: [String]
    let occurrenceCount: Int
    let initialState: String?
    let goalState: String?
}

// MARK: - Scheduled Tasks (Time Hooks)

struct ScheduledHook: Identifiable, Equatable {
    let id: String
    let title: String
    let actionTask: String
    let state: String          // active, running, paused, completed, failed
    let scheduleType: String   // one_time, interval, calendar
    let recurrenceDescription: String
    let nextRunAt: Double?
    let lastRunAt: Double?
    let lastResult: String?
    let lastError: String?
    let fireCount: Int
    let createdAt: Double

    var isRecurring: Bool { scheduleType != "one_time" }
    var isActive: Bool { state == "active" }
    var isRunning: Bool { state == "running" }
    var isPaused: Bool { state == "paused" }
    var isCompleted: Bool { state == "completed" }
    var isFailed: Bool { state == "failed" }
}
