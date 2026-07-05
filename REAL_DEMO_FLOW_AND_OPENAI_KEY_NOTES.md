# Real Demo Flow + OpenAI Key Setup

## OpenAI Key

Do not hardwire the real OpenAI key into source code.

Use `.env`:

```env
PLATFORM_OPENAI_API_KEY=your_real_openai_key_here
OPENAI_MODEL=gpt-4o-mini
```

Every client account uses the platform key by default.

Clients can override it later by adding their own OpenAI integration in the Integrations page.

## Real Demo Flow

The intended database-backed flow is:

```text
IndustryTemplate in DB
→ signup dropdown loads DB template
→ client selects industry
→ ClientAccount is created
→ AIInstance is created from that IndustryTemplate
→ widget uses that assistant greeting/system prompt/industry
```

## Verify

Run:

```bash
python manage.py seed_industries --clear
python manage.py verify_demo_flow --create-test
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/accounts/signup/
```

and verify all industries show in the dropdown.

## If you want to add the OpenAI key quickly

From the project folder:

```bash
nano .env
```

Then set:

```env
PLATFORM_OPENAI_API_KEY=your_real_key_here
```

Save, stop server, restart:

```bash
python manage.py runserver
```
