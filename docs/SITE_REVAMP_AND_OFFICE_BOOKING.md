# Product navigation and office booking

The public site now has two clear product entries: **Meet your AI employee** opens the video/voice team demos; **Website chatbots** opens the industry template catalog. Existing industry slugs, demo signup, private conversations, captured inquiries, dealership intake/CRM and Guru handoffs remain in place. The customer workspace emphasizes website chat; existing paid publishing/integration routes remain available under Publishing & account.

The public pricing page directs visitors to an AI Specialist for custom pricing during a Growth Assessment. The default sales email description is updated only when it still exactly matches the old seeded text; owner-customized messaging is preserved.

## Media

`static/video/guru-welcome.mp4` is a new 10-second Runway-generated welcome film based on the existing approved `guru-helmet.jpg` character. Runway task: `aba45d2b-927f-4086-b832-44aae50e95a7`. Delivered at 1280×720, optimized to approximately 1.7 MB with H.264, yuv420p and fast-start metadata. It is intentionally silent and uses explicit playback controls. Guru's live voice, avatar and the existing rooftop film/audio are unchanged. Its helmet stays sealed with a violet visor; generated frames at 3 and 9 seconds were visually checked.

## Deploy

Run the standard deployment including `python manage.py migrate` and `python manage.py collectstatic --noinput`. Core migrations 0005/0006 create office booking tables and seed the approved schedule. CRM migration 0018 refreshes unchanged default assessment copy. The new video is a small included static asset, not part of the private training-video disk bundle.

The initial schedule is Monday–Friday, 9 AM–5 PM, America/Los_Angeles; appointments are 30 minutes with a 30-minute buffer. The last slot starts at 4 PM so its buffer ends by 5 PM. Minimum notice defaults to two hours and bookings open 60 days ahead. These controls, holidays/time off, cancellation and notification retries are owner-only at `/owner/calendar/`.

A confirmed booking creates an owner calendar entry, ConsultationRequest, internal CRM appointment and activity. Signed sales attribution is preserved; the booking counts as an assessment, not as a rep's call. Reservation and availability mutations lock the shared schedule row on PostgreSQL. Repeated submission tokens do not create another appointment. Customer confirmation URLs are signed, unlisted and marked no-store/noindex.

Virtual assessment booking is the default public path. In-person scheduling remains available through a small secondary link and the contact footer; the homepage has no dedicated office promotion. Guru offers virtual first and mentions office visits when relevant to the visitor.

## Owner notifications

Notifications go to **james@aibiz.guru**, configurable in the owner calendar. The owner dashboard also displays unread bookings. The customer receives confirmation plus an ICS calendar attachment. Failed mail stays pending with a visible retry action; the reservation remains confirmed.

Use the existing Render mail provider with a verified sender. Required SMTP settings, if using Django SMTP:

- `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- Correct `EMAIL_USE_TLS` / `EMAIL_USE_SSL` values for the provider
- `DEFAULT_FROM_EMAIL` set to the provider's verified company sender
- `PUBLIC_BASE_URL=https://aibiz.guru`

Credentials belong only in Render environment settings, never in Git. Production email settings were not verified in this local work. Local browser checks used an in-memory backend and sent no real emails. Provider acceptance does not prove inbox delivery; verify one real booking after deployment.

Retry pending notifications manually in the owner calendar or run:

```sh
python manage.py deliver_office_booking_emails --limit 20
```

This command can be scheduled by the deployment operator if automatic retries are desired. No scheduler or external calendar connection is installed by this change.

## Calendar boundary

Virtual booking continues through `https://calendly.com/james-aibiz/30min`. Office availability excludes confirmed office appointments, blocked time, and recorded CRM/Calendly assessments. It does not query Google Calendar. Office bookings do **not** write busy events back to Calendly. Use distinct virtual hours or block conflicting time in Calendly to avoid a later virtual booking overlapping an office visit. The website owner calendar is the requested destination.

## Verification

Local tests cover reservation/idempotency, buffers, weekends/DST, competing reservations, cancellations, mail failures/retry, signed attribution, owner permissions and private chatbot intake/inbox isolation. Existing sales, Calendly, email draft, Guru, demo and dealership tests were also exercised. Browser verification used only fictional customer details in a separate preview database. Live microphones and production mail require a real-device check after deployment. Desktop and 390-pixel mobile layouts were checked in the browser, including the mobile menu, landing page and industry catalog. Actual microphone behavior still needs a real-device check.
