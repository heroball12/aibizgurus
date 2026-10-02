# AI Experience Center — Automotive pilot

This extends the existing `core` Demo Center. `/demo/` keeps its 13 working category demonstrations and introduces the tool-enabled Velocity Motors flagship at `/demo/automotive/`. The existing automotive category remains the Apex Auto Studio repair-shop preview; the new flagship is explicitly a dealership experience. No second Django app or parallel real CRM was created.

## Reused foundations

- Existing industry catalog, Axel helmet artwork, purple/gold brand, authentication and employee roles.
- `PlatformAIService` server-side OpenAI configuration and metadata-only usage accounting.
- Shared database-backed `RequestBudget` for limits across workers.
- Existing Growth Assessment form and real lead capture; attribution is added only after that form is deliberately submitted.
- Voice lessons from the existing Guru/Runway experience: microphone gating during speech, quiet-voice support, typing pauses and explicit interruption. Existing Guru and Runway calls are unchanged.

The existing Runway character transport handles its own conversation and client navigation events. Velocity needs authoritative inventory tool results and one persistent history across voice/text. Phase 1 therefore uses an OpenAI transcription → existing platform AI with validated tools → speech pipeline. It does not launch a second ungrounded character conversation. See VOICE.md for limits and the live validation gate.

## Records and boundaries

`core/demo_models.py` defines:

- `DemoExperience`: publication/public access and current revision.
- `DemoRevision`: immutable business, inventory and scenario snapshot pinned by every session. Each AI turn also records the deployed `BEHAVIOR_VERSION`; a code deployment may update behavior for existing sessions, while their business data stays pinned.
- `DemoSession`: random UUID plus server-side browser binding, rep/source/scenario, bounded conversation and synthetic workflow state. Anonymous sessions expire after two hours; staff sessions after eight.
- `DemoCRMLead` / `DemoCRMActivity`: a working fictional dealership customer record and activity timeline, scoped to one session, with staff stage/assignment/notes.
- `DemoEvent`: non-content usage, tool/action/failure and latency metadata.
- `DemoShareLink`: opaque signed attribution to a fresh session; never shares a transcript/customer.
- `DemoConversion`: provenance of a deliberately submitted real Growth Assessment request.
- `DemoRepAccess` / `DemoFeedback`: employee access overrides and internal field reports.

The fictional CRM never imports `crm.Lead`, clients, billing or outbound providers. Only `access.attribute_assessment` touches a real lead, after the existing real form validates and saves it. Demo bookings only update the caller's synthetic state and fictional CRM.

## Request flow

1. Render no-store page and initialize a browser-bound session over CSRF-protected POST.
2. Each message obtains a 75-second lease. Requests outside the session's browser binding are rejected.
3. The model receives policy, scenario/current state and six bounded complete prior tool turns—not the inventory database.
4. Model requests go through `PlatformAIService.tool_completion`; Pydantic validates each allowlisted tool. Only deterministic tools can search inventory, offer slots or mutate fictional records.
5. A transaction rechecks the lease, persists the transcript/state, updates the fictional CRM and records analytics. Failed generations do not commit partial bookings.
6. Repeating the last successful request UUID returns its saved result. Reset invalidates in-flight responses before clearing content and fictional CRM rows.

Contact intake adds validated phone/email and a purchase-plan preference to session customer state. The financing tool stages a draft plus an explicit UI-open request; the browser opens the local form when that request changes. `/demo/automotive/financing/` handles CSRF-protected, browser-bound form opening/submission, locks the session and refuses writes during an active AI lease. Financial fields accept only server-owned sample profiles and enumerated options. Submitted data and its activity are saved atomically to the same isolated state and CRM snapshot. No new database table or migration is required for contact/financing fields.

## Deployment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_center --publish
python manage.py collectstatic --noinput
```

Use the existing Render `PLATFORM_OPENAI_API_KEY` or `OPENAI_API_KEY`. No Runway key, new storage bucket or media disk is needed for this feature. Illustrative images are small, versioned static assets.

The seed command upgrades the original stock `velocity-2026.1.1` content to `velocity-2026.1.2`, which adds financing instructions. It preserves manager-created content revisions. Existing sessions keep their original business snapshot; deployed behavior supports the fictional application in both versions. Start a fresh session after updating for the latest scenario copy.

Optional settings: `DEMO_CHAT_MODEL` (defaults to the existing chat model), `DEMO_AI_DAILY_LIMIT=600`, `DEMO_VOICE_DAILY_LIMIT=600`. These are bounded even for employees. Do not configure zero as unlimited.

Run `python manage.py purge_demo_sessions` daily in the existing operational scheduler to clear conversations and fictional customer records that expired more than 14 days ago. `--dry-run` previews the count. Aggregate analytics and attribution remain. No production deployment, account change or scheduler creation was performed by this implementation.

## Verification status

Automated provider calls are mocked; tests validate orchestration and deterministic data boundaries, not the intelligence or latency of a live model. The local checkout had no OpenAI key during implementation. Before a field pilot, run the real conversation/voice checklist in AUTOMOTIVE_DEMO.md on Render or a configured local environment and on the actual iPad. Do not describe the pilot as live-verified until that check passes.
