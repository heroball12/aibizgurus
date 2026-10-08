# Guru Drive — private iPad dealership app

Native SwiftUI iPad app with an authenticated WKWebView workspace, built for the
13-inch iPad in landscape and portrait. Uses the existing Velocity Motors engine,
Axel speech pipeline, inventory, appointments, financing application and fictional
CRM. The public website and its routes remain available independently.

## Open and build

Open `GuruDrive.xcodeproj` in Xcode. Select the **GuruDrive** scheme and an iPad.
The minimum deployment target is iPadOS 17. No third-party native dependencies.

```sh
xcodebuild -project ios/GuruDrive/GuruDrive.xcodeproj -scheme GuruDrive \
  -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath .local-artifacts/guru-drive-build CODE_SIGNING_ALLOWED=NO build
```

Release builds always use `https://aibiz.guru/demo/automotive/ipad/`. There is no
editable server address or provider credential in the app. Debug builds accept
Xcode launch arguments `-DemoBaseURL http://127.0.0.1:8002` for an isolated local
simulator server. Only localhost/127.0.0.1 overrides are accepted; Release ignores
the arguments. Keep local testing separate from production credentials/data.

## Deploy the server first

1. Commit/push the accompanying Django, template and static-file changes through
   the existing Render deployment workflow. No new database migration is needed.
2. Check that the dealership dataset is initialized. On a deployment that has
   never had it, run `python manage.py seed_demo_center --publish` in Render Shell.
   This creates synthetic inventory and publishes the web demo. It is idempotent
   and preserves custom manager revisions. Do not replace existing custom content.
3. Confirm `/demo/automotive/` loads, then sign in at
   `/demo/automotive/ipad/` with an active employee/owner account. A client account
   or a rep disabled through DemoRepAccess cannot enter.
4. Use the site's existing server-side AI configuration. The account must have
   access to `DEMO_CHAT_MODEL` (or its configured default), `gpt-4o-mini-transcribe`
   and `gpt-4o-mini-tts`. No API key goes in Xcode, the app bundle or TestFlight.
   The development preview can browse inventory without an AI key, but cannot
   conduct a live AI conversation. Test a spoken exchange on the deployed server.

At implementation time (2026-10-03), the deployed `/demo/automotive/` URL returned
404. The new private endpoints are local changes and need deployment before the
Release app can connect. Successful compilation does not verify live AI access.

## Private TestFlight installation

1. Sign in at [Apple Developer Account](https://developer.apple.com/account/) and
   check the membership status. A paid Apple Developer Program membership is
   needed for TestFlight distribution. A free Personal Team is not sufficient.
2. In Xcode → Settings → Accounts, add that Apple account. In the GuruDrive target
   → Signing & Capabilities, select the paid team and leave automatic signing on.
   The proposed bundle ID is `guru.aibiz.GuruDrive`; change it if your team needs
   another identifier. No team ID or signing credentials are committed here.
3. Create the iOS app record **Guru Drive** in App Store Connect with the same
   bundle ID. Set the required beta contact/test information and privacy answers
   to match the actual server and AI processing. Do not submit a public release.
4. Select **Any iOS Device (arm64)** → Product → Archive → Distribute App →
   App Store Connect / TestFlight. Use internal-only distribution if the intended
   testers are authorized App Store Connect team members. Otherwise use a private
   external tester group (Apple's beta review applies). Do not enable a public link.
5. After processing, add the build to the chosen group. Install Apple's TestFlight
   on the iPad, accept the invitation and install Guru Drive. Sign in with the
   employee's existing website account, then tap **Speak** to allow the microphone.

TestFlight builds expire after 90 days; upload an updated build to keep testing.
For a permanent private release later, evaluate Apple's Custom Apps distribution.
See [Apple's TestFlight overview](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/).
No signing, upload, tester invitation or production deployment has been performed
as part of the local build.
Xcode's connected account currently shows only **Personal Team** (checked
2026-10-03). Confirm an enrolled team before attempting the TestFlight upload.

## What is native

- SwiftUI presenter bar: Talk to Axel, Dealership CRM, inventory, scenarios,
  new prospect, guide, reload and sign-out.
- App icon, dark appearance, adaptive layout, connection indicator and recovery.
- Microphone permission confined to the trusted private workspace and main frame;
  camera permission denied. No recording on launch or foregrounding.
- Audio and capture pause when backgrounded or opening the presenter guide/browser.
  Switching back requires a deliberate tap to resume listening.
- The display stays awake while an authenticated presentation is active.
- Deliberate external links open in a separate Safari sheet. Redirects cannot
  navigate the workspace into an arbitrary site. Login cannot invoke the bridge.

The conversation and CRM are shared web components, not a second native copy of
the business logic. This keeps the website and app behavior in step. Sessions are
bound to the authenticated browser and expire after eight hours. Only an opaque
session ID is persisted locally for app restart; no transcripts or API keys are
stored by the native bridge. Private responses are not cacheable. Sign-out and
revocation block session access even through the public API URLs.

## Validation

```sh
.venv/bin/python manage.py test core.test_experience_ipad core.test_experience --noinput
swiftc -module-cache-path /tmp/guru-drive-swift-cache \
  ios/GuruDrive/GuruDrive/AppPolicy.swift ios/GuruDrive/Tests/main.swift \
  -o /tmp/guru-drive-policy-tests
/tmp/guru-drive-policy-tests
node --test frontend/experience/session.test.cjs frontend/experience/voice.test.cjs
```

The server suite covers employee access, CSRF, public-site preservation, browser
isolation, private session revocation, CRM handoff/edit/resume/reset and the existing
dealership flows. Native checks cover trusted origins, navigation escapes and CRM
session URLs. Debug simulator and unsigned Release device builds compile.
The JavaScript tests cover quiet voice capture, silence, cancellation, microphone
release before playback, and preserving a saved prospect across a failed resume.

Before using the TestFlight build in a sales presentation, complete a physical
iPad check: sign in; allow the mic; have a multi-turn spoken conversation; provide
fictional name/phone/email; book a vehicle appointment; submit the sample financing
form; inspect/edit its CRM record; return to Axel; background/foreground; test a
network interruption; reset and sign out. Simulator checks cannot certify physical
microphone quality, routing, Bluetooth/headset behavior or live provider access.
