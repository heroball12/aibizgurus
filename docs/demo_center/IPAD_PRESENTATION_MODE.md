# iPad field setup

1. In Safari, open the deployed HTTPS site and sign in using the rep's existing AIBG employee login.
2. Open `/demo/automotive/`. Test a spoken exchange while on reliable internet.
3. Use Safari Share → Add to Home Screen. The page supplies a web app manifest, standalone appearance, theme color and Apple web-app metadata. This is an online app; no service worker stores conversations or pretends the AI works offline.
4. Choose a relevant scenario in Demo controls, then tap Presentation. Navigation and the lower marketing section are hidden while attribution, Exit presentation, New prospect and Show dealership view remain available.
5. An optional browser screen wake lock is requested when supported. It is not assumed to exist on every iPad/browser. Device auto-lock and Safari microphone settings remain device controls.

The app uses safe touch targets, responsive single/two-column layouts, scrollable inventory and an internally scrolling conversation. Landscape is optimized for conversation beside results; portrait places the inventory below. iOS supports the MediaRecorder MP4 path when available. Unsupported/denied microphone access leaves the text input usable.

Do not promise offline AI. Keep a hotspot available. Connection failures are visible and Retry preserves the successful conversation. Switching away pauses microphone/audio. Returning requires tapping the microphone again. After every dealership, use New prospect and confirm the reset before handing the iPad to the next person.

The fictional CRM sign-in is a demonstration identity separate from the real employee login. The workspace uses this browser's existing session and cannot be opened by another device just by copying a record URL. The QR opens a fresh demo rather than sharing private conversation state.
