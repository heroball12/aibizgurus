# AI Business Gurus Platform

Complete Django starter platform for multi-industry AI receptionists.

## What is included

- Public sales site
- Supported industries directory
- Unsupported industry consultation request flow
- Client signup/login
- Client dashboard
- Business profile onboarding
- AI instance settings
- Embeddable iframe widget
- Real OpenAI integration with fallback mode
- Optional client-provided OpenAI key
- Optional platform OpenAI key
- Optional Twilio voice AI webhook
- Optional Twilio SMS webhook
- Call/SMS logging
- Employee/ops dashboard
- Internal CRM for AI Business Gurus sales leads
- Client lead inboxes and conversation transcripts for each business account
- Industry templates across many business types
- Render/PostgreSQL-ready setup
- SQLite default for local testing
- Runway video concierge with typed/voice input, guided browsing, and consultation handoff. See [setup and deployment notes](docs/VIDEO_CONCIERGE.md).

## Quick Start

```bash
cd ai_business_gurus_platform
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --upgrade
cp .env.example .env
python manage.py makemigrations
python manage.py migrate
python manage.py seed_industries --clear
python manage.py check_signup_industries
python manage.py verify_demo_flow --create-test
python manage.py check_audit
python manage.py createsuperuser
python manage.py runserver
```

Open:

- Public site: http://127.0.0.1:8000/
- Client portal: http://127.0.0.1:8000/portal/
- Employee ops: http://127.0.0.1:8000/ops/
- CRM: http://127.0.0.1:8000/crm/
- Django admin: http://127.0.0.1:8000/admin/

## Optional OpenAI

Add to `.env`:

```env
PLATFORM_OPENAI_API_KEY=your_platform_key
OPENAI_MODEL=gpt-4o-mini
```

Clients can also save their own OpenAI API key in Integrations.

## Optional Twilio

Add to `.env`:

```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
PUBLIC_BASE_URL=https://yourdomain.com
VALIDATE_TWILIO_SIGNATURES=1
```

Twilio webhooks per assistant:

- Voice: `/voice/incoming/<assistant_slug>/`
- SMS: `/voice/sms/<assistant_slug>/`

## Embed Example

```html
<iframe src="https://yourdomain.com/ai/widget/client-assistant-slug/" width="100%" height="650" style="border:0;border-radius:16px;"></iframe>
```

## Production Notes

This repo includes a Render blueprint (`render.yaml`) and build script (`build.sh`). The production path is:

```bash
./build.sh
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers $WEB_CONCURRENCY --timeout 120
```

Required production environment variables:

```env
DEBUG=0
SECRET_KEY=generate-a-long-random-secret
DATABASE_URL=postgres://...
ALLOWED_HOSTS=aibiz.guru,www.aibiz.guru
CSRF_TRUSTED_ORIGINS=https://aibiz.guru,https://www.aibiz.guru
PUBLIC_BASE_URL=https://aibiz.guru
FIELD_ENCRYPTION_KEY=generate-a-real-fernet-key
PLATFORM_OPENAI_API_KEY=your_platform_openai_key
OPENAI_MODEL=gpt-4o-mini
SECURE_SSL_REDIRECT=1
SESSION_COOKIE_SECURE=1
CSRF_COOKIE_SECURE=1
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_PRELOAD=1
WEB_CONCURRENCY=3
```

Optional production environment variables:

```env
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_STARTER=
STRIPE_PRICE_GROWTH=
STRIPE_PRICE_PRO=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
VALIDATE_TWILIO_SIGNATURES=1
OWNER_ALERT_EMAIL=
EMAIL_BACKEND=
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
```

Operational endpoints:

- Health check: `/healthz/`
- Robots: `/robots.txt`
- Sitemap: `/sitemap.xml`

Before launch, create the first owner/superuser through Django admin or `createsuperuser`, configure real Stripe price IDs if checkout should be live, connect the production domain, and verify Twilio/OpenAI webhooks with real credentials.


## Upgrade Pack Added Before Localhost Test

This upgraded package adds:

- Encrypted integration credentials using `FIELD_ENCRYPTION_KEY`
- Masked credential display in the dashboard
- Best-effort email/log alerts when leads are created
- Widget chat rate limiting
- Stripe-ready billing app and checkout placeholders
- Billing model/admin
- Safer OpenAI error logging/fallback
- Central employee permission helper
- Production logging baseline

Generate a real encryption key before production:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then place it in `.env`:

```env
FIELD_ENCRYPTION_KEY=your-generated-key
```
# aibizgurus
# aibizgurus


## Sales workspace

Staff sales work starts at `/crm/`: Today, Lead Finder, Pipeline and Assessments. Existing imports, detailed statuses, assignment and bulk controls remain available under More tools and Advanced records. Existing lead records are preserved.

- Lead Finder uses real OpenStreetMap public listings with phone numbers. Result cards link to the listing and business website when supplied. Results persist across days and are paginated; adding a prospect does not record a call. Phone deduplication also checks archived and do-not-contact records, including another check when saving a result. Public results are cached for five minutes and provider failures trigger a one-minute cooldown. Public source coverage varies; a requested count is a limit, not guaranteed inventory. The Overpass endpoint remains configurable through `LEAD_FINDER_OVERPASS_URL`; see the [official instance directory](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances) when choosing a provider appropriate to your usage.
- Searches up to 20 run immediately. Larger quantities are offered only when `CELERY_BROKER_URL` (or `REDIS_URL`) is configured; a running Celery worker is still required. Worker/provider errors are shown in search status. No new paid search account is required.
- Growth Assessments are 15–20 minute video business reviews with an AI Specialist: current operations, AI opportunities, implementation strategy and custom pricing. The existing Calendly link supplies availability and invitations. Staff explicitly confirm the booking and record its time in the CRM; this is not an automatic Calendly synchronization. Times use the configured `America/Los_Angeles` timezone.
- Each lead has a structured assessment brief, simple conversation outcomes, follow-up dates and an activity history. Raw notes and advanced classification controls remain accessible.
- Ask Guru opens a staff-only Type / Speak coaching window using the existing Runway credentials and avatar. The server checks staff access and lead ownership on both rendering and session creation. Only the selected business name, industry, stage and bounded assessment fields enter the persona; contact fields, meeting links and raw notes are excluded. Information typed into the call itself is processed by Runway under the existing live-call terms. The coach proposes wording and role-plays; it does not send outreach, mutate CRM records, or book appointments. Public Guru and demo sessions keep their existing audio transport and visitor handoffs.

Deployment uses migration `crm.0009` (additive fields only), already covered by the existing Render migration commands. No additional environment variables are needed for the coach when public Guru is configured.

## Lead sheets

`/crm/sheets/` provides a built-in spreadsheet editor; it does not require Google OAuth or create a Google-hosted document. Create a blank sheet, open an Excel/CSV file for review, or use **Edit this view in a sheet** from CRM screens. The contextual action respects lead, pipeline, queue, import and Finder filters. Finder sheets edit existing staging results; saving them does not promote results or record outreach.

- **Save to CRM** applies all valid edits in one transaction, with row errors, duplicate checks, owner/assignment permissions, do-not-contact protections and conflict detection. Retries use a mutation ID to avoid duplicate inserts. Existing records retain fields outside the sheet. Follow-up dates also update the CRM's next-follow-up time. Confirmed assessment bookings still belong on the lead page.
- Named sheets store ordered record references, not another copy of the lead values. Reopening reads current CRM data and removes inaccessible rows from the view. Removing a row from a sheet does not delete the lead. Sheets themselves are private to their creator.
- Sheets support 500 rows, column groups, dropdowns, dates and multi-cell TSV paste. Larger filtered selections clearly show the cap; refine the source view to edit the remaining records. Exports support up to 10,000 filtered records. Drafts live in the current browser tab with an unsaved-change warning.
- Excel downloads include frozen headers, text-safe phone numbers, validation dropdowns and hidden signed record references. Reopen a current export as the same user to update its existing CRM rows, even after changing their names. Stale, expired (90 days), inaccessible or cross-user references are rejected. CSV exports escape spreadsheet formulas. `.xlsx` and UTF-8 `.csv` uploads support 5 MB files; Open file previews the first visible worksheet and reports ignored columns. The original tracker importer still supports multi-tab analysis.
- Excel files are compatible with Excel and Google Sheets. The OOXML writer uses Python's standard library and adds no runtime dependency. Migration `crm.0010` adds the private sheet model.

## Teamspace chat

`/team/messages/` contains the redesigned staff inbox and responsive conversations. Attachments, reactions and owner oversight remain available. Sending uses an authenticated JSON response with an idempotent message nonce, preserves failed drafts and avoids full-page reloads. Feeds return 60 messages at a time with earlier-message loading and reconnect backoff. Polling never marks messages read: the visible, focused conversation explicitly acknowledges the latest displayed message when scrolled to the bottom.

Notification preferences are stored per account: Aurora, Glass, Pulse, Soft chime or Silent; volume; message previews; desktop alerts; Do Not Disturb. Individual conversations can be muted. Unread totals count every active membership, and browser tabs coordinate notification deduplication. Alerts operate while an app tab remains open (browser timer throttling applies); this is not closed-browser Web Push. Desktop permission is requested only by the user's Enable alerts action, and sounds follow browser audio permissions. The global Team button is also available in the CRM.

Team video calls and screen sharing are deferred. Migration `audit.0006` adds notification preferences, muted memberships and message retry IDs; `audit.0007` removes the experimental call schema already applied in the local preview. Existing messages and preferences are preserved. These migrations run through the existing Render migration command.
