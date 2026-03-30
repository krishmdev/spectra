import Foundation
import ApplicationServices
import AppKit

struct AXRefEntry {
    let element: AXUIElement
    let role: String
    let label: String
    let frame: CGRect
}

struct JSPageContext {
    let paywallDetected: Bool
    let paywallType: String
    let articles: [String]
    let headings: [String]
    let alerts: [String]
}

struct AXSnapshot {
    let tree: String
    let refMap: [Int: AXRefEntry]
    let url: String
    let title: String
    let nodeCount: Int
    let jsContext: JSPageContext?
}

class AXTreeReader {
    private var refMap: [Int: AXRefEntry] = [:]
    private var counter = 0
    private let maxNodes = 120
    private let maxDepth = 8

    private let interactiveRoles: Set<String> = [
        "AXButton", "AXLink", "AXTextField", "AXSecureTextField",
        "AXSearchField", "AXCheckBox", "AXRadioButton", "AXComboBox",
        "AXMenuItem", "AXTab"
    ]

    private let structuralRoles: Set<String> = [
        "AXHeading", "AXList", "AXNavigation", "AXMain",
        "AXSearch", "AXBanner", "AXContentInfo", "AXWebArea"
    ]

    func snapshot(safariPID: pid_t) -> AXSnapshot? {
        self.refMap = [:]
        self.counter = 0

        let safariApp = AXUIElementCreateApplication(safariPID)

        guard let window = getAttribute(element: safariApp, attribute: kAXFocusedWindowAttribute) as! AXUIElement?,
              let webArea = findWebArea(root: window) else {
            return nil
        }

        let url = getAttribute(element: webArea, attribute: "AXURL") as? URL ?? URL(string: "about:blank")!
        let title = getAttribute(element: webArea, attribute: kAXTitleAttribute) as? String ?? "Safari"

        // Fast JS page context — single round-trip
        var jsContext = readPageContext()

        // Auto-dismiss paywall before walking the AX tree.
        // Paywall modals block the AX tree: body gets overflow:hidden and the
        // overlay covers all article elements. Removing the DOM nodes restores
        // full tree access without requiring the agent to tap an invisible X button.
        if jsContext?.paywallDetected == true {
            runPaywallDismissalJS()
            usleep(450_000) // 450ms for DOM mutation to settle
            jsContext = readPageContext() // re-read — paywall should be gone
        }

        // AX tree walk (for interactive element refs)
        var lines: [String] = []
        walk(element: webArea, depth: 0, lines: &lines)

        return AXSnapshot(
            tree: lines.joined(separator: "\n"),
            refMap: self.refMap,
            url: url.absoluteString,
            title: title,
            nodeCount: self.counter,
            jsContext: jsContext
        )
    }

    // MARK: - Paywall Dismissal JS

    /// Remove paywall/subscription overlays and restore page scrolling.
    /// Called automatically when readPageContext() detects a paywall.
    func runPaywallDismissalJS() {
        let js = "(function(){" +
            // Remove all known paywall/modal overlay selectors
            "var sel='[class*=paywall],[id*=paywall],[class*=piano-],[class*=tp-modal]," +
            "[class*=Paywall],[class*=SubscribeOverlay],[class*=RegwallModal]," +
            "[class*=gate-body],[class*=css-offers],[class*=SignupModal]," +
            "[class*=subscription-modal],[class*=meter-modal]';" +
            "document.querySelectorAll(sel).forEach(function(e){e.remove();});" +
            // Also remove generic dialogs containing subscription language
            "document.querySelectorAll('[role=dialog],[role=alertdialog]').forEach(function(e){" +
            "var t=e.textContent.toLowerCase();" +
            "if(t.indexOf('subscri')>=0||t.indexOf('sign in')>=0||t.indexOf('register')>=0||t.indexOf('continue reading')>=0){e.remove();}" +
            "});" +
            // Remove fixed-position backdrops/overlays (semi-transparent covers)
            "document.querySelectorAll('[class*=backdrop],[class*=Overlay],[class*=overlay]').forEach(function(e){" +
            "var s=window.getComputedStyle(e);" +
            "if(s.position==='fixed'&&parseFloat(s.zIndex)>100){e.remove();}" +
            "});" +
            // Restore scrolling — paywalls lock body scroll
            "document.body.style.overflow='';" +
            "document.body.style.position='';" +
            "document.documentElement.style.overflow='';" +
            // NYT-specific: remove overflow-hidden class on body
            "document.body.classList.remove('overflow-hidden','noscroll','modal-open');" +
            "})()"

        let escaped = js
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let source = "tell application \"Safari\" to do JavaScript \"\(escaped)\" in current tab of front window"
        if let script = NSAppleScript(source: source) {
            var err: NSDictionary?
            script.executeAndReturnError(&err)
        }
    }

    // MARK: - JS Page Context (one AppleScript call instead of 100+ AX API calls)

    private func readPageContext() -> JSPageContext? {
        // Single-line JS — no newlines, single-quoted strings to avoid AppleScript escaping hell
        let js = "(function(){" +
            "var r={paywallDetected:false,paywallType:'',articles:[],headings:[],alerts:[]};" +
            "try{" +
            // Paywall / subscription wall detection
            "var pw=document.querySelector('[class*=paywall],[id*=paywall],[class*=piano-],[class*=tp-modal],[class*=Paywall],[class*=SubscribeOverlay],[class*=gate-body],[class*=meter-content]');" +
            "if(pw&&window.getComputedStyle(pw).display!='none'&&window.getComputedStyle(pw).visibility!='hidden'){r.paywallDetected=true;r.paywallType='overlay';}" +
            // NYT-specific signals
            "if(!r.paywallDetected&&document.querySelector('[data-testid=inline-message],[class*=SignupModal],[class*=css-offers],[class*=RegwallModal]')){r.paywallDetected=true;r.paywallType='nyt-gate';}" +
            // Visible dialogs / alerts
            "document.querySelectorAll('[role=dialog],[role=alertdialog]').forEach(function(d){" +
            "if(window.getComputedStyle(d).display!='none'){var t=d.textContent.trim().slice(0,150);if(t.length>10)r.alerts.push(t);}" +
            "});" +
            // Cookie/consent banners
            "var ck=document.querySelector('[id*=cookie],[class*=cookie-banner],[id*=consent],[class*=gdpr],[id*=CookieBanner]');" +
            "if(ck&&window.getComputedStyle(ck).display!='none'){r.alerts.push('Cookie/consent banner present');}" +
            // Article headlines — broad selector set for major news sites
            "var seen={};" +
            "document.querySelectorAll('article h2,article h3,[class*=headline] a,[data-testid*=headline],[class*=Headline] a,h2 a,h3 a').forEach(function(el,i){" +
            "if(i<15){var t=el.textContent.trim().slice(0,100);if(t.length>10&&!seen[t]){seen[t]=1;r.articles.push(t);}}" +
            "});" +
            // Page H1s for orientation
            "document.querySelectorAll('h1').forEach(function(h){var t=h.textContent.trim().slice(0,100);if(t)r.headings.push(t);});" +
            "}catch(e){}" +
            "return JSON.stringify(r);" +
            "})()"

        // Embed JS into AppleScript — only need to escape backslash and double-quote
        let escaped = js
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")

        let source = "tell application \"Safari\" to return do JavaScript \"\(escaped)\" in current tab of front window"
        guard let script = NSAppleScript(source: source) else { return nil }

        var error: NSDictionary?
        let result = script.executeAndReturnError(&error)
        guard error == nil, let jsonStr = result.stringValue else { return nil }

        guard let data = jsonStr.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }

        return JSPageContext(
            paywallDetected: json["paywallDetected"] as? Bool ?? false,
            paywallType:     json["paywallType"]     as? String ?? "",
            articles:        json["articles"]        as? [String] ?? [],
            headings:        json["headings"]        as? [String] ?? [],
            alerts:          json["alerts"]          as? [String] ?? []
        )
    }

    // MARK: - AX Tree Walk

    private func findWebArea(root: AXUIElement) -> AXUIElement? {
        var children: CFTypeRef?
        AXUIElementCopyAttributeValue(root, kAXChildrenAttribute as CFString, &children)
        guard let arr = children as? [AXUIElement] else { return nil }
        for child in arr {
            if getAttribute(element: child, attribute: kAXRoleAttribute) as? String == "AXWebArea" {
                return child
            }
            if let found = findWebArea(root: child) { return found }
        }
        return nil
    }

    private func walk(element: AXUIElement, depth: Int, lines: inout [String]) {
        guard counter < maxNodes && depth <= maxDepth else { return }

        let role        = getAttribute(element: element, attribute: kAXRoleAttribute)    as? String ?? ""
        let title       = getAttribute(element: element, attribute: kAXTitleAttribute)   as? String ?? ""
        let description = getAttribute(element: element, attribute: kAXDescriptionAttribute) as? String ?? ""
        let isHidden    = (getAttribute(element: element, attribute: kAXHiddenAttribute) as? Bool) ?? false
        let isEnabled   = (getAttribute(element: element, attribute: kAXEnabledAttribute) as? Bool) ?? true

        if isHidden || !isEnabled { return }

        let label = (title.isEmpty ? description : title).trimmingCharacters(in: .whitespacesAndNewlines)
        let isInteractive = interactiveRoles.contains(role)
        let isStructural  = structuralRoles.contains(role)
        var shouldKeep = isInteractive || isStructural

        if role == "AXImage" && label.isEmpty { shouldKeep = false }
        if role == "AXStaticText"             { shouldKeep = false }

        if shouldKeep {
            counter += 1
            let ref = counter
            let frame = getFrame(element: element)
            refMap[ref] = AXRefEntry(element: element, role: role, label: label, frame: frame)

            let indent      = String(repeating: "  ", count: depth)
            let displayRole = role.replacingOccurrences(of: "AX", with: "").lowercased()
            var line = "\(indent)[\(ref)] \(displayRole)"
            if !label.isEmpty { line += " \"\(label)\"" }

            if let value = getAttribute(element: element, attribute: kAXValueAttribute) as? String,
               !value.isEmpty, value != label {
                line += " → \"\(value)\""
            }
            lines.append(line)
        }

        var children: CFTypeRef?
        AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &children)
        if let arr = children as? [AXUIElement] {
            for child in arr {
                walk(element: child, depth: shouldKeep ? depth + 1 : depth, lines: &lines)
            }
        }
    }

    // MARK: - Helpers

    private func getAttribute(element: AXUIElement, attribute: String) -> Any? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        return result == .success ? value : nil
    }

    private func getFrame(element: AXUIElement) -> CGRect {
        var posVal: CFTypeRef?
        var sizVal: CFTypeRef?
        AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &posVal)
        AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &sizVal)

        var pos  = CGPoint.zero
        var size = CGSize.zero
        if let p = posVal { AXValueGetValue(p as! AXValue, .point, &pos) }
        if let s = sizVal { AXValueGetValue(s as! AXValue, .size, &size) }
        return CGRect(origin: pos, size: size)
    }
}
