import SwiftUI

struct ConfirmationSheet: View {
    @EnvironmentObject var ws: WebSocketService
    @Environment(\.dismiss) private var dismiss

    private var isHandoff: Bool { ws.handoffRequest != nil }

    var body: some View {
        VStack(spacing: 16) {
            // Drag handle
            RoundedRectangle(cornerRadius: 2)
                .fill(Color(.systemGray3))
                .frame(width: 36, height: 4)
                .padding(.top, 8)

            // Header
            VStack(spacing: 6) {
                HStack(spacing: 10) {
                    Circle()
                        .fill(DS.warningLight)
                        .frame(width: 36, height: 36)
                        .overlay(
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(DS.warning)
                                .font(.body)
                        )
                    VStack(alignment: .leading, spacing: 2) {
                        Text(isHandoff ? "Your turn" : "Confirm action")
                            .font(.headline)
                        Text(isHandoff
                             ? (ws.handoffRequest?.reason ?? "")
                             : "Spectra wants to perform this action")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
            }
            .padding(.horizontal, 20)

            // Detail card
            if let req = ws.confirmationRequest {
                VStack(spacing: 8) {
                    DetailRow(label: "App", value: req.app)
                    DetailRow(label: "Action", value: req.action)
                    if !req.label.isEmpty {
                        DetailRow(label: "Target", value: req.label)
                    }
                    if !req.detail.isEmpty {
                        DetailRow(label: "Detail", value: req.detail)
                    }
                }
                .padding(14)
                .background(Color(.secondarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .padding(.horizontal, 20)
            }

            Spacer()

            // Buttons
            if isHandoff {
                Button {
                    ws.sendTakeoverDone()
                    dismiss()
                } label: {
                    Text("I'm done")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(DS.primary)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: DS.buttonRadius))
                }
                .padding(.horizontal, 20)
            } else {
                HStack(spacing: 12) {
                    Button {
                        ws.sendConfirmation(false)
                        dismiss()
                    } label: {
                        Text("Cancel")
                            .fontWeight(.medium)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .overlay(
                                RoundedRectangle(cornerRadius: DS.buttonRadius)
                                    .stroke(Color(.systemGray3), lineWidth: 1)
                            )
                    }
                    .foregroundStyle(.primary)

                    Button {
                        ws.sendConfirmation(true)
                        dismiss()
                    } label: {
                        Text("Confirm")
                            .fontWeight(.semibold)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .background(DS.primary)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: DS.buttonRadius))
                    }
                }
                .padding(.horizontal, 20)
            }
        }
        .padding(.bottom, 20)
        .presentationDetents([.medium])
        .presentationDragIndicator(.hidden)
    }
}

private struct DetailRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.subheadline)
                .fontWeight(.medium)
        }
    }
}
