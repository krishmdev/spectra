import SwiftUI

struct TransparencyPortalView: View {
    @EnvironmentObject var ws: WebSocketService
    @State private var selectedTab = 0

    var body: some View {
        VStack(spacing: 0) {
            // Tab picker
            Picker("View", selection: $selectedTab) {
                Text("Sequences").tag(0)
                Text("All Actions").tag(1)
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)
            .padding(.top, 8)

            if selectedTab == 0 {
                sequencesTab
            } else {
                actionsTab
            }
        }
        .navigationTitle("Context Triggers")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            ws.requestSequences()
            ws.requestActionLog()
        }
    }

    // MARK: - Sequences Tab

    private var sequencesTab: some View {
        ScrollView {
            if ws.learnedSequences.isEmpty {
                emptyState(
                    icon: "arrow.triangle.branch",
                    title: "No sequences yet",
                    subtitle: "Spectra learns patterns from your repeated actions. Keep using your phone and sequences will appear here."
                )
            } else {
                LazyVStack(spacing: 12) {
                    ForEach(ws.learnedSequences) { seq in
                        SequenceCard(sequence: seq)
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
                LazyVStack(spacing: 0) {
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

// MARK: - Sequence Card

private struct SequenceCard: View {
    let sequence: LearnedSequence

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header
            HStack {
                Image(systemName: "arrow.triangle.branch")
                    .font(.caption)
                    .foregroundStyle(DS.primary)
                Text("Sequence")
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

            // Action chain
            ForEach(Array(sequence.actions.enumerated()), id: \.offset) { index, action in
                HStack(alignment: .top, spacing: 8) {
                    VStack(spacing: 0) {
                        Circle()
                            .fill(index < sequence.actions.count - 1 ? DS.primary.opacity(0.6) : DS.success)
                            .frame(width: 8, height: 8)
                            .padding(.top, 5)
                        if index < sequence.actions.count - 1 {
                            Rectangle()
                                .fill(DS.primary.opacity(0.2))
                                .frame(width: 1.5)
                                .frame(maxHeight: .infinity)
                        }
                    }
                    .frame(width: 8)

                    VStack(alignment: .leading, spacing: 2) {
                        if index == sequence.actions.count - 1 {
                            Text("TRIGGERS")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(DS.success)
                        }
                        Text(action)
                            .font(.caption)
                            .foregroundStyle(index == sequence.actions.count - 1 ? .primary : .secondary)
                            .fontWeight(index == sequence.actions.count - 1 ? .medium : .regular)
                    }
                }
            }
        }
        .padding(12)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: - Action Row (timeline)

private struct ActionRow: View {
    let entry: ActionLogEntry
    let isFirst: Bool
    let isLast: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            // Timeline dot + line
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
