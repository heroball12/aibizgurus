# Reviewed outreach and Lead Finder research

**Current phase:** direct Gmail/SMS sending is deferred. Its production endpoints return 410. Use the [sales email copilot](sales_email_generator/USER_GUIDE.md) for reviewed copy/paste drafts. The transport setup below is historical reference for a later project, not deployment instructions for this phase. Lead Finder research and business verification remain active.

Employees can open a pipeline lead and click **Send email** or **Send text**. Guru drafts from saved notes, recent activity, the assessment brief and saved website research. The employee edits the recipient-specific draft and clicks **Confirm & send**. The recipient and sender are shown before approval; changing the contact requires a new draft. Messages aim at a 15–20 minute Growth Assessment. Pricing remains custom and is discussed only by an AI Specialist during that assessment.

Drafting reuses the existing Render `PLATFORM_OPENAI_API_KEY` / `OPENAI_API_KEY` configuration and model. No new AI key is needed. A missing key or provider failure produces an error, not pretend AI copy.

## Activate sending on Render

The normal Render start command runs migrations. No extra package, worker or database service is required. Deploy the code, then open **Sales → Workspace → Email & texting** for setup status and employee connections.

### Employee Gmail

1. In Google Cloud, use a project owned by the business's Google Workspace organization. Enable **Gmail API**.
2. Configure Google Auth Platform branding and choose an **Internal** audience for your Workspace staff.
3. Create an OAuth client of type **Web application**. Add this exact authorized redirect URI:

   `https://aibiz.guru/crm/outreach/google/callback/`

4. Put the following in the Render web service's Environment settings, never in Git or chat:

   | Variable | Value |
   | --- | --- |
   | `SALES_GOOGLE_CLIENT_ID` | Google web OAuth client ID |
   | `SALES_GOOGLE_CLIENT_SECRET` | Matching Google client secret |
   | `SALES_GOOGLE_REDIRECT_URI` | Exact URI above |
   | `SALES_GOOGLE_DOMAINS` | `aibiz.guru` (comma-separated if multiple company domains are allowed) |
   | `FIELD_ENCRYPTION_KEY` | A strong, persistent encryption key |

   **Preserve an existing production encryption key.** Other integrations may already depend on it. A new installation can generate a Fernet key privately with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Back it up with the database; changing it without migrating encrypted fields invalidates stored credentials.

5. If Workspace blocks the app, allow the OAuth client through your Workspace admin API controls. Each employee clicks **Connect Google Workspace** and grants sending access. The mailbox must be a verified company account in an allowed domain and cannot be connected to two employees.

The requested scopes are `openid`, `email`, and `https://www.googleapis.com/auth/gmail.send`. This integration does not read Gmail inboxes. Approved emails appear in the employee's Gmail Sent, and replies arrive in their Gmail inbox. Refresh tokens are encrypted in PostgreSQL; access tokens remain transient. Disconnect removes local access and attempts Google revocation.

Local OAuth testing needs an explicitly registered local callback, such as `http://127.0.0.1:8001/crm/outreach/google/callback/`, matching `SALES_GOOGLE_REDIRECT_URI` with `DEBUG=1`.

Reference: [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Gmail sending scope](https://developers.google.com/workspace/gmail/api/auth/scopes).

### Company SMS

Use an SMS-enabled Twilio number dedicated to sales. Existing assistant SMS routes remain separate.

| Variable | Value |
| --- | --- |
| `TWILIO_ACCOUNT_SID` | Existing Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Matching auth token |
| `SALES_SMS_FROM_NUMBER` | Company sales number in E.164 format, e.g. `+1…` |
| `PUBLIC_BASE_URL` | `https://aibiz.guru` |
| `SALES_SMS_MESSAGING_SERVICE_SID` | Optional Messaging Service SID; the configured number must be in its sender pool |

In the number or Messaging Service's incoming-message configuration, set HTTP **POST** to:

`https://aibiz.guru/crm/outreach/sms/inbound/`

Do not replace an assistant's existing incoming-message routing unless that number is being dedicated to sales. Complete Twilio's applicable sender registration and enable the number for the intended destinations. The app supplies each message's delivery-status callback automatically. CRM callbacks always validate Twilio signatures, even if the older voice integration's validation flag is disabled.

Employees must confirm that the prospect agreed to receive texts. Texts identify AI Business Gurus and include `Reply STOP to opt out.` in the reviewed content. STOP blocks that number across the sales feature. START removes the SMS opt-out but never silently clears a CRM Do Not Contact restriction. Replies are recorded on the most recent submitted conversation for that number. Unmatched inbound messages remain in `SalesSMSReply` for support investigation; there is no separate SMS inbox in this release.

Reference: [Twilio messaging webhooks](https://www.twilio.com/docs/messaging/guides/webhook-request), [Twilio opt-outs](https://www.twilio.com/docs/messaging/tutorials/advanced-opt-out).

### Final production check

Use a consenting internal recipient for the first live email and text. Check the exact edited body, Gmail Sent, SMS delivery callback, inbound reply and STOP. Automated and local UI tests use simulated providers; no real prospect messages were sent during implementation.

A draft UUID is a single send intent. The server claims it before calling the provider. Repeated confirmations do not resend it. If delivery is uncertain after a timeout, the same intent stays blocked and the UI offers **Check sending status**. Check Gmail Sent or Twilio logs before creating a replacement draft. “Submitted” means accepted by the provider, not delivered or read. Definitively rejected drafts require a new reviewed draft after the underlying issue is fixed. Drafts expire after 24 hours; generation and sending each have a per-employee hourly limit of 30.

## Dig deeper

Every Lead Finder result with a website has **Dig deeper**, also available on saved pipeline leads. It reads the homepage and up to two linked About, Contact or Services pages, respecting robots.txt. It saves public descriptions, contact details, headings, hours when present, and evidence for chat, booking and shopping/ordering tools. Existing contact fields are not overwritten. The report moves with a prospect into the pipeline and can inform AI outreach.

Known AI embed code is distinguished from general chat integrations whose AI mode is unconfirmed. Custom AI-assistant links are reported as offered conversations, not tested agents. This is a bounded public-HTML scan, not a JavaScript browser. Cookie-gated, dynamically injected and sign-in-only tools can be missed. No checkout, appointment, form or conversation is operated. “No evidence found” never means a feature is definitely absent.

Network requests accept only HTTP/S and standard ports, reject credentials and private/reserved addresses, pin the validated address for the connection, check every redirect, validate TLS, cap response size, and use a time budget. There are no cookies or authenticated browsing. Each employee has 20 scans per hour; a row cannot be rescanned more than once in a 30-second window. Website research uses no additional API key.

## Is the business still operating?

New directory searches exclude explicit business lifecycle closures, vacant shops and past end dates, and report the excluded count. An old disused amenity does not suppress a different currently active business at the same site. Normal weekly hours and old COVID-hours exceptions are not interpreted as permanent closures.

**Check operating status → Check public sources** refreshes the exact OpenStreetMap record and scans the business website for prominent closure notices. A renamed listing or closure notice flags the prospect for review. Unavailable websites and directory errors leave the outcome unverified. Neither an accessible site nor the existence of a listing establishes that a business is still operating.

Employees can record a direct confirmation with **I verified this business directly**, explaining how they checked. This saves the outcome, employee and timestamp. Closure/listing-change flags block pipeline conversion and reviewed outreach until resolved. An inconclusive recheck does not erase an earlier closure flag or direct confirmation. Existing Do Not Contact restrictions remain in effect. Public checks cannot guarantee real-world operating status; direct confirmation is the final step for unclear results. Google Places is not used, as requested.

## Validation

Run `.venv/bin/python manage.py test --noinput`. Targeted suites are `crm.test_outreach`, `crm.test_website_research` and `crm.test_business_status`. They cover reviewed edits, duplicate sending, access scope, OAuth state and encryption, SMS opt-outs and signed callbacks, request safety, evidence attribution, cached research, pipeline transfer and business-status restrictions.
