import Foundation

/// One trusted server, one private workspace. Redirects never gain bridge/mic access.
struct AppPolicy {
    let origin: URL
    static let workspacePath = "/demo/automotive/ipad/"
    var home: URL { origin.appendingPathComponent(Self.workspacePath) }
    private func path(_ url: URL) -> String { url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) }

    func loginPage(_ url: URL) -> Bool { sameOrigin(url) && ["accounts/login", "demo/automotive/ipad/login"].contains(path(url)) }

    func sameOrigin(_ url: URL) -> Bool {
        url.scheme == origin.scheme && url.host == origin.host &&
        (url.port ?? (url.scheme == "https" ? 443 : 80)) == (origin.port ?? (origin.scheme == "https" ? 443 : 80)) &&
        url.user == nil && url.password == nil
    }

    func privatePage(_ url: URL) -> Bool {
        sameOrigin(url) && !loginPage(url) && (path(url.standardized) == "demo/automotive/ipad" || path(url.standardized).hasPrefix("demo/automotive/ipad/")) &&
        !url.path.contains("..") && !url.path.contains("\\")
    }

    func embedded(_ url: URL) -> Bool {
        privatePage(url) || loginPage(url)
    }

    func crmPage(_ url: URL) -> Bool {
        privatePage(url) && path(url) == "demo/automotive/ipad/crm" &&
        URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.contains(where: {
            $0.name == "session" && UUID(uuidString: $0.value ?? "") != nil
        }) == true
    }

    static var configured: AppPolicy {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        if let index = arguments.firstIndex(of: "-DemoBaseURL"), arguments.count > index + 1,
           let url = URL(string: arguments[index + 1]),
           ["127.0.0.1", "localhost"].contains(url.host), ["http", "https"].contains(url.scheme) {
            return AppPolicy(origin: url)
        }
        #endif
        return AppPolicy(origin: URL(string: "https://aibiz.guru")!)
    }
}
