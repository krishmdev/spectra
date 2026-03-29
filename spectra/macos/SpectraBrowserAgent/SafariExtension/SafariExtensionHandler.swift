import SafariServices
import os.log

class SafariExtensionHandler: SFSafariExtensionHandler {
    
    override func messageReceived(withName messageName: String, from page: SFSafariPage, userInfo: [String : Any]?) {
        // Handle messages from the extension popup
        guard let userInfo = userInfo, let task = userInfo["task"] as? String else { return }
        
        os_log(.debug, log: .default, "Received task from extension popup: %{public}@", task)
        
        // Dispatch to the native host
        // In a real app, this would use a Shared Instance or XPC
        // For this implementation, we assume a globally accessible instance
        DispatchQueue.main.async {
            // SpectraNativeHost.shared.dispatchTask(userQuery: task)
            print("Native host received task: \(task)")
        }
    }
}
