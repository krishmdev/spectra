import SwiftUI

struct StoredTasksView: View {
    @EnvironmentObject var ws: WebSocketService
    @State private var selectedTask: StoredTask?

    private let dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    var body: some View {
        ScrollView {
            if ws.storedTasks.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "clock.badge.questionmark")
                        .font(.system(size: 40))
                        .foregroundStyle(.secondary)
                    Text("No stored tasks yet")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Tasks you complete will appear here with their context triggers.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 40)
                }
                .padding(.top, 80)
            } else {
                // Timeline header
                HStack(spacing: 6) {
                    Image(systemName: "timeline.selection")
                        .font(.caption)
                        .foregroundStyle(DS.primary)
                    Text("Sequential Timeline")
                        .font(.caption).fontWeight(.medium)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("\(ws.storedTasks.count) tasks")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)

                LazyVStack(spacing: 0) {
                    ForEach(Array(ws.storedTasks.enumerated()), id: \.element.id) { index, task in
                        HStack(alignment: .top, spacing: 12) {
                            // Timeline rail
                            VStack(spacing: 0) {
                                if index > 0 {
                                    Rectangle()
                                        .fill(DS.primary.opacity(0.25))
                                        .frame(width: 2, height: 12)
                                } else {
                                    Spacer().frame(width: 2, height: 12)
                                }

                                ZStack {
                                    Circle()
                                        .fill(DS.primary.opacity(0.15))
                                        .frame(width: 28, height: 28)
                                    Image(systemName: iconForTask(task))
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundStyle(DS.primary)
                                }

                                if index < ws.storedTasks.count - 1 {
                                    Rectangle()
                                        .fill(DS.primary.opacity(0.25))
                                        .frame(width: 2)
                                        .frame(maxHeight: .infinity)
                                } else {
                                    Spacer().frame(width: 2)
                                }
                            }
                            .frame(width: 28)

                            // Task card
                            VStack(alignment: .leading, spacing: 8) {
                                Text(task.taskDescription)
                                    .font(.subheadline).fontWeight(.medium)
                                    .lineLimit(2)

                                // Trigger pills
                                FlowLayout(spacing: 6) {
                                    ForEach(task.triggers) { trigger in
                                        TriggerPill(trigger: trigger)
                                    }
                                }

                                // Meta row
                                HStack(spacing: 8) {
                                    Label("\(task.stepCount) steps", systemImage: "arrow.triangle.branch")
                                    Text("\u{00B7}")
                                    Label("Run \(task.occurrenceCount)x", systemImage: "arrow.clockwise")
                                    Spacer()
                                    Text(formatRelativeDate(task.createdAt))
                                }
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            }
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color(.secondarySystemBackground))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                        }
                        .padding(.horizontal, 20)
                        .padding(.bottom, 4)
                    }
                }
                .padding(.top, 8)
            }
        }
        .navigationTitle("Stored Tasks")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            ws.requestStoredTasks()
        }
    }

    // MARK: - Helpers

    private func iconForTask(_ task: StoredTask) -> String {
        if task.triggers.contains(where: { $0.type == "location" }) {
            return "location.fill"
        }
        return "clock.fill"
    }

    private func formatRelativeDate(_ timestamp: Double) -> String {
        let date = Date(timeIntervalSince1970: timestamp)
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

// MARK: - Trigger Pill

private struct TriggerPill: View {
    let trigger: ContextTrigger

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 9, weight: .semibold))
            Text(trigger.label)
                .font(.caption2).fontWeight(.medium)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(backgroundColor)
        .foregroundStyle(foregroundColor)
        .clipShape(Capsule())
    }

    private var icon: String {
        switch trigger.type {
        case "time": return "clock"
        case "location": return "location"
        case "app": return "app"
        default: return "questionmark"
        }
    }

    private var backgroundColor: Color {
        switch trigger.type {
        case "time": return DS.primary.opacity(0.12)
        case "location": return DS.success.opacity(0.12)
        case "app": return DS.warning.opacity(0.12)
        default: return Color.secondary.opacity(0.12)
        }
    }

    private var foregroundColor: Color {
        switch trigger.type {
        case "time": return DS.primary
        case "location": return DS.success
        case "app": return DS.warningBadgeText
        default: return .secondary
        }
    }
}

