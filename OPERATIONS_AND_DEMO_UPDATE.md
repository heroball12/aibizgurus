# Demo Center and operational fixes

This update keeps the existing Django application, purple/gold brand, database, and Git → Render deployment flow. It does not replace production credentials or migrate hosting.

## Demo Center

- Original cinematic neural-core artwork, generated with the built-in image tool, in `static/img/demo-neural-core.png`.
- Four fictional industry scenarios: home services, dental, real estate, and auto services.
- Selectable workflow stages, play/pause/replay, a changing lead preview, accessible keyboard tabs, and optional device speech.
- Public conversational preview using the existing platform OpenAI key. A bounded guided response is explicitly labelled when AI is unavailable. The preview takes no real booking or messaging actions.
- A real, locally rendered, 24-second H.264 MP4 at `static/video/demo-workflow.mp4`. **The film is silent.** Captions, transcript, native controls, and a poster are included. The optional interactive speech preview is separate from the film.
- The video is original code-drawn motion graphics, not third-party stock footage or a recorded live customer session. Rebuild with `scripts/render_demo_video.py`; production does not need its build-only Pillow/FFmpeg dependencies.
- Responsive mobile navigation and repairs to the home-page demo/consultation links.

Artwork brief: a luminous violet plasma core in smoked glass, champagne-gold orbital arcs, and a dark plum background, with space for website copy. No generated text, logos, or people.

## Functional changes

- Web chat now requires signed conversation ownership, validates lengths/contact fields, respects collection settings, reports errors honestly, and maintains one lead per conversation.
- Request and AI usage budgets are stored in the database so they work across multiple Gunicorn workers. Account endpoints are throttled as well.
- Staff passwords are validated; the old shared default is gone. Existing staff who still use it must change it. Editing a staff member with an empty password field preserves the existing password.
- Password reset/change flows are available. Login respects safe return URLs; logout requires a CSRF-protected POST.
- Stripe stores customer/subscription references and plan state; handles subscription updates, cancellations, failed invoices, and payment recovery; deduplicates events; and retrieves current subscription state to avoid applying stale events. Existing subscriptions created by the old checkout can be linked using their original Checkout client reference. Customer billing management opens Stripe’s portal.
- Checkout uses POST, client metadata, and idempotency keys. An existing subscription is not duplicated. Success-page access alone cannot activate an account.
- Twilio signatures default to enabled outside debug mode. Per-client Twilio auth tokens are supported. Webhook retries replay the original response. Calls keep their conversation across turns; SMS replies share a recent conversation and one lead.
- Lead Finder uses real OpenStreetMap listings only, correctly scopes cities within states, reports provider failures/empty results, prevents duplicate batch execution and competing staging writes, and refuses to promote legacy batches containing generated samples. Historical sample records are preserved for review.
- Failed queue dispatch is reported instead of leaving a job silently queued. The Celery task retries provider failures.
- Imports cannot modify another SDR’s assigned lead or add activities to it. Hidden Excel tabs are excluded; expanded workbook size/column limits are enforced; classification uses whole phrases.
- Portal totals reflect all records, and customer CSV export is isolated to the account and protects spreadsheet formula cells.
- The assessment page exposes its working request form alongside Calendly. Consultation and CRM writes are atomic and rate limited.
- New lead alerts are sent after commit with populated contact details. Missing recipients no longer cause contact/transcript contents to be logged.
- Repeated deployment seeding preserves customized industry templates. Explicit `seed_industries --force` restores bundled definitions when wanted.
- `/healthz/` tests database connectivity. `python manage.py check_operations` provides read-only configuration diagnostics without showing secrets or contacting paid services.
- GitHub Actions checks Python 3.14 with PostgreSQL, tests, migrations, and production static assets. The alternate Docker build now includes production static collection and excludes local secrets/data from its build context.

## Existing Render setup: release verification

The current environment values remain authoritative. Do not replace working secrets. The existing build/start commands apply the four new additive migrations and collect the new static assets.

1. Run `python manage.py check_operations --json` in the Render service. It reports configuration only, not successful provider delivery. Uploaded files must continue using the existing persistent storage mount through `MEDIA_ROOT`.
2. Ensure the existing Stripe webhook endpoint `/billing/webhook/` delivers `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `customer.subscription.created/updated/deleted/paused/resumed`, `invoice.paid`, `invoice.payment_failed`, and `invoice.payment_action_required`. Enable the Stripe customer portal in the existing Stripe account if it is not already enabled.
3. Existing recurring price IDs continue to work. Optional `STRIPE_SETUP_PRICE_STARTER`, `STRIPE_SETUP_PRICE_GROWTH`, and `STRIPE_SETUP_PRICE_PRO` add one-time setup prices. If absent, the page states that setup not shown in checkout is arranged separately. No guessed fees or new charges are introduced.
4. Keep Twilio signature validation enabled in production and use the exact public webhook URL. Existing platform credentials or active per-client Twilio integrations are used.
5. `LEAD_FINDER_ENABLE_PUBLIC_HTTP=1` enables the real listing source. If an existing environment explicitly sets it to `0`, searches report that they are disabled. The old fallback-provider setting is ignored; no synthetic prospects are created. A live Celery worker is needed for searches over 20; `process_lead_generation_batches` remains available for queued jobs.
6. `TRUSTED_PROXY_HOPS` defaults to one on Render, zero locally. It selects trusted appended entries from the right of `X-Forwarded-For`; adjust only for a different verified reverse-proxy chain. The global AI budget remains a separate cost boundary.
7. Confirm one password reset email, a test-mode Stripe payment/cancellation, and one Twilio test call/SMS in the deployed environment. Local tests mock these external services and do not spend money or message real customers.
8. Inspect any legacy sample batches reported by the diagnostic command. Already-existing CRM records are not silently deleted or reclassified.

## Validation

74 local automated tests pass. The production-mode smoke check renders 14 public routes successfully, compiles 58 HTML templates, and verifies eight new/updated manifest assets. Production static collection and Django’s deployment checks pass.

Automated tests cover conversation isolation, signed tokens, rate limits, lead deduplication and alerts, public demo CSRF/fallback/AI paths, subscription state and retries, legacy subscription linking, voice/SMS history and retries, staff account changes, password reset, safe redirects, tenant exports, hidden import sheets, seed preservation, real listing query construction, and existing CRM/team workflows.

Browser checks cover desktop/mobile layout, loaded artwork, industry switching, workflow selection/playback, guided chat, selected-industry signup links, keyboard navigation, mobile menu, video playback, and console errors. Local runtime is Python 3.12; the committed CI job targets the Render Python 3.14 version.

## Implementation references

- [Stripe subscription events](https://docs.stripe.com/billing/subscriptions/webhooks)
- [Twilio webhook signatures](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
- [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Overpass area queries](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL#Map_relation_to_area_(map_to_area))
- [Render reverse proxies and application rate limits](https://render.com/articles/how-render-handles-ddos-attacks)
