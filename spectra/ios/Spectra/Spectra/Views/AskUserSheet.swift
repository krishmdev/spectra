import SwiftUI

struct AskUserSheet: View {
    @EnvironmentObject var ws: WebSocketService
    @Environment(\.dismiss) private var dismiss
    @State private var customAnswer = ""

    private var request: AskUserRequest? { ws.askUserRequest }

    var body: some View {
        VStack(spacing: 16) {
            // Drag handle
            RoundedRectangle(cornerRadius: 2)
                .fill(Color(.systemGray3))
                .frame(width: 36, height: 4)
                .padding(.top, 8)

            // Header
            HStack(spacing: 10) {
                Circle()
                    .fill(DS.primaryTint)
                    .frame(width: 36, height: 36)
                    .overlay(
                        Image(systemName: "questionmark")
                            .foregroundStyle(DS.primary)
                            .font(.body).fontWeight(.semibold)
                    )
                VStack(alignment: .leading, spacing: 2) {
                    Text("Agent needs your input")
                        .font(.headline)
                    Text(request?.question ?? "")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.horizontal, 20)

            // Options (if provided)
            if let options = request?.options, !options.isEmpty {
                VStack(spacing: 8) {
                    ForEach(options, id: \.self) { option in
                        Button {
                            sendAnswer(option)
                        } label: {
                            Text(option)
                                .font(.subheadline).fontWeight(.medium)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 10)
                                .overlay(
                                    RoundedRectangle(cornerRadius: DS.buttonRadius)
                                        .stroke(DS.primary, lineWidth: 1)
                                )
                                .foregroundStyle(DS.primary)
                        }
                    }
                }
                .padding(.horizontal, 20)
            }

            Spacer()

            // Free-text input
            HStack(spacing: 8) {
                TextField("Type your answer...", text: $customAnswer)
                    .textFieldStyle(.roundedBorder)
                    .frame(height: 44)
                    .onSubmit { sendCustom() }

                Button { sendCustom() } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                        .foregroundStyle(DS.primary)
                }
                .disabled(customAnswer.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 20)
        }
        .presentationDetents([.medium])
        .presentationDragIndicator(.hidden)
    }

    private func sendAnswer(_ answer: String) {
        ws.sendUserAnswer(answer)
        dismiss()
    }

    private func sendCustom() {
        let answer = customAnswer.trimmingCharacters(in: .whitespaces)
        guard !answer.isEmpty else { return }
        sendAnswer(answer)
    }
}
