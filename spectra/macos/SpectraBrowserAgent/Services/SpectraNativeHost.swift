import Foundation
import AppKit

class SpectraNativeHost: NSObject {
    private let url = URL(string: "ws://localhost:8765/ws")!
    private var webSocketTask: URLSessionWebSocketTask?
    private let urlSession = URLSession(configuration: .default)

    private let treeReader = AXTreeReader()
    private let executor   = AXExecutor()
    private var currentSnapshot: AXSnapshot?

    private var reconnectDelay: TimeInterval = 1
    private let maxReconnectDelay: TimeInterval = 4
    private var retryCount = 0

    // How long to wait for the page to settle after each action type
    private let actionSettleTime: [String: TimeInterval] = [
        "navigate":   2.5,   // full page load
        "go_back":    1.5,   // back navigation
        "tap":        0.5,   // link/button click — may trigger navigation
        "type_text":  0.3,
        "scroll":     0.2,
    ]

    func start() {
        connect()
    }

    private func connect() {
        webSocketTask = urlSession.webSocketTask(with: url)
        webSocketTask?.resume()
        receiveMessage()
        retryCount = 0
        reconnectDelay = 1
    }

    private func reconnect() {
        guard retryCount < 3 else {
            showNotification(title: "Spectra Agent Error", message: "Spectra backend not reachable")
            return
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + reconnectDelay) { [weak self] in
            guard let self = self else { return }
            self.retryCount += 1
            self.reconnectDelay = min(self.reconnectDelay * 2, self.maxReconnectDelay)
            self.connect()
        }
    }

    // MARK: - Task Dispatch

    func dispatchTask(userQuery: String) {
        guard let safariApp = NSWorkspace.shared.runningApplications.first(where: {
            $0.bundleIdentifier == "com.apple.Safari"
        }) else {
            showNotification(title: "Safari Not Found", message: "Please open Safari before starting a task.")
            return
        }

        guard let snapshot = treeReader.snapshot(safariPID: safariApp.processIdentifier) else {
            showNotification(title: "Error", message: "Failed to read Safari accessibility tree.")
            return
        }

        self.currentSnapshot = snapshot

        var screenDict = buildScreenDict(from: snapshot)
        let command: [String: Any] = [
            "type":   "command",
            "task":   userQuery,
            "source": "safari_ax_agent",
            "screen": screenDict,
        ]
        sendMessage(command)
    }

    // MARK: - Screen Dict Builder

    private func buildScreenDict(from snapshot: AXSnapshot) -> [String: Any] {
        var d: [String: Any] = [
            "mode":       "ax_tree",
            "app":        "Safari",
            "url":        snapshot.url,
            "page_title": snapshot.title,
            "tree":       snapshot.tree,
            "node_count": snapshot.nodeCount,
        ]
        if let ctx = snapshot.jsContext {
            d["paywall_detected"] = ctx.paywallDetected
            d["paywall_type"]     = ctx.paywallType
            if !ctx.articles.isEmpty { d["page_articles"] = ctx.articles }
            if !ctx.alerts.isEmpty   { d["page_alerts"]   = ctx.alerts   }
            if !ctx.headings.isEmpty { d["page_headings"] = ctx.headings }
        }
        return d
    }

    // MARK: - WebSocket Communication

    private func sendMessage(_ dict: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: dict),
              let jsonString = String(data: data, encoding: .utf8) else { return }
        let message = URLSessionWebSocketTask.Message.string(jsonString)
        webSocketTask?.send(message) { error in
            if let error = error { print("WebSocket send error: \(error)") }
        }
    }

    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):            self.handleIncomingMessage(text)
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8) { self.handleIncomingMessage(text) }
                @unknown default: break
                }
                self.receiveMessage()
            case .failure(let error):
                print("WebSocket receive failure: \(error)")
                self.reconnect()
            }
        }
    }

    private func handleIncomingMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else { return }

        if type == "ax_action" {
            let action = json["action"] as? String ?? ""
            let ref    = json["ref"]    as? Int
            let params = json["params"] as? [String: Any] ?? [:]

            guard let snapshot = currentSnapshot else { return }

            let result = executor.execute(action: action, ref: ref, params: params, refMap: snapshot.refMap)
            print("Action [\(action)] → \(result)")

            // Adaptive settle time based on action type
            let settle = actionSettleTime[action] ?? 0.5
            DispatchQueue.global().asyncAfter(deadline: .now() + settle) { [weak self] in
                self?.sendScreenUpdate()
            }
        }
    }

    private func sendScreenUpdate() {
        guard let safariApp = NSWorkspace.shared.runningApplications.first(where: {
            $0.bundleIdentifier == "com.apple.Safari"
        }) else { return }

        guard let newSnapshot = treeReader.snapshot(safariPID: safariApp.processIdentifier) else { return }
        self.currentSnapshot = newSnapshot

        let update: [String: Any] = [
            "type":   "screen_update",
            "screen": buildScreenDict(from: newSnapshot),
        ]
        sendMessage(update)
    }

    // MARK: - Notifications

    private func showNotification(title: String, message: String) {
        let notification = NSUserNotification()
        notification.title = title
        notification.informativeText = message
        NSUserNotificationCenter.default.deliver(notification)
    }
}
