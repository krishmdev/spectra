import SwiftUI

struct HomeView: View {
    @EnvironmentObject var ws: WebSocketService
    @State private var inputText = ""
    @State private var navPath = NavigationPath()
    @State private var taskHistory: [CompletedTask] = []
    
    var body: some View {
        NavigationStack(path: $navPath) {
            VStack(spacing: 0) {
                // Header
                VStack(spacing: 2) {
                    Text("Spectra")
                        .font(.title2).fontWeight(.semibold)
                    Text("your iOS agent")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .padding(.top, 8)

                // Task history
                ScrollView {
                    LazyVStack(spacing: 12) {
                        ForEach(taskHistory) { task in
                            TaskCard(task: task)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
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
