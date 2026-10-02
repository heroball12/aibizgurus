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

`audit.EmployeeLeadEvent` stores actor, lead identity, timestamp, source, field changes and outcome flags. Request/lead uniqueness prevents duplicate credit from multiple saves or overlapping note/activity records. Events survive lead reassignment/deletion and are read-only in Django admin. Existing general audit logs remain available; no speculative historical calls or bookings are backfilled.

Employee pages, exports and logs require owner/admin access. Employee-scoped bulk actions retain their scope server-side, including delete-all-filtered. Employees retain access only to their own active internal leads. Managers can inspect and edit archived internal leads. Current lead management screens retain their normal deletion confirmation.

## Deployment and verification

Run the usual `python manage.py migrate`. Migration `audit.0008_employee_lead_events` depends only on the committed business verification migration, not on pending AI outreach. New detailed sales metrics begin after deployment. No new API credentials or paid services are required.

Run `python manage.py test audit.test_performance core.tests crm.test_sheets`. Tests cover attribution, notes, bulk/sheet updates, retries, rollback, assessment deduplication, deletion retention, archived access, permissions, date boundaries and CSV output.
