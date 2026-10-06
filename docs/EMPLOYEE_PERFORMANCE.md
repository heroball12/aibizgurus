# Employee performance and lead oversight

Owners see the employee scoreboard at `/owner/`. Owners and admins also see it on `/ops/` and `/owner/staff/`. Select an employee for lead controls and their sales/site activity history. Reports support date ranges, employee search, sorting and CSV export.

## Counting rules

- One successful manual lead edit or note per lead per request counts as one **call / update** for the actor, irrespective of lead assignment. Explicit logged calls also count. This is an activity proxy, not telephony verification.
- An unchanged save, failed form, duplicate spreadsheet retry, background update, website research, import or page visit does not add a call. Spreadsheet and bulk edits count each changed lead once. Creation alone is not a call.
- A booked assessment requires both a confirmed appointment timestamp and the appropriate status. Bookings, completions, proposals, wins and losses count distinct leads with that transition in the date range. Repeated saves do not create extra bookings. Booking rate uses unique leads worked (including confirmed bookings) as its denominator.
- Assigned leads, upcoming booked status, overdue/due follow-ups, warm/hot, archived and review counts describe the **current** pipeline. They are intentionally separate from the date-filtered actor activity.
- Clock hours are clipped to the reporting window. Running shifts stop accruing after the existing eight-hour automatic clock-out limit. Calls per hour uses those clocked hours.
- Finder searches/results, imports, sign-ins, recorded page requests and completed training videos use their source records. A completed training video is not a certification. Last activity is a recorded request, not proof of live presence.
- Dates use the application's timezone (America/Los_Angeles); the end date is inclusive. CSV exports include the period and timezone.

## History and permissions

`audit.EmployeeLeadEvent` stores actor, lead identity, timestamp, source, field changes and outcome flags. Request/lead uniqueness prevents duplicate credit from multiple saves or overlapping note/activity records. Events survive lead reassignment/deletion and are read-only in Django admin. Existing general audit logs remain available. Owners can open **Recover historical activity** from the dashboard or CRM scorecards. Review the first batch and start recovery once; the page processes bounded batches and reports progress. Reload to resume after an interruption. All-time metrics include recovered events, with a separate Recovered updates column and Historical labels.

Recovery is restricted to records before the `audit.0008_employee_lead_events` migration timestamp. It preserves the original author and time, groups overlapping audit/note/activity records by recorded successful request, and uses deterministic identifiers to prevent duplicates on rerun. A duplicate note/activity pair without request logs is matched only by the same author, lead, exact text and a two-second timestamp window. Unattributed records, imports, page visits and generic updates without request boundaries are skipped. Structured status transitions may recover proposal/win outcomes; assessments additionally require a contemporaneous appointment timestamp in the saved evidence; current lead status is never used to invent historical outcomes. Nearby existing counter events are conservatively excluded.

CLI alternative: `python manage.py recover_sales_history` previews; add `--apply` to recover. Preview totals can overlap across evidence sources; application merges them. Activity with no retained evidence cannot be reconstructed. Older audit saves lack full diffs and may include unchanged submissions; recovered totals are kept separately visible for that reason.

Employee pages, exports and logs require owner/admin access. Employee-scoped bulk actions retain their scope server-side, including delete-all-filtered. Employees retain access only to their own active internal leads. Managers can inspect and edit archived internal leads. Current lead management screens retain their normal deletion confirmation.

## Deployment and verification

Run the usual `python manage.py migrate`. Migration `audit.0008_employee_lead_events` depends only on the committed business verification migration, not on pending AI outreach. Deploy the new migrations as usual. Historical recovery requires no credentials or paid services and does not alter leads, training credit or assignments.

Run `python manage.py test audit.test_performance audit.test_history core.tests crm.test_sheets crm.test_selling crm.test_calendly`. Tests cover attribution, notes, bulk/sheet updates, retries, rollback, assessment deduplication, deletion retention, archived access, permissions, date boundaries and CSV output.


## Guided selling and follow-up plans

**Today → Start selling** (`/crm/sell/`) prioritizes due follow-ups, then warm/hot opportunities and new records within the existing user scope. Future follow-ups, archived/closed/restricted leads and booked assessments are excluded. Guru opens with selected lead context; the screen offers a grounded opener, recent notes, the email draft workspace and a tracked booking link. Save & next records one manual outcome and moves forward. Skipping adds no activity. Signed versions prevent stale writes and persisted submission IDs prevent duplicate credit on retry.

Introduction, after-demo and assessment-invitation plans create internal reminders. Each saved conversation advances a step; an explicit callback date takes precedence. Plans stop on booking, closure, archiving or do-not-contact. They never send email/SMS or place calls automatically. Completing the last step ends the plan; the rep still decides the next disposition.

## Specialist controls

Owners can grant **AI specialist** on the staff account form. Strategy/custom pricing fields are restricted in the assessment form, spreadsheet schema/import/export, and Django lead admin. Rep updates preserve existing specialist notes. Guru's rep-coaching context excludes strategy/pricing. Only qualified specialists discuss custom pricing during a Growth Assessment; no automated price quotes are introduced.

## Calendly setup

1. Deploy the migrations and code. Keep `PUBLIC_BASE_URL=https://aibiz.guru` in Render.
2. In James's Calendly account, open Integrations & apps → API & webhooks and generate a personal access token. Select `users:read`, `event_types:read`, `scheduled_events:read`, and `webhooks:write` (which also includes webhook read access); Calendly requires a plan supporting webhooks.
3. Store the token only in Render's `CALENDLY_API_TOKEN`. Generate a random signing secret (for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`) and store it in `CALENDLY_WEBHOOK_SIGNING_KEY`. Do not place either in Git or chat. Redeploy.
4. As owner, open **Assessments → Calendar connection & unmatched bookings** and click Connect. This registers a user-scoped subscription for created/canceled invitees and selects James's `30min` event type. It does not schedule appointments or send outreach.
5. Book a sample appointment using a lead's calendar link, then cancel/reschedule it. Verify lead status/time, rep attribution, Last webhook time and metrics. This live provider test remains necessary after connection; automated tests use signed fixtures/mocked provider calls.

The endpoint is `/crm/assessments/calendly/webhook/`. It verifies HMAC signatures and a three-minute timestamp tolerance before processing, filters the event type, ignores duplicate/older notifications, and applies changes transactionally. A rescheduled booking cannot be cleared by the old booking's later cancellation. Bookings count as assessments, never calls. A cancellation adds a due follow-up but does not erase the historical booking event. Historical booking metrics count distinct leads per period, not raw appointment objects.

Tracked links preserve the originating rep for 180 days. Plain links use a unique CRM email match and credit the assigned rep. Email mismatches, ambiguous matches, conflicting appointments, inactive leads and missing tracking go to the owner review queue. Review queues never automatically reopen do-not-contact leads. Existing calendar appointments are not bulk imported. Booking synchronization begins after connecting. Credentials are never stored in database records; only connection metadata is retained. If the signing secret changes, remove/recreate this integration's subscription in Calendly and reconnect; the app refuses to claim an old subscription uses the new secret.

Provider references: https://developer.calendly.com/api-docs/overview/webhooks/webhook-signatures and https://developer.calendly.com/api-docs/calendly-api/webhooks/get-sample-webhook-data.
