# Demo analytics and attribution

Managers use `/demo/automotive/manage/` for 7/30/90-day reporting, rep filtering, session/source/scenario/version rows, voice/text turns, average successful AI-turn latency, tool activity, handoff/CRM views, real assessment requests and field feedback.

Events include started, turn (voice/text + latency), tool/tool_error (name only), inventory_browsed, transcribed, speech_delivered, voice_error, llm_error, handoff_viewed, crm_signed_in, crm_viewed, assessment_clicked, assessment_requested, presentation and reset. Actual demo appointment/trade/search/comparison operations are counted through successful tool names. Session start → last committed turn/reset gives interaction duration; time spent idle on a page is not represented as work or a phone call.

The logged-in rep owns a field session. A signed share link passes the rep and scenario to a new public session without customer history. On deliberate real Growth Assessment form submission, `DemoConversion` preserves rep, source, vertical, scenario, content version, session and timestamp. The real lead is assigned to the still-authorized rep. Invalid signatures do not assign a rep.

A CTA click is **not a booking**. The existing Calendly widget remains external; there is no verified Calendly booking webhook in this feature. Manager reports label form submissions as assessment requests, never booked appointments. Do not infer revenue or show-rate uplift from these counts.

Feedback categories: wrong answer, inventory mismatch, voice, UI, slow, scenario, unhandled prospect question, feature request, other. Entries carry rep/session/scenario and notes and can be marked reviewed. Synthetic activity is separate from the real employee call/lead metrics dashboard.
