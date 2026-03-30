import SwiftUI

struct TransparencyPortalView: View {
    @EnvironmentObject var ws: WebSocketService
    @State private var selectedTab = 0
    @State private var selectedWorkflow: LearnedSequence?

    var body: some View {
        VStack(spacing: 0) {
            Picker("View", selection: $selectedTab) {
                Text("Workflows").tag(0)
                Text("Schedules").tag(1)
                Text("Actions").tag(2)
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)
            .padding(.top, 8)

            if selectedTab == 0 {
                workflowsTab
            } else if selectedTab == 1 {
                schedulesTab
            } else {
                actionsTab
            }
        }
        .navigationTitle("Automation")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            ws.requestSequences()
            ws.requestActionLog()
            ws.requestSchedules()
        }
        .sheet(item: $selectedWorkflow) { workflow in
            WorkflowDetailSheet(sequence: workflow)
        }
    }

    // MARK: - Workflows Tab

    private var workflowsTab: some View {
        ScrollView {
            if ws.learnedSequences.isEmpty {
                emptyState(
                    icon: "arrow.right.circle",
                    title: "No workflows yet",
                    subtitle: "Spectra learns your patterns. Use your phone naturally and workflows will appear here."
                )
            } else {
                LazyVStack(spacing: 12) {
                    ForEach(ws.learnedSequences) { seq in
                        WorkflowCard(sequence: seq)
                            .onTapGesture { selectedWorkflow = seq }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
            }
        }
    }

    // MARK: - Schedules Tab

    private var schedulesTab: some View {
        ScrollView {
            if ws.scheduledHooks.isEmpty {
                emptyState(
                    icon: "clock.badge.checkmark",
                    title: "No scheduled tasks",
                    subtitle: "Ask Spectra to do something on a schedule and it will appear here."
                )
            } else {
                LazyVStack(spacing: 12) {
                    ForEach(ws.scheduledHooks) { hook in
                        ScheduleCard(hook: hook, ws: ws)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
            }
        }
    }

    // MARK: - Actions Tab

    private var actionsTab: some View {
        ScrollView {
            if ws.actionLog.isEmpty {
                emptyState(
                    icon: "list.bullet.rectangle",
                    title: "No actions recorded",
                    subtitle: "As you use apps, Spectra watches and records every action in natural language."
                )
            } else {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(ws.actionLog.enumerated()), id: \.element.id) { index, entry in
                        ActionRow(entry: entry, isFirst: index == 0, isLast: index == ws.actionLog.count - 1)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
            }
        }
    }

    private func emptyState(icon: String, title: String, subtitle: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 36))
                .foregroundStyle(.secondary)
            Text(title)
                .font(.subheadline).fontWeight(.medium)
                .foregroundStyle(.secondary)
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .padding(.top, 60)
    }
}

// MARK: - Workflow Card (initial state → goal state)

private struct WorkflowCard: View {
    let sequence: LearnedSequence

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Header
            HStack {
                Image(systemName: "bolt.fill")
                    .font(.caption2)
                    .foregroundStyle(DS.primary)
                Text("Workflow")
                    .font(.caption).fontWeight(.semibold)
                    .foregroundStyle(DS.primary)
                Spacer()
                Text("Seen \(sequence.occurrenceCount)x")
                    .font(.caption2).fontWeight(.medium)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(DS.primary.opacity(0.8))
                    .clipShape(Capsule())
            }

            // Two-column: initial state → goal state
            HStack(alignment: .top, spacing: 8) {
                // Initial state
                StateBox(
                    label: "WHEN",
                    text: sequence.initialState ?? "Unknown trigger",
                    color: DS.primary
                )

                // Arrow
                VStack {
                    Spacer()
                    Image(systemName: "arrow.right")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(DS.primary.opacity(0.5))
                    Spacer()
                }
                .frame(width: 20)

                // Goal state
                StateBox(
                    label: "THEN",
                    text: sequence.goalState ?? "Unknown action",
                    color: DS.success
                )
            }
        }
        .padding(12)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

private struct StateBox: View {
    let label: String
    let text: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(color)
            Text(text)
                .font(.caption)
                .foregroundStyle(.primary)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Workflow Detail Sheet

private struct WorkflowDetailSheet: View {
    let sequence: LearnedSequence
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    // WHEN section
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 6) {
                            Circle().fill(DS.primary).frame(width: 8, height: 8)
                            Text("WHEN")
                                .font(.caption).fontWeight(.bold)
                                .foregroundStyle(DS.primary)
                        }
                        Text(sequence.initialState ?? "Unknown trigger")
                            .font(.body)
                            .foregroundStyle(.primary)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(DS.primary.opacity(0.06))
                    .clipShape(RoundedRectangle(cornerRadius: 12))

                    // Arrow
                    HStack {
                        Spacer()
                        Image(systemName: "arrow.down")
                            .font(.title3.weight(.bold))
                            .foregroundStyle(DS.primary.opacity(0.4))
                        Spacer()
                    }

                    // THEN section
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 6) {
                            Circle().fill(DS.success).frame(width: 8, height: 8)
                            Text("THEN")
                                .font(.caption).fontWeight(.bold)
                                .foregroundStyle(DS.success)
                        }
                        Text(sequence.goalState ?? "Unknown action")
                            .font(.body)
                            .foregroundStyle(.primary)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(DS.success.opacity(0.06))
                    .clipShape(RoundedRectangle(cornerRadius: 12))

                    // Meta
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Details")
                            .font(.caption).fontWeight(.semibold)
                            .foregroundStyle(.secondary)

                        HStack(spacing: 16) {
                            Label("Seen \(sequence.occurrenceCount)x", systemImage: "arrow.clockwise")
                            Label(formatDate(sequence.createdAt), systemImage: "calendar")
                        }
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    }
                    .padding(.top, 8)

                    // Raw actions
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Raw actions observed")
                            .font(.caption).fontWeight(.semibold)
                            .foregroundStyle(.secondary)

                        ForEach(Array(sequence.actions.enumerated()), id: \.offset) { i, action in
                            HStack(alignment: .top, spacing: 8) {
                                Text("\(i + 1).")
                                    .font(.caption2).monospacedDigit()
                                    .foregroundStyle(.tertiary)
                                    .frame(width: 16, alignment: .trailing)
                                Text(action)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .padding(.top, 4)
                }
                .padding(20)
            }
            .navigationTitle("Workflow Detail")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func formatDate(_ ts: Double) -> String {
        let date = Date(timeIntervalSince1970: ts)
        let fmt = DateFormatter()
        fmt.dateStyle = .medium
        fmt.timeStyle = .short
        return fmt.string(from: date)
    }
}

// MARK: - Schedule Card

private struct ScheduleCard: View {
    let hook: ScheduledHook
    let ws: WebSocketService

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header: title + state badge
            HStack {
                Text(hook.title)
                    .font(.subheadline).fontWeight(.medium)
                    .lineLimit(2)
                Spacer()
                StateBadge(state: hook.state)
            }

            // Recurrence
            if !hook.recurrenceDescription.isEmpty {
                HStack(spacing: 4) {
                    Image(systemName: hook.isRecurring ? "repeat" : "clock")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(hook.recurrenceDescription)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            // Live countdown to next run
            if let nextRun = hook.nextRunAt, hook.isActive || hook.isRunning {
                TimelineView(.periodic(from: Date(), by: 1)) { context in
                    let remaining = nextRun - context.date.timeIntervalSince1970
                    if remaining > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "timer")
                                .font(.caption2)
                                .foregroundStyle(DS.primary)
                            Text("Next run in \(formatCountdown(remaining))")
                                .font(.caption2).fontWeight(.medium)
                                .foregroundStyle(DS.primary)
                        }
                    } else if hook.isRunning {
                        HStack(spacing: 4) {
                            ProgressView().controlSize(.mini)
                            Text("Running now...")
                                .font(.caption2).fontWeight(.medium)
                                .foregroundStyle(DS.warning)
                        }
                    }
                }
            }

            // Last run info
            if let lastRun = hook.lastRunAt {
                HStack(spacing: 4) {
                    if let result = hook.lastResult {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption2).foregroundStyle(DS.success)
                        Text(result).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    } else if let error = hook.lastError {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption2).foregroundStyle(DS.danger)
                        Text(error).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer()
                    Text(formatRelative(lastRun))
                        .font(.system(size: 9)).foregroundStyle(.tertiary)
                }
            }

            // Controls
            HStack(spacing: 8) {
                if hook.isActive || hook.isFailed {
                    Button("Pause") { ws.pauseSchedule(hook.id) }
                        .buttonStyle(ScheduleButtonStyle(color: DS.warning))
                }
                if hook.isPaused {
                    Button("Resume") { ws.resumeSchedule(hook.id) }
                        .buttonStyle(ScheduleButtonStyle(color: DS.success))
                }
                if !hook.isCompleted {
                    Button("Cancel") { ws.cancelSchedule(hook.id) }
                        .buttonStyle(ScheduleButtonStyle(color: DS.danger))
                }
                if hook.isActive || hook.isPaused {
                    Button("Run Now") { ws.runScheduleNow(hook.id) }
                        .buttonStyle(ScheduleButtonStyle(color: DS.primary))
                }
                Spacer()
                if hook.fireCount > 0 {
                    Text("Ran \(hook.fireCount)x")
                        .font(.system(size: 9)).foregroundStyle(.tertiary)
                }
            }
        }
        .padding(12)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func formatCountdown(_ seconds: Double) -> String {
        let s = Int(seconds)
        if s < 60 { return "\(s)s" }
        if s < 3600 { return "\(s / 60)m \(s % 60)s" }
        return "\(s / 3600)h \((s % 3600) / 60)m"
    }

    private func formatRelative(_ ts: Double) -> String {
        let date = Date(timeIntervalSince1970: ts)
        let fmt = RelativeDateTimeFormatter()
        fmt.unitsStyle = .abbreviated
        return fmt.localizedString(for: date, relativeTo: Date())
    }
}

private struct StateBadge: View {
    let state: String
    var body: some View {
        Text(state.capitalized)
            .font(.system(size: 9, weight: .bold))
            .foregroundStyle(.white)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(badgeColor)
            .clipShape(Capsule())
    }
    private var badgeColor: Color {
        switch state {
        case "active": return DS.success
        case "running": return DS.primary
        case "paused": return DS.warning
        case "completed": return .gray
        case "failed": return DS.danger
        default: return .gray
        }
    }
}

private struct ScheduleButtonStyle: ButtonStyle {
    let color: Color
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption2).fontWeight(.medium)
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.12))
            .clipShape(Capsule())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

private struct ScheduleSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption).fontWeight(.bold)
                .foregroundStyle(.secondary)
                .padding(.leading, 4)
            content()
        }
    }
}

// MARK: - Action Row (timeline)

private struct ActionRow: View {
    let entry: ActionLogEntry
    let isFirst: Bool
    let isLast: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 0) {
                Rectangle()
                    .fill(isFirst ? .clear : Color.secondary.opacity(0.2))
                    .frame(width: 1.5, height: 8)
                Circle()
                    .fill(appColor)
                    .frame(width: 7, height: 7)
                Rectangle()
                    .fill(isLast ? .clear : Color.secondary.opacity(0.2))
                    .frame(width: 1.5)
                    .frame(maxHeight: .infinity)
            }
            .frame(width: 7)

            VStack(alignment: .leading, spacing: 2) {
                Text(entry.action)
                    .font(.caption)
                HStack(spacing: 4) {
                    Text(appShort)
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(appColor)
                    Text(formatTime(entry.timestamp))
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                }
            }
            .padding(.vertical, 4)
        }
    }

    private var appShort: String {
        entry.app.split(separator: ".").last.map(String.init) ?? entry.app
    }

    private var appColor: Color {
        let hash = abs(appShort.hashValue)
        let colors: [Color] = [DS.primary, DS.success, .orange, .pink, .cyan, .indigo]
        return colors[hash % colors.count]
    }

    private func formatTime(_ ts: Double) -> String {
        let date = Date(timeIntervalSince1970: ts)
        let fmt = DateFormatter()
        fmt.dateFormat = "h:mm a"
        return fmt.string(from: date)
    }
}
