import SwiftUI

struct ResultView: View {
    @EnvironmentObject var ws: WebSocketService
    /// Pops the whole task flow so home is visible again.
    var onNewTask: () -> Void = {}

    private var result: TaskResult? { ws.taskResult }
    private var success: Bool { result?.success ?? false }

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            // Success / failure icon
            Image(systemName: success ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(success ? DS.success : DS.danger)

            // Summary
            Text(result?.summary ?? "Task finished")
                .font(.system(size: 16, weight: .semibold))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            // Stats pills
            if let result = result {
                HStack(spacing: 12) {
                    StatPill(text: "\(result.steps) steps")
                    StatPill(text: "\(String(format: "%.1f", result.duration))s")
                    if !ws.memoryItems.isEmpty {
                        StatPill(text: "\(ws.memoryItems.count) saved")
                    }
                }
            }

            // Memory section
            if !ws.memoryItems.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("MEMORY")
                        .font(.caption).fontWeight(.semibold)
                        .foregroundStyle(.secondary)
                    FlowLayout(spacing: 8) {
                        ForEach(ws.memoryItems) { item in
                            MemoryPill(item: item)
                        }
                    }
                }
                .padding(.horizontal, 20)
            }

            Spacer()

            // New task button — pop entire task stack back to home
            Button {
                onNewTask()
            } label: {
                Text("New task")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(DS.primary)
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: DS.cardRadius))
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 16)
        }
        .navigationBarBackButtonHidden(true)
    }
}

private struct StatPill: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.caption).fontWeight(.medium)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Color(.secondarySystemBackground))
            .clipShape(Capsule())
    }
}
