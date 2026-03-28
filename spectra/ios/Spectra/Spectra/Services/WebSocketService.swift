import Foundation
import Combine

final class WebSocketService: ObservableObject {
    @Published var isConnected = false
    @Published var latestStatus: TaskStatus?
    @Published var confirmationRequest: ConfirmationRequest?
    @Published var handoffRequest: HandoffRequest?
    @Published var planPreview: PlanPreviewData?
    @Published var memoryItems: [MemoryItem] = []
    @Published var taskResult: TaskResult?
    @Published var statusHistory: [TaskStatus] = []
    @Published var askUserRequest: AskUserRequest?
    @Published var isVoiceListening = false
    @Published var voiceTranscript: String?
    @Published var voiceError: String?
    @Published var errorMessage: String?

    private var webSocketTask: URLSessionWebSocketTask?
    private let url = URL(string: "ws://localhost:8765/ws")!
    private let session: URLSession = URLSession(configuration: .default)
    private var connectionID = 0  // guards stale callbacks
    private var isConnecting = false

    func connect() {
        guard !isConnecting else { return }
        isConnecting = true

        // Tear down any existing connection
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        connectionID += 1
        let myID = connectionID

        let task = session.webSocketTask(with: url)
        webSocketTask = task
        task.resume()

        // Don't set isConnected until we get the first successful receive or ping-pong
        listenForMessages(id: myID)

        // Verify connection is alive after 2 seconds via ping
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) { [weak self] in
            self?.verifyAndStartPinging(id: myID)
        }

        isConnecting = false
    }

    private func verifyAndStartPinging(id: Int) {
        guard connectionID == id, let task = webSocketTask else { return }
        task.sendPing { [weak self] error in
            guard let self = self, self.connectionID == id else { return }
            if error != nil {
                // Connection failed — retry
                DispatchQueue.main.async {
                    self.isConnected = false
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                        guard self.connectionID == id else { return }
                        self.connect()
                    }
                }
            } else {
                // Connection is alive
                DispatchQueue.main.async {
                    self.isConnected = true
                }
                self.schedulePing(id: id)
            }
        }
    }

    private func schedulePing(id: Int) {
        DispatchQueue.global().asyncAfter(deadline: .now() + 15) { [weak self] in
            guard let self = self, self.connectionID == id, let task = self.webSocketTask else { return }
            task.sendPing { [weak self] error in
                guard let self = self, self.connectionID == id else { return }
                if error != nil {
                    DispatchQueue.main.async {
                        self.isConnected = false
                        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                            guard self.connectionID == id else { return }
                            self.connect()
                        }
                    }
                } else {
                    self.schedulePing(id: id)
                }
            }
        }
    }

    func disconnect() {
        connectionID += 1
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        DispatchQueue.main.async { self.isConnected = false }
    }

    // MARK: - Outgoing Messages

    func sendCommand(_ task: String) {
        resetTaskState()
        send(["type": "command", "task": task])
    }

    func sendConfirmation(_ approved: Bool) {
        send(["type": "confirm", "approved": approved])
    }

    func sendPlanApproval(_ approved: Bool, modifiedSteps: [String]? = nil) {
        var msg: [String: Any] = ["type": "plan_approve", "approved": approved]
        if let steps = modifiedSteps { msg["modified_steps"] = steps }
        send(msg)
    }

    func sendStop() {
        send(["type": "stop"])
    }

    func sendVoiceStart() {
        voiceTranscript = nil
        voiceError = nil
        isVoiceListening = true
        send(["type": "voice_start"])
    }

    func sendVoiceStop() {
        isVoiceListening = false
        send(["type": "voice_stop"])
    }

    func sendTakeoverDone() {
        send(["type": "takeover_done"])
    }

    func sendUserAnswer(_ answer: String) {
        send(["type": "user_answer", "answer": answer])
        DispatchQueue.main.async { self.askUserRequest = nil }
    }

    // MARK: - Internal

    private func resetTaskState() {
        DispatchQueue.main.async {
            self.latestStatus = nil
            self.statusHistory = []
            self.memoryItems = []
            self.taskResult = nil
            self.planPreview = nil
            self.confirmationRequest = nil
            self.handoffRequest = nil
            self.askUserRequest = nil
            self.errorMessage = nil
        }
    }

    private func send(_ message: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: message),
              let string = String(data: data, encoding: .utf8) else { return }
        guard let task = webSocketTask else {
            DispatchQueue.main.async {
                self.errorMessage = "Not connected to server"
            }
            return
        }
        task.send(.string(string)) { [weak self] error in
            if let error = error {
                DispatchQueue.main.async {
                    self?.errorMessage = error.localizedDescription
                }
            }
        }
    }

    private func listenForMessages(id: Int) {
        webSocketTask?.receive { [weak self] result in
            guard let self = self, self.connectionID == id else { return }
            switch result {
            case .success(let message):
                // First successful receive confirms the connection is alive
                DispatchQueue.main.async {
                    if !self.isConnected { self.isConnected = true }
                }
                switch message {
                case .string(let text):
                    self.handleRawMessage(text)
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8) {
                        self.handleRawMessage(text)
                    }
                @unknown default:
                    break
                }
                self.listenForMessages(id: id)
            case .failure:
                DispatchQueue.main.async {
                    guard self.connectionID == id else { return }
                    self.isConnected = false
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                        guard self.connectionID == id else { return }
                        self.connect()
                    }
                }
            }
        }
    }

    private func handleRawMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else { return }

        DispatchQueue.main.async { [self] in
            self.handleMessage(type: type, json: json)
        }
    }

    private func handleMessage(type: String, json: [String: Any]) {
        switch type {
        case "status":
            if let data = try? JSONSerialization.data(withJSONObject: json),
               let status = try? JSONDecoder().decode(TaskStatus.self, from: data) {
                latestStatus = status
                statusHistory.append(status)
                // Don't post progress notifications — they cover the screen and interfere with WDA
                // NotificationService.shared.postProgress(step: status.step, total: status.total, detail: status.detail)
            }

        case "memory_update":
            if let key = json["key"] as? String, let value = json["value"] as? String {
                let item = MemoryItem(key: key, value: value)
                if let idx = memoryItems.firstIndex(where: { $0.key == key }) {
                    memoryItems[idx] = item
                } else {
                    memoryItems.append(item)
                }
            }

        case "plan_preview":
            if let data = try? JSONSerialization.data(withJSONObject: json),
               let plan = try? JSONDecoder().decode(PlanPreviewData.self, from: data) {
                planPreview = plan
            }

        case "confirm_request":
            if let data = try? JSONSerialization.data(withJSONObject: json),
               let request = try? JSONDecoder().decode(ConfirmationRequest.self, from: data) {
                confirmationRequest = request
                NotificationService.shared.postConfirmation(action: request.action, detail: request.detail)
            }

        case "handoff_request":
            if let reason = json["reason"] as? String {
                handoffRequest = HandoffRequest(reason: reason)
                NotificationService.shared.postConfirmation(action: "Handoff", detail: reason)
            }

        case "ask_user":
            if let data = try? JSONSerialization.data(withJSONObject: json),
               let request = try? JSONDecoder().decode(AskUserRequest.self, from: data) {
                askUserRequest = request
                NotificationService.shared.postConfirmation(action: "Question", detail: request.question)
            }

        case "done":
            if let data = try? JSONSerialization.data(withJSONObject: json),
               let result = try? JSONDecoder().decode(TaskResult.self, from: data) {
                taskResult = result
                NotificationService.shared.postCompletion(summary: result.summary, steps: result.steps, duration: result.duration)
            }

        case "stuck":
            let reason = json["reason"] as? String ?? "Unknown"
            taskResult = TaskResult(success: false, summary: reason, steps: statusHistory.count, duration: 0)

        case "voice_listening":
            isVoiceListening = true

        case "voice_result":
            isVoiceListening = false
            voiceTranscript = json["transcript"] as? String

        case "voice_error":
            isVoiceListening = false
            voiceError = json["error"] as? String

        case "voice_cancelled":
            isVoiceListening = false

        case "error":
            errorMessage = json["message"] as? String

        default:
            break
        }
    }
}
