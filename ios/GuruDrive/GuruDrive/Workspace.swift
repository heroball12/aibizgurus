import SwiftUI
import WebKit
import Network
import AVFAudio

@MainActor
final class Workspace: NSObject, ObservableObject, WKNavigationDelegate, WKUIDelegate {
    @Published var loading = true
    @Published var connected = true
    @Published var ready = false
    @Published var busy = false
    @Published var screen = "signin"
    @Published var status = "Sign in to begin"
    @Published var failure: String?
    @Published var externalPage: ExternalPage?
    let policy = AppPolicy.configured
    let webView: WKWebView
    private let network = NWPathMonitor()
    private var crmURL: URL?
    private var pendingCommand: String?
    private var backgrounded = false
    private var requestingMicrophonePermission = false

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.applicationNameForUserAgent = "GuruDrive/1.0"
        webView = WKWebView(frame: .zero, configuration: configuration)
        super.init()
        configuration.userContentController.add(Bridge(owner: self), name: "guru")
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 0.047, green: 0.047, blue: 0.071, alpha: 1)
        webView.scrollView.backgroundColor = webView.backgroundColor
        webView.allowsBackForwardNavigationGestures = false
        webView.scrollView.keyboardDismissMode = .interactive
        #if DEBUG
        webView.isInspectable = true
        #endif
        network.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.connected = path.status == .satisfied
                if path.status != .satisfied { self?.command("pause") }
            }
        }
        network.start(queue: DispatchQueue(label: "guru.network"))
        webView.load(URLRequest(url: policy.home))
    }

    func command(_ name: String) {
        guard ["pause", "resume", "status", "crm", "inventory", "reset", "controls", "signout"].contains(name),
              let url = webView.url, policy.privatePage(url) else { return }
        webView.evaluateJavaScript("window.guruAppCommand?.('\(name)')", completionHandler: nil)
    }

    func customer(command next: String? = nil) {
        if screen == "customer" { if let next { command(next) }; return }
        pendingCommand = next
        navigate(policy.home)
    }

    func dealership() {
        guard !busy else { return }
        if screen == "customer" { command("crm") }
        else if let crmURL { navigate(crmURL) }
    }

    func navigate(_ url: URL) {
        command("pause")
        webView.load(URLRequest(url: url))
    }

    func retry() {
        failure = nil
        // Do not reload a submitted POST or silently reset a prospect.
        let url = webView.url.flatMap { policy.embedded($0) ? $0 : nil } ?? policy.home
        navigate(url)
    }

    func signout() {
        pendingCommand = nil
        crmURL = nil
        command("signout")
    }

    func activity(_ active: Bool) {
        backgrounded = !active
        if !active { command("pause") }
        webView.setAllMediaPlaybackSuspended(!active, completionHandler: nil)
        if !active { webView.setMicrophoneCaptureState(.none, completionHandler: nil) }
        else { command("resume") }
        UIApplication.shared.isIdleTimerDisabled = active && ready
    }

    func sceneChanged(_ phase: ScenePhase) {
        // The system permission sheet briefly deactivates the app. Do not cancel
        // the very first Speak tap while the user is answering that sheet.
        if phase == .inactive && requestingMicrophonePermission { return }
        activity(phase == .active)
    }

    func receive(_ message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame,
              let frameURL = message.frameInfo.request.url, policy.privatePage(frameURL),
              let pageURL = webView.url, policy.privatePage(pageURL),
              let data = message.body as? [String: Any],
              let page = data["screen"] as? String, ["customer", "crm", "guide"].contains(page) else { return }
        screen = page
        ready = data["ready"] as? Bool ?? false
        busy = data["busy"] as? Bool ?? false
        let state = data["state"] as? String ?? "READY"
        status = ["LISTENING": "Listening", "SPEAKING": "Axel is speaking", "THINKING": "Axel is working", "READY": "Ready"][state] ?? "Ready"
        if let raw = data["crmURL"] as? String, let url = URL(string: raw), policy.crmPage(url) { crmURL = url }
        UIApplication.shared.isIdleTimerDisabled = ready && !backgrounded
        if ready && !busy && page == "customer", let next = pendingCommand {
            pendingCommand = nil
            command(next)
        }
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        loading = true; ready = false; busy = false; failure = nil
        UIApplication.shared.isIdleTimerDisabled = false
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loading = false
        if let url = webView.url, policy.loginPage(url) { screen = "signin"; status = "Employee sign-in"; crmURL = nil }
        command("status")
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { failed(error) }
    private func failed(_ error: Error) {
        guard (error as NSError).code != NSURLErrorCancelled else { return }
        loading = false; ready = false
        failure = "The dealership couldn't load. Check your connection, then try again. Your saved demo stays on the server."
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        loading = false; ready = false
        failure = "The presentation paused. Tap Try again to reconnect to your saved prospect."
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame, let http = response.response as? HTTPURLResponse, http.statusCode >= 500 || http.statusCode == 404 {
            loading = false; ready = false
            failure = http.statusCode == 404 ? "This workspace isn't available. Make sure the iPad update is deployed, then open the customer experience again." : "The server is temporarily unavailable. Please try again."
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if action.targetFrame?.isMainFrame == false { decisionHandler(.cancel); return }
        if policy.embedded(url) {
            if action.targetFrame == nil { webView.load(action.request); decisionHandler(.cancel) }
            else { decisionHandler(.allow) }
        } else {
            decisionHandler(.cancel)
            // Only deliberate link taps open a separate browser. Redirects cannot escape.
            if action.navigationType == .linkActivated && url.scheme == "https" {
                command("pause"); externalPage = ExternalPage(url: url)
            }
        }
    }

    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        guard type == .microphone, frame.isMainFrame, !backgrounded,
              let url = frame.request.url, policy.privatePage(url),
              origin.host == policy.origin.host, origin.protocol == policy.origin.scheme,
              let current = webView.url, policy.privatePage(current) else { decisionHandler(.deny); return }
        // The system prompt is explicit; no mic capture starts on launch or app resume.
        requestingMicrophonePermission = true
        AVAudioApplication.requestRecordPermission { [weak self] allowed in
            Task { @MainActor in
                guard let self else { decisionHandler(.deny); return }
                self.requestingMicrophonePermission = false
                decisionHandler(allowed && !self.backgrounded ? .grant : .deny)
            }
        }
    }
}

@MainActor
private final class Bridge: NSObject, WKScriptMessageHandler {
    weak var owner: Workspace?
    init(owner: Workspace) { self.owner = owner }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) { owner?.receive(message) }
}

struct ExternalPage: Identifiable { let id = UUID(); let url: URL }

struct DealershipWebView: UIViewRepresentable {
    let workspace: Workspace
    func makeUIView(context: Context) -> WKWebView { workspace.webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
