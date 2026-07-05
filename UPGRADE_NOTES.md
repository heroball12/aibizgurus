# Pre-Localhost Upgrade Notes

I upgraded the original starter project before your localhost test.

## Added Now

1. Encrypted Integration Credentials
- OpenAI, Twilio, Stripe, and other integration values are encrypted before save.
- Dashboard display masks credentials.

2. Lead Alerts
- New leads trigger a best-effort alert.
- If email is configured, it sends to `OWNER_ALERT_EMAIL` and the client contact email.
- If email is not configured, it logs the alert instead of breaking.

3. Rate Limiting
- The AI widget chat endpoint has a simple IP-based limit of 40 requests per minute per assistant.

4. Stripe Billing Placeholders
- Billing app added.
- Starter/Growth/Pro checkout routes added.
- Stripe webhook placeholder added.
- It will not break if Stripe is not configured.

5. Safer OpenAI Fallback
- If OpenAI fails or keys are missing, the assistant falls back to scripted lead-capture replies.

## Still Recommended Later

- Full Stripe webhook verification and subscription status syncing
- Stronger role/permission matrix
- Real production email service
- SMS owner alerts using Twilio outbound API
- Better analytics
- Real-time streaming voice AI
- Production security review
