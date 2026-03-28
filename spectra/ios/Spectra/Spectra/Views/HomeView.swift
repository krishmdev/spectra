import SwiftUI

struct HomeView: View {
    @EnvironmentObject var ws: WebSocketService
    @State private var inputText = ""
    @State private var navigateToTask = false
    @State private var taskHistory: [CompletedTask] = []
    @State private var currentTask = ""

    var body: some View {
        NavigationStack {
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

                // Prompt
                Text("What can I help you with?")
                    .font(.subheadline).foregroundStyle(.secondary)
                    .padding(.bottom, 12)

                // Mic button — triggers server-side voice capture on Mac
                Button {
                    if ws.isVoiceListening {
                        ws.sendVoiceStop()
                    } else {
                        ws.sendVoiceStart()
                    }
                } label: {
                    ZStack {
                        Circle()
                            .fill(DS.primary)
                            .frame(width: DS.micSize, height: DS.micSize)
                            .scaleEffect(ws.isVoiceListening ? 1.15 : 1.0)
                            .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: ws.isVoiceListening)

                        Image(systemName: ws.isVoiceListening ? "waveform" : "mic.fill")
                            .font(.title3)
                            .foregroundStyle(.white)
                    }
                }
                .padding(.bottom, 12)

                // Voice status
                if ws.isVoiceListening {
                    Text("Listening on Mac mic...")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 20)
                        .padding(.bottom, 4)
                } else if let err = ws.voiceError {
                    Text(err)
                        .font(.caption)
                        .foregroundStyle(DS.danger)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20)
                        .padding(.bottom, 4)
                }

                // Text input
                HStack(spacing: 8) {
                    TextField("Type a task...", text: $inputText)
                        .textFieldStyle(.roundedBorder)
                        .frame(height: 44)
                        .onSubmit { submitTask() }

                    Button { submitTask() } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title2)
                            .foregroundStyle(DS.primary)
                    }
                    .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 16)
            }
            .navigationDestination(isPresented: $navigateToTask) {
                TaskRunningView(taskName: currentTask)
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
        currentTask = task
        inputText = ""
        ws.sendCommand(task)
        navigateToTask = true
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
