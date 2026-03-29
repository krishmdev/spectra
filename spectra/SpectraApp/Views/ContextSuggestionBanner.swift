import SwiftUI

struct ContextSuggestionBanner: View {
    let suggestion: String
    let onAccept: () -> Void
    let onDecline: () -> Void
    
    @State private var offset: CGFloat = -150
    @State private var opacity: Double = 0
    @State private var hasResponded = false
    
    var body: some View {
        VStack(spacing: 12) {
            Text(suggestion)
                .font(.subheadline)
                .fontWeight(.medium)
                .multilineTextAlignment(.center)
                .foregroundColor(.primary)
                .padding(.horizontal)
            
            HStack(spacing: 20) {
                Button(action: {
                    hasResponded = true
                    onDecline()
                    dismiss()
                }) {
                    Text("Not now")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundColor(.secondary)
                        .padding(.vertical, 8)
                        .padding(.horizontal, 16)
                        .background(Color.secondary.opacity(0.15))
                        .cornerRadius(20)
                }
                
                Button(action: {
                    hasResponded = true
                    onAccept()
                    dismiss()
                }) {
                    Text("Yes, do it")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundColor(.white)
                        .padding(.vertical, 8)
                        .padding(.horizontal, 16)
                        .background(Color.accentColor)
                        .cornerRadius(20)
                }
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(UIColor.systemBackground))
                .shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5)
        )
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .offset(y: offset)
        .opacity(opacity)
        .onAppear {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) {
                offset = 0
                opacity = 1
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 12) {
                if !hasResponded {
                    hasResponded = true
                    onDecline()
                    dismiss()
                }
            }
        }
    }
    
    private func dismiss() {
        withAnimation(.easeIn(duration: 0.3)) {
            offset = -150
            opacity = 0
        }
    }
}
