import SwiftUI

/// Voice + text composer: Mac-hosted capture via WebSocket (`voice_start` / `voice_stop`).
struct VoiceInputSection: View {
    @EnvironmentObject var ws: WebSocketService
    @Binding var inputText: String
    var onSubmit: () -> Void

    @State private var voiceTapCount = 0
    @State private var isPulsing = false

    private var canUseVoice: Bool {
        ws.isConnected
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            headerRow
            voiceBlock
            if ws.isVoiceListening || ws.voiceError != nil {
                statusBlock
            }
            Divider()
                .padding(.vertical, 14)
            textRow
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: DS.speechCardRadius, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
        )
        .overlay(
            RoundedRectangle(cornerRadius: DS.speechCardRadius, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.06), lineWidth: 1)
        )
        .onChange(of: ws.isVoiceListening) { _, isListening in
            if isListening {
                withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                    isPulsing = true
                }
            } else {
                withAnimation(.easeOut(duration: 0.3)) {
                    isPulsing = false
                }
            }
        }
    }

    private var headerRow: some View {
        HStack(alignment: .center, spacing: 8) {
            Image(systemName: "waveform.and.mic")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(DS.primary)
            Text("Voice command")
                .font(.subheadline.weight(.semibold))
            Spacer()
            connectionPill
        }
        .padding(.bottom, 14)
    }

    private var connectionPill: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(ws.isConnected ? DS.success : Color.orange.opacity(0.85))
                .frame(width: 7, height: 7)
            Text(ws.isConnected ? "Ready" : "Connecting…")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            Capsule()
                .fill(Color(.tertiarySystemFill))
        )
    }

    private var voiceBlock: some View {
        HStack(alignment: .center, spacing: 16) {
            voiceButton
            VStack(alignment: .leading, spacing: 4) {
                Text(ws.isVoiceListening ? "Listening…" : "Tap to speak")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(.primary)
                if ws.isVoiceListening {
                    Text("Your Mac microphone is on. Speak clearly, then tap again to stop.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var voiceButton: some View {
        Button {
            voiceTapCount += 1
            if ws.isVoiceListening {
                ws.sendVoiceStop()
            } else {
                guard canUseVoice else { return }
                ws.sendVoiceStart()
            }
        } label: {
            ZStack {
                if ws.isVoiceListening {
                    // Pulsating appealing glow
                    Circle()
                        .fill(DS.primary.opacity(0.2))
                        .frame(width: DS.voiceMicOuter + 20, height: DS.voiceMicOuter + 20)
                        .scaleEffect(isPulsing ? 1.4 : 0.8)
                        .opacity(isPulsing ? 0 : 1)
                    
                    Circle()
                        .fill(DS.primary.opacity(0.3))
                        .frame(width: DS.voiceMicOuter + 8, height: DS.voiceMicOuter + 8)
                        .scaleEffect(isPulsing ? 1.15 : 0.95)
                        .opacity(isPulsing ? 0 : 1)
                }
                
                Circle()
                    .fill(canUseVoice ? DS.primary : DS.primary.opacity(0.45))
                    .frame(width: DS.micSize, height: DS.micSize)
                    .shadow(color: DS.primary.opacity(ws.isVoiceListening ? 0.5 : 0.18), radius: ws.isVoiceListening ? 12 : 8, y: 3)
                
                Image(systemName: ws.isVoiceListening ? "stop.fill" : "mic.fill")
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: DS.voiceMicOuter, height: DS.voiceMicOuter)
            .animation(.easeInOut(duration: 0.3), value: ws.isVoiceListening)
        }
        .buttonStyle(.plain)
        .disabled(!canUseVoice && !ws.isVoiceListening)
        .opacity(canUseVoice || ws.isVoiceListening ? 1 : 0.55)
        .accessibilityLabel(ws.isVoiceListening ? "Stop listening" : "Start voice command")
        .accessibilityHint("Sends audio from your Mac microphone to Spectra")
        .sensoryFeedback(.impact(weight: .medium, intensity: 0.85), trigger: voiceTapCount)
    }

    @ViewBuilder
    private var statusBlock: some View {
        VStack(alignment: .leading, spacing: 10) {
            if ws.isVoiceListening {
                Text("Listening on Mac mic")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(DS.primary)
                    .padding(.top, 4)
            }
            if let err = ws.voiceError {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(DS.danger)
                    Text(err)
                        .font(.caption)
                        .foregroundStyle(DS.danger)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: DS.buttonRadius, style: .continuous)
                        .fill(DS.danger.opacity(0.12))
                )
            }
        }
        .padding(.top, 14)
    }

    private var textRow: some View {
        HStack(spacing: 10) {
            TextField("Or type a task…", text: $inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...4)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: DS.buttonRadius, style: .continuous)
                        .fill(Color(.tertiarySystemFill))
                )
                .onSubmit { onSubmit() }

            Button(action: onSubmit) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title)
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(DS.primary)
            }
            .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty)
            .accessibilityLabel("Send task")
        }
    }
}

#Preview {
    struct PreviewWrap: View {
        @State private var text = ""
        var body: some View {
            VoiceInputSection(inputText: $text, onSubmit: {})
                .environmentObject(WebSocketService())
                .padding()
        }
    }
    return PreviewWrap()
}
