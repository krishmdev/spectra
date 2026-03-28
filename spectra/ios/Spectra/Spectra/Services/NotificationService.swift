import Foundation
import UserNotifications

final class NotificationService {
    static let shared = NotificationService()

    private init() {}

    func requestPermission() {
        // Define actionable buttons for confirmation notifications
        let approveAction = UNNotificationAction(
            identifier: "APPROVE_ACTION",
            title: "Approve",
            options: [.foreground]
        )
        let denyAction = UNNotificationAction(
            identifier: "DENY_ACTION",
            title: "Deny",
            options: [.destructive]
        )
        let confirmCategory = UNNotificationCategory(
            identifier: "CONFIRMATION",
            actions: [approveAction, denyAction],
            intentIdentifiers: [],
            options: []
        )

        let center = UNUserNotificationCenter.current()
        center.setNotificationCategories([confirmCategory])
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    /// Live-updating progress — reuses the same ID so each step replaces the last.
    func postProgress(step: Int, total: Int, detail: String) {
        let content = UNMutableNotificationContent()
        content.title = "Spectra — Step \(step)/\(total)"
        content.body = detail
        content.sound = nil  // Silent
        // Same identifier → updates in place
        let request = UNNotificationRequest(identifier: "spectra-progress", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    func postConfirmation(action: String, detail: String) {
        let content = UNMutableNotificationContent()
        content.title = "Spectra — Approval Needed"
        content.body = "\(action): \(detail)"
        content.sound = .default
        content.categoryIdentifier = "CONFIRMATION"
        let request = UNNotificationRequest(identifier: "spectra-confirm", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    func postCompletion(summary: String, steps: Int, duration: Double) {
        // Clear the progress notification first
        UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: ["spectra-progress"])

        let content = UNMutableNotificationContent()
        content.title = "Spectra — Done!"
        content.body = summary
        content.subtitle = "\(steps) steps \u{00B7} \(String(format: "%.1f", duration))s"
        content.sound = .default
        let request = UNNotificationRequest(identifier: "spectra-done", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
