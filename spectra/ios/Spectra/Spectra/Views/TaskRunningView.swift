import SwiftUI

struct TaskRunningView: View {
    let taskName: String
    @EnvironmentObject var ws: WebSocketService
    @Environment(\.dismiss) private var dismiss
    @State private var showResult = false

    private var badge: (String, Color, Color) {
        if ws.taskResult != nil { return ("Done", DS.success.opacity(0.15), DS.success) }
        if ws.confirmationRequest != nil || ws.handoffRequest != nil {
            return ("Waiting", DS.warningLight, DS.warningBadgeText)
        }
        return ("Running", DS.warningLight, DS.warningBadgeText)
    }

    private var currentStep: Int {
        ws.latestStatus?.step ?? 0
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    // Plan section
                    if let plan = ws.planPreview {
                        SectionHeader(title: "Plan")
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(Array(plan.steps.enumerated()), id: \.offset) { idx, step in
                                PlanStepRow(
                                    index: idx + 1,
                                    text: step,
                                    status: stepStatus(for: idx + 1)
                                )
                            }
                        }
                    }

                    // Memory section
                    if !ws.memoryItems.isEmpty {
                        SectionHeader(title: "Memory")
                        FlowLayout(spacing: 8) {
                            ForEach(ws.memoryItems) { item in
                                MemoryPill(item: item)
                            }
                        }
                    }

                    // Live actions
                    SectionHeader(title: "Live actions")
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(ws.statusHistory.reversed()) { status in
                            HStack(spacing: 8) {
                                Text("Step \(status.step)")
                                    .font(.caption2)
                                    .foregroundStyle(DS.success)
                                    .frame(width: 44, alignment: .leading)
                                Text("\(status.action): \(status.detail)")
                                    .font(.caption)
                                    .lineLimit(1)
                            }
                            .id(status.id)
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 16)
            }
        }
        .navigationTitle(taskName)
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(true)
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) {
                Button { dismiss() } label: {
                    Image(systemName: "chevron.left")
                        .fontWeight(.semibold)
                }
            }
            ToolbarItem(placement: .navigationBarTrailing) {
                StatusBadge(text: badge.0, bg: badge.1, fg: badge.2)
            }
        }
        .safeAreaInset(edge: .bottom) {
            if ws.taskResult == nil {
                Button {
                    ws.sendStop()
                } label: {
                    Text("Stop task")
                        .fontWeight(.medium)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .foregroundStyle(DS.danger)
                        .overlay(
                            RoundedRectangle(cornerRadius: 20)
                                .stroke(DS.danger, lineWidth: 1)
                        )
                }
                .padding(.horizontal, 32)
                .padding(.bottom, 16)
            }
        }
        .sheet(isPresented: Binding(
            get: { ws.confirmationRequest != nil || ws.handoffRequest != nil },
            set: { if !$0 { ws.confirmationRequest = nil; ws.handoffRequest = nil } }
        )) {
            ConfirmationSheet()
                .environmentObject(ws)
        }
        .sheet(isPresented: Binding(
            get: { ws.askUserRequest != nil },
            set: { if !$0 { ws.askUserRequest = nil } }
        )) {
            AskUserSheet()
                .environmentObject(ws)
        }
        .onChange(of: ws.taskResult) { _, result in
            if result != nil {
                showResult = true
            }
        }
        .navigationDestination(isPresented: $showResult) {
            ResultView()
                .environmentObject(ws)
        }
    }

    private func stepStatus(for step: Int) -> StepStatus {
        if step < currentStep { return .done }
        if step == currentStep { return .current }
        return .upcoming
    }
}

// MARK: - Subcomponents

private struct SectionHeader: View {
    let title: String
    var body: some View {
        Text(title.uppercased())
            .font(.caption).fontWeight(.semibold)
            .foregroundStyle(.secondary)
    }
}

private struct StatusBadge: View {
    let text: String
    let bg: Color
    let fg: Color
    var body: some View {
        Text(text)
            .font(.caption2).fontWeight(.semibold)
            .foregroundStyle(fg)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(bg)
            .clipShape(Capsule())
    }
}

struct PlanStepRow: View {
    let index: Int
    let text: String
    let status: StepStatus

    var body: some View {
        HStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(circleColor)
                    .frame(width: DS.stepIndicatorSize, height: DS.stepIndicatorSize)
                if status == .done {
                    Image(systemName: "checkmark")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(.white)
                } else {
                    Text("\(index)")
                        .font(.system(size: 10, weight: status == .current ? .semibold : .regular))
                        .foregroundStyle(numberColor)
                }
            }
            Text(text)
                .font(.caption)
                .fontWeight(status == .current ? .semibold : .regular)
                .foregroundStyle(status == .upcoming ? .secondary : .primary)
        }
    }

    private var circleColor: Color {
        switch status {
        case .done: return DS.success
        case .current: return DS.warning
        case .upcoming: return Color(.systemGray4)
        }
    }

    private var numberColor: Color {
        switch status {
        case .done: return .white
        case .current: return .white
        case .upcoming: return .gray
        }
    }
}

struct MemoryPill: View {
    let item: MemoryItem
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(item.key)
                .font(.caption2)
                .foregroundStyle(DS.memoryTextDark)
            Text(item.value)
                .font(.subheadline).fontWeight(.semibold)
                .foregroundStyle(DS.memoryTextDeep)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(DS.primaryTint)
        .clipShape(RoundedRectangle(cornerRadius: DS.pillRadius))
    }
}

// MARK: - FlowLayout

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = arrange(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(proposal: proposal, subviews: subviews)
        for (index, frame) in result.frames.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY),
                proposal: ProposedViewSize(frame.size)
            )
        }
    }

    private func arrange(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, frames: [CGRect]) {
        let maxWidth = proposal.width ?? .infinity
        var frames: [CGRect] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            frames.append(CGRect(origin: CGPoint(x: x, y: y), size: size))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
        }

        let totalHeight = y + rowHeight
        return (CGSize(width: maxWidth, height: totalHeight), frames)
    }
}
