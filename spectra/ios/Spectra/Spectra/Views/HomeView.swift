import SwiftUI

struct HomeView: View {
    @EnvironmentObject var ws: WebSocketService
    @State private var inputText = ""
    @State private var navPath = NavigationPath()
    @State private var taskHistory: [CompletedTask] = []
    @State private var currentTask = ""
    @State private var showPortal = false

    var body: some View {
        NavigationStack(path: $navPath) {
            VStack(spacing: 0) {
                // Header with hamburger menu
                HStack {
                    NavigationLink(destination: TransparencyPortalView().environmentObject(ws)) {
                        Image(systemName: "line.3.horizontal")
                            .font(.title3)
                            .foregroundStyle(DS.primary)
                    }
                    Spacer()
                    VStack(spacing: 2) {
                        Text("Spectra")
                            .font(.title2).fontWeight(.semibold)
                        Text("your iOS agent")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    // Balance the hamburger icon width
                    Color.clear.frame(width: 24, height: 24)
                }
                .padding(.horizontal, 20)
                .padding(.top, 8)

                // Sequence suggestion banner
                if let suggestion = ws.sequenceSuggestion {
                    SequenceSuggestionBanner(
                        suggestion: suggestion,
                        onAccept: { ws.acceptSequenceSuggestion(suggestion.nextAction) },
                        onDecline: { ws.declineSequenceSuggestion() }
                    )
                }

                // Scrollable content: session task history
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if !taskHistory.isEmpty {
                            ForEach(taskHistory) { task in
                                TaskCard(task: task)
                                    .padding(.horizontal, 20)
                                    .padding(.bottom, 8)
                            }
                        }
                    }
                    .padding(.top, 12)
                }

                Spacer()

                Text("What can I help you with?")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .padding(.bottom, 8)

                VoiceInputSection(inputText: $inputText, onSubmit: submitTask)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 16)
            }
            .navigationDestination(for: String.self) { taskName in
                TaskRunningView(taskName: taskName, onNewTask: {
                    navPath = NavigationPath()
                })
                .environmentObject(ws)
            }
            .onChange(of: ws.voiceTranscript) { _, transcript in
                if let transcript = transcript, !transcript.isEmpty {
                    inputText = transcript
                    ws.voiceTranscript = nil
                    submitTask()
                }
            }
            .onChange(of: ws.taskResult) { _, result in
                if let result = result {
                    taskHistory.insert(
                        CompletedTask(
                            summary: result.summary,
                            steps: result.steps,
                            duration: result.duration,
                            app: ws.latestStatus?.app ?? "",
                            success: result.success
                        ),
                        at: 0
                    )
                }
            }
        }
    }

    private func submitTask() {
        let task = inputText.trimmingCharacters(in: .whitespaces)
        guard !task.isEmpty else { return }
        inputText = ""
        ws.sendCommand(task)
        navPath.append(task)
    }
}

// MARK: - Sequence Suggestion Banner

private struct SequenceSuggestionBanner: View {
    let suggestion: SequenceSuggestion
    let onAccept: () -> Void
    let onDecline: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "sparkles")
                    .font(.caption)
                    .foregroundStyle(DS.primary)
                Text("Suggested next action")
                    .font(.caption2).fontWeight(.semibold)
                    .foregroundStyle(DS.primary)
                Spacer()
                Text("Seen \(suggestion.occurrenceCount)x")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(.secondary)
            }

            Text(suggestion.nextAction)
                .font(.subheadline).fontWeight(.medium)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text("After: \(suggestion.prefix.last ?? "")")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 12) {
                Button(action: onDecline) {
                    Text("Not now")
                        .font(.caption).fontWeight(.medium)
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 6)
                        .padding(.horizontal, 14)
                        .background(Color.secondary.opacity(0.12))
                        .clipShape(Capsule())
                }
                Button(action: onAccept) {
                    Text("Yes, do it")
                        .font(.caption).fontWeight(.semibold)
                        .foregroundStyle(.white)
                        .padding(.vertical, 6)
                        .padding(.horizontal, 14)
                        .background(DS.primary)
                        .clipShape(Capsule())
                }
            }
        }
        .padding(12)
        .background(DS.primaryTint)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal, 20)
        .padding(.top, 8)
    }
}

// MARK: - Task Card

private struct TaskCard: View {
    let task: CompletedTask

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) {
                Image(systemName: task.success ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(task.success ? DS.success : DS.danger)
                    .font(.caption)
                Text(task.success ? "Completed" : "Failed")
                    .font(.caption2).fontWeight(.semibold)
                    .foregroundStyle(task.success ? DS.success : DS.danger)
            }
            Text(task.summary)
                .font(.subheadline)
                .lineLimit(2)
            Text("\(task.steps) steps \u{00B7} \(String(format: "%.1f", task.duration))s\(task.app.isEmpty ? "" : " \u{00B7} \(task.app)")")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}
