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
