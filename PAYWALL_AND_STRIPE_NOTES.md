# Paywall + Stripe Placeholder Patch

## Product Flow

- Public site remains free.
- Client signup remains free.
- Client receives a demo workspace and draft assistant.
- Full-version features remain visible but show locks.
- Clicking locked features takes the client to Billing.
- Billing shows Starter/Growth/Pro plans.
- Stripe checkout routes are wired but use placeholder keys/prices until real Stripe values are added.

## Locked Until Activation

Visible but locked:
- Live website embed publishing
- Full OpenAI-powered responses
- Voice AI calling
- SMS automation
- Lead alerts
- Production lead inbox
- CRM exports/conversation management

## Stripe Placeholder Values

`.env.example` includes:

```env
STRIPE_SECRET_KEY=sk_test_placeholder_replace_me
STRIPE_PRICE_STARTER=price_placeholder_starter
STRIPE_PRICE_GROWTH=price_placeholder_growth
STRIPE_PRICE_PRO=price_placeholder_pro
```

Replace these with real Stripe test/live values when ready.

## Manual Activation

For now, after a manual payment or test sale, activate a client in Django admin:

ClientAccount -> activation_status = active

That unlocks publishing and full-version UI.
