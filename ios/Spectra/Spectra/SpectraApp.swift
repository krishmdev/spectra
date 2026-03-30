import SwiftUI
import UserNotifications

class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    /// Shared reference so notification actions can reach the WebSocketService.
    weak var ws: WebSocketService?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        NotificationService.shared.requestPermission()
        return true
    }

    /// Show notification banners even when the app is in the foreground.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }

    /// Handle actionable notification button taps (Approve / Deny).
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        switch response.actionIdentifier {
        case "APPROVE_ACTION":
            ws?.sendConfirmation(true)
        case "DENY_ACTION":
            ws?.sendConfirmation(false)
        default:
            break
        }
        completionHandler()
    }
}

@main
struct SpectraApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var ws = WebSocketService()

    var body: some Scene {
        WindowGroup {
            HomeView()
                .environmentObject(ws)
                .onAppear {
                    appDelegate.ws = ws
                    ws.connect()
                }
        }
    }
}
