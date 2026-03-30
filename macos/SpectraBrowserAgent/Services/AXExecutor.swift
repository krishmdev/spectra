import Foundation
import ApplicationServices
import AppKit

class AXExecutor {
    private let kAXPressAction = "AXPress"
    private let kAXShowMenuAction = "AXShowMenu"
    private let kAXFocusAction = "AXFocus"
    
    func execute(action: String, ref: Int?, params: [String: Any], refMap: [Int: AXRefEntry]) -> String {
        // Ensure Safari is active for any interaction
        activateSafari()
        
        guard let refNum = ref ?? (params["ref"] as? Int), let entry = refMap[refNum] else {
            if action == "scroll" { return executeScroll(direction: params["direction"] as? String ?? "down", refMap: refMap) }
            if action == "go_back" { return executeGoBack() }
            if action == "navigate" { return executeNavigate(url: params["url"] as? String ?? "") }
            return "Error: ref [\(ref ?? 0)] not found and action [\(action)] requires an element."
        }
        
        switch action {
        case "tap":
            return executeTap(entry: entry)
        case "type_text":
            return executeTypeText(entry: entry, text: params["text"] as? String ?? "")
        default:
            return "Error: Unknown action [\(action)]"
        }
    }
    
    private func activateSafari() {
        if let safari = NSWorkspace.shared.runningApplications.first(where: { $0.bundleIdentifier == "com.apple.Safari" }) {
            safari.activate(options: .activateIgnoringOtherApps)
            usleep(100000) // 100ms for activation
        }
    }
    
    private func executeTap(entry: AXRefEntry) -> String {
        let center = CGPoint(x: entry.frame.midX, y: entry.frame.midY)
        
        // 1. Move mouse to trigger hovers (NYT article cards etc.)
        moveMouse(to: center)
        usleep(50000) // 50ms hover
        
        // 2. Try AXPress
        let result = AXUIElementPerformAction(entry.element, kAXPressAction as CFString)
        if result == .success {
            return "Tapped [\(entry.label)] via AX"
        }
        
        // 3. Fallback to CGEvent mouse click
        click(at: center)
        return "Tapped [\(entry.label)] via CGEvent"
    }
    
    private func executeTypeText(entry: AXRefEntry, text: String) -> String {
        // 1. Focus the element
        AXUIElementPerformAction(entry.element, kAXFocusAction as CFString)
        usleep(100000)
        
        // 2. Robust Clear: Cmd+A then Backspace
        postKeyboardEvent(keyCode: 0, modifiers: .maskCommand) // Cmd+A
        usleep(50000)
        postKeyboardEvent(keyCode: 51) // Backspace
        usleep(50000)
        
        // 3. Set Value via AX
        let result = AXUIElementSetAttributeValue(entry.element, kAXValueAttribute as CFString, text as CFTypeRef)
        
        // 4. Post-Type: Enter (to trigger search/submit listeners)
        postKeyboardEvent(keyCode: 36) // Return
        
        if result == .success {
            return "Cleared and typed [\(text)] into [\(entry.label)]"
        }
        return "Error: Failed to type into [\(entry.label)]"
    }
    
    private func executeScroll(direction: String, refMap: [Int: AXRefEntry]) -> String {
        guard let webArea = refMap.values.first(where: { $0.role == "AXWebArea" }) else {
            return "Error: Cannot find web area to scroll"
        }
        
        let center = CGPoint(x: webArea.frame.midX, y: webArea.frame.midY)
        let deltaY = direction == "down" ? -120 : 120
        scroll(at: center, deltaY: Int32(deltaY))
        return "Scrolled \(direction)"
    }
    
    private func executeGoBack() -> String {
        let scriptSource = "tell application \"Safari\" to do JavaScript \"history.back()\" in current tab of front window"
        return runAppleScript(source: scriptSource) ? "Navigated back" : "Error: Failed to navigate back"
    }
    
    private func executeNavigate(url: String) -> String {
        // Strip quotes to prevent AppleScript injection
        let safeURL = url
            .replacingOccurrences(of: "\"", with: "")
            .replacingOccurrences(of: "\\", with: "")
        let scriptSource = "tell application \"Safari\" to set URL of current tab of front window to \"\(safeURL)\""
        return runAppleScript(source: scriptSource) ? "Navigated to \(safeURL)" : "Error: Failed to navigate"
    }
    
    // MARK: - Event Simulation
    
    private func moveMouse(to point: CGPoint) {
        let source = CGEventSource(stateID: .hidSystemState)
        let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)
        move?.post(tap: .cghidEventTap)
    }
    
    private func click(at point: CGPoint) {
        let source = CGEventSource(stateID: .hidSystemState)
        let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
        let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
        
        down?.post(tap: .cghidEventTap)
        usleep(10000)
        up?.post(tap: .cghidEventTap)
    }
    
    private func postKeyboardEvent(keyCode: CGKeyCode, modifiers: CGEventFlags = []) {
        let source = CGEventSource(stateID: .hidSystemState)
        let down = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: true)
        let up = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: false)
        
        down?.flags = modifiers
        up?.flags = modifiers
        
        down?.post(tap: .cghidEventTap)
        usleep(10000)
        up?.post(tap: .cghidEventTap)
    }
    
    private func scroll(at point: CGPoint, deltaY: Int32) {
        let source = CGEventSource(stateID: .hidSystemState)
        let scroll = CGEvent(scrollWheelEventSource: source, wheelCount: 1, wheel1: deltaY, wheel2: 0, wheel3: 0)
        scroll?.location = point
        scroll?.post(tap: .cghidEventTap)
    }
    
    private func runAppleScript(source: String) -> Bool {
        if let script = NSAppleScript(source: source) {
            var error: NSDictionary?
            script.executeAndReturnError(&error)
            return error == nil
        }
        return false
    }
}
