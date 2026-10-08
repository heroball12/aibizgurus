import SwiftUI
import SafariServices

@main
struct GuruDriveApp: App {
    var body: some Scene { WindowGroup { PresentationView().preferredColorScheme(.dark) } }
}

struct PresentationView: View {
    @StateObject private var workspace = Workspace()
    @Environment(\.scenePhase) private var scenePhase
    @State private var showGuide = false
    @State private var confirmSignout = false
    private let purple = Color(red: 0.72, green: 0.58, blue: 0.96)
    private let gold = Color(red: 0.91, green: 0.77, blue: 0.49)

    var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 24) { brand; Spacer(); tabs; Spacer(); actions }
                VStack(spacing: 12) { HStack { brand; Spacer(); actions }; tabs }
            }
            .padding(.horizontal, 24).padding(.vertical, 14)
            .background(Color(red: 0.08, green: 0.065, blue: 0.12))
            if !workspace.connected {
                Label("You're offline. Reconnect to talk with Axel. Your saved prospect will stay here.", systemImage: "wifi.slash")
                    .font(.subheadline).padding(12).frame(maxWidth: .infinity).background(gold.opacity(0.15))
            }
            ZStack(alignment: .top) {
                DealershipWebView(workspace: workspace)
                if workspace.loading { ProgressView().progressViewStyle(.linear).tint(purple) }
                if let failure = workspace.failure {
                    VStack(spacing: 20) {
                        Image(systemName: "antenna.radiowaves.left.and.right.slash").font(.system(size: 40)).foregroundStyle(purple)
                        Text("Let's reconnect.").font(.largeTitle.bold())
                        Text(failure).multilineTextAlignment(.center).frame(maxWidth: 470)
                        Button("Try again") { workspace.retry() }.buttonStyle(.borderedProminent).tint(purple)
                        Button("Customer experience") { workspace.navigate(workspace.policy.home) }
                    }.padding(40).frame(maxWidth: .infinity, maxHeight: .infinity).background(Color(red: 0.047, green: 0.047, blue: 0.071))
                }
            }
        }
        .tint(purple)
        .sheet(isPresented: $showGuide, onDismiss: { workspace.command("resume") }) { guide }
        .sheet(item: $workspace.externalPage, onDismiss: { workspace.command("resume") }) { page in BrowserSheet(url: page.url) }
        .confirmationDialog("Sign out of Guru Drive?", isPresented: $confirmSignout, titleVisibility: .visible) {
            Button("Sign out", role: .destructive) { workspace.signout() }
        }
        .onChange(of: scenePhase) { _, phase in workspace.sceneChanged(phase) }
    }

    private var brand: some View {
        HStack(spacing: 12) {
            Image(systemName: "sparkles.rectangle.stack.fill").font(.title2).foregroundStyle(purple)
            VStack(alignment: .leading, spacing: 3) {
                Text("GURU DRIVE").font(.headline).tracking(3)
                Text("VELOCITY MOTORS · PRIVATE DEMO").font(.system(size: 9, weight: .semibold)).tracking(1.4).foregroundStyle(.secondary)
            }
        }.fixedSize()
    }

    private var tabs: some View {
        HStack(spacing: 8) {
            tab("Talk to Axel", icon: "waveform", selected: workspace.screen == "customer") { workspace.customer() }
            tab("Dealership CRM", icon: "rectangle.split.2x2", selected: workspace.screen == "crm") { workspace.dealership() }
        }.disabled(!workspace.ready || workspace.busy || !workspace.connected)
    }

    private func tab(_ title: String, icon: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) { Label(title, systemImage: icon).font(.subheadline.weight(.semibold)).padding(.horizontal, 16).frame(minHeight: 44).background(selected ? purple.opacity(0.22) : Color.clear, in: RoundedRectangle(cornerRadius: 12)) }
            .buttonStyle(.plain).foregroundStyle(selected ? purple : .secondary)
    }

    private var actions: some View {
        HStack(spacing: 16) {
            HStack(spacing: 6) { Circle().fill(workspace.connected ? purple : gold).frame(width: 6, height: 6); Text(workspace.connected ? workspace.status : "Offline").font(.caption) }.foregroundStyle(.secondary)
            Menu {
                Button("New prospect", systemImage: "person.badge.plus") { workspace.customer(command: "reset") }.disabled(!workspace.ready || workspace.busy)
                Button("Inventory", systemImage: "car.side") { workspace.customer(command: "inventory") }.disabled(!workspace.ready || workspace.busy)
                Button("Demo scenarios", systemImage: "slider.horizontal.3") { workspace.customer(command: "controls") }.disabled(!workspace.ready || workspace.busy)
                Button("Presenter guide", systemImage: "book") { workspace.command("pause"); showGuide = true }
                Divider()
                Button("Reload workspace", systemImage: "arrow.clockwise") { workspace.retry() }.disabled(workspace.busy)
                Button("Sign out", systemImage: "rectangle.portrait.and.arrow.right", role: .destructive) { confirmSignout = true }.disabled(!workspace.ready || workspace.busy)
            } label: { Image(systemName: "ellipsis.circle").font(.title2).frame(width: 44, height: 44).accessibilityLabel("Presentation options") }
        }.fixedSize()
    }

    private var guide: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    Text("One conversation.\nThe whole journey.").font(.largeTitle.bold())
                    guideStep("01", "Meet Axel", "Tap Speak, allow the microphone, and describe a fictional customer's vehicle needs. Type is always available. Let Axel finish before replying, or tap Interrupt & speak.")
                    guideStep("02", "Build the customer story", "Give a sample name, phone and email. Compare vehicles, discuss a trade, choose a demo appointment, and try the fictional financing application.")
                    guideStep("03", "Show the other side", "Tap Dealership CRM, then Enter demo workspace. See the captured contact, vehicle, appointment and financing details. Return to Axel to continue the same prospect.")
                    guideStep("04", "Start fresh", "Use New prospect between presentations. It asks before clearing this demo's customer and conversation.")
                    Text("Live conversation requires internet and the site's connected AI service. These are fictional dealership records, not real bookings or credit applications.").font(.footnote).foregroundStyle(.secondary)
                    Text("Employee sign-in protects the app. The public website remains available separately. Use your website account; no provider API keys belong on the iPad.").font(.footnote).foregroundStyle(.secondary)
                }.padding(32)
            }.navigationTitle("Presenter guide").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showGuide = false } } }
        }.presentationDetents([.large])
    }

    private func guideStep(_ number: String, _ title: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 18) { Text(number).font(.title2.monospaced()).foregroundStyle(purple); VStack(alignment: .leading, spacing: 7) { Text(title).font(.title3.bold()); Text(text).foregroundStyle(.secondary) } }
    }
}

struct BrowserSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> SFSafariViewController { SFSafariViewController(url: url) }
    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
