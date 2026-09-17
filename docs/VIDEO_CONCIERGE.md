# Guru video concierge

`/ai/concierge/` hosts a live Runway Character in a floating video-call window. The public-site launcher opens this experience at the visitor's current page. Type or Speak can be selected before connecting; microphone and sound controls remain available during a call. The visitor's camera is never requested. Minimizing keeps the video visible while they browse.

## Production activation on Render

The existing Python build and migration commands support this feature. No Node runtime, new worker, or additional Python dependency is required in production. Set these variables in the existing Render web service before deploying the code:

| Variable | Value |
| --- | --- |
| `RUNWAYML_API_SECRET` | The Runway developer key saved in the ignored local `.env`; copy privately into Render, never into Git or chat. |
| `RUNWAY_AVATAR_ID` | `b6494a17-6106-4592-9e52-e6685a76e830` (Guru, created in the current Runway developer organization) |
| `VIDEO_CONCIERGE_ENABLED` | `1` |
| `VIDEO_CONCIERGE_DAILY_LIMIT` | `20` initially |
| `VIDEO_CONCIERGE_HOURLY_LIMIT` | `3` initially, per visitor IP |
| `VIDEO_CONCIERGE_MAX_SECONDS` | `300` maximum |

The developer organization needs Characters access and API credits. The media-generation app subscription is separate from developer API usage. Runway can end idle sessions earlier than the five-minute maximum. Provider concurrency limits still apply; requests beyond capacity fall back to booking or a team follow-up. Limits above count attempted starts, and are database-backed across Render workers. Set `VIDEO_CONCIERGE_ENABLED=0` to disable new live sessions while retaining the consultation and follow-up paths.

Local configuration is complete. **Render environment configuration and production deployment have not been performed as part of this change.** The local development preview uses an hourly limit of 10 for manual testing only; the production default remains 3.

## Conversation and website actions

Runway's native Character receives audio. Spoken input uses the visitor's microphone after browser permission. Typed messages are converted to speech with Runway's `eleven_multilingual_v2` endpoint and fed into the same live audio channel through Web Audio. Visitors see their original text and hear Guru's spoken video reply; they do not hear the synthesized readback. This adds speech-generation latency and API usage. Messages are limited to 500 characters and 12 typed messages per call.

The client uses the official `@runwayml/avatars` SDK for session credentials, transcripts, and tools, with LiveKit for media. The permanent API key remains on the server. Browsers receive one ephemeral session key bound to their Django session; task receipts for typed speech are signed and expire. The app does not save video, audio, or conversation transcripts. Runway may retain them, disclosed before a call. Explicitly submitted follow-up details are stored in consultation requests and the internal sales CRM. A volunteered preferred name and short business goal are also retained in the visitor session for introductions, with a two-hour usage window; full call transcripts and unsent drafts are not copied into that memory.

Guru's knowledge comes from public services, roles, industries, and the shared pricing catalog in `core/catalog.py`. It can:

- Change between allowlisted public pages without disconnecting the call.
- Bring the consultation calendar or request section into view.
- Draft a follow-up form using details volunteered by the visitor.
- Reveal a secure portal link for existing clients.

Guru's conversation instructions and each action tool require spoken guidance: explain what is about to open and why, with one relevant next step, in a single spoken reply accompanying the action. Both sentences are generated before invoking the tool because a tool call can end the provider's spoken turn. This applies to page changes, highlighted sections, portal links, and follow-up drafts. Related actions on one page share a concise explanation, and a declined consultation should not trigger repeated booking pitches. These instructions apply to new calls after the updated server code is deployed.

The visitor chooses and confirms a Calendly appointment. A follow-up request is not a reservation. Forms require manual submission and contact consent; the model cannot submit them. Account pages open separately and remain protected from framing. Guru cannot read or change private account data, issue refunds, or manage client billing. Questions requiring that access are handed to the team.

The call checkbox links to AI Business Gurus Terms of Service in a compact dialog. Opening or closing the terms does not check the agreement box or start a call. The same assistant-specific terms are available at `/ai/concierge/terms/`, including the Runway processing and recording disclosure, AI limitations, appropriate use, form submission, booking, and support information.

## Build and verification

The homepage's “Meet your AI employee” action replaces the arrival film and copy with the concierge at `/ai/concierge/?embed=1`. The same call stays open when the visitor or Guru opens an approved page. The initial embedded screen does not load a second copy of the homepage. Its frame policy allows only this site's origin; account pages remain protected. “Back to the film” ends the call before removing the interface.

For startup performance, the call transport is preloaded when the connection interface opens, and readiness is polled more frequently at the beginning. An initial paid session and microphone capture require the visitor to agree and press Start. A requested demo transfer can reuse that agreement through a short-lived, single-use handoff after Guru finishes speaking and closes its call. Connection progress shows the actual stage and elapsed time.

`python manage.py sync_guru` saves the current public personality and greeting as Runway character defaults. `build.sh` runs it on deployment when Guru is configured. Runway documents slower provisioning with per-call personality or greeting overrides. Calls use saved defaults only after verifying they match the current code; the check is cached for five minutes. A changed prompt or unavailable sync falls back to this release's explicit instructions. Public persona configuration is shared; visitor messages and session credentials are never cached. No new environment variables are required.

In a local provider test on September 16, 2026, session readiness changed from 9.62 seconds with overrides to 2.34 seconds with matching defaults (including the first configuration lookup). These are individual measurements of provisioning, not a guarantee of end-to-end video latency; network, WebRTC and provider load still affect connection time.

The homepage integration passed 92 Django tests and 7 Node tests, including consent, same-origin framing, persona fallback, navigation and cancellation before a call finishes connecting. Desktop and 390 × 844 mobile browser checks covered the hero transition, terms dialog, guided navigation, minimized video and return to the film. The transport bundle is unchanged; provider readiness was measured separately from browser video playback.

```sh
python manage.py migrate
python manage.py test --noinput
python manage.py makemigrations --check --dry-run
pnpm --dir frontend/concierge install --frozen-lockfile
pnpm --dir frontend/concierge test
pnpm --dir frontend/concierge build
python manage.py collectstatic --noinput
```

Commit `static/js/concierge-call.js` whenever its source or lockfile changes. The compiled bundle is intentionally checked in for the Python-only Render build. `node_modules`, `.env`, the SQLite database, and generated `staticfiles` are ignored.

Verified locally on September 16, 2026: 98 Django tests and 3 Node tests passed; production-mode static collection and migration consistency passed. Live Runway tests confirmed moving video with sound, typed questions producing spoken answers, correct Starter pricing, automatic consultation navigation, the Calendly calendar loading available dates, and a follow-up draft prepared without submission. Mobile layout was checked at 390 × 844. Physical microphone capture and mobile Safari still require device testing; the live audio transport itself was exercised by the typed speech bridge. No real appointment or follow-up request was submitted during browser testing.

After deployment, use a current browser over HTTPS to check Type, microphone permission and mute/unmute, Sound on/off, End call, navigation while connected, calendar loading, and one authorized internal test handoff. A browser reload ends the call; if cancellation is interrupted, the next start offers End call to close the previous session.

## Character artwork

The current portrait is `static/img/guru-helmet.jpg`: a seated graphite robot with a completely sealed faceplate, thin purple visor, purple chest light and gold details. The older mouth-based portrait is retained as a historical asset but is no longer used by the call interface. The UI displays the original sealed-helmet artwork during speech, with a purple light driven by live audio. Runway's generated facial video is hidden because it can distort the visor into lips. A generated gesture clip still plays for guided page actions. The interface labels this treatment as voice-reactive robot artwork. See [DEMO_CENTER.md](DEMO_CENTER.md) for the category employees, revised audio transport, typing cues, current verification and limitations, and [DEMO_ARTWORK.md](DEMO_ARTWORK.md) for generation briefs.

Provider references: [Runway Characters](https://docs.dev.runwayml.com/characters/), [session defaults and overrides](https://docs.dev.runwayml.com/characters/concepts/#per-call-overrides), [integration](https://docs.dev.runwayml.com/characters/integration/), and [client tools](https://docs.dev.runwayml.com/characters/tools/client-tools/).
