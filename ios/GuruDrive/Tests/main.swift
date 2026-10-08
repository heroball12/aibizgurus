import Foundation

let p = AppPolicy(origin: URL(string: "https://aibiz.guru")!)
func check(_ condition: Bool, _ message: String) {
    if !condition { fatalError(message) }
}
check(p.home.absoluteString == "https://aibiz.guru/demo/automotive/ipad/", "Private launch URL")
for raw in ["https://aibiz.guru/demo/automotive/ipad/", "https://aibiz.guru/accounts/login/?next=/demo/automotive/ipad/"] {
    check(p.embedded(URL(string: raw)!), "Allowed page: \(raw)")
}
for raw in ["http://aibiz.guru/demo/automotive/ipad/", "https://aibiz.guru.evil.test/demo/automotive/ipad/", "https://evil.test/demo/automotive/ipad/", "https://aibiz.guru:8443/demo/automotive/ipad/", "https://user@aibiz.guru/demo/automotive/ipad/", "https://aibiz.guru/demo/automotive/", "https://aibiz.guru/crm/", "https://aibiz.guru/demo/automotive/ipad/../manage/", "https://aibiz.guru/demo/automotive/ipad/%2e%2e/manage/", "file:///demo/automotive/ipad/"] {
    check(!p.embedded(URL(string: raw)!), "Blocked escape: \(raw)")
}
check(!p.privatePage(URL(string: "https://aibiz.guru/accounts/login/")!), "Login cannot use native bridge/mic")
check(p.embedded(URL(string: "https://aibiz.guru/demo/automotive/ipad/login/")!), "Private sign-in loads in app")
check(!p.privatePage(URL(string: "https://aibiz.guru/demo/automotive/ipad/login/")!), "Private sign-in cannot use native bridge/mic")
check(p.crmPage(URL(string: "https://aibiz.guru/demo/automotive/ipad/crm/?session=12345678-1234-1234-1234-123456789012")!), "Valid CRM session")
check(!p.crmPage(URL(string: "https://aibiz.guru/demo/automotive/ipad/crm/?session=bad")!), "Reject invalid session")
print("Passed native navigation, origin, private workspace, and CRM session checks.")
