# Velocity Motors

A fictional dealership with Axel as its AI Concierge. Public entry: `/demo/automotive/`. Internal management: `/demo/automotive/manage/`. Rep guide: `/demo/automotive/guide/`.

## The sales walkthrough

1. Rep signs in with their existing AIBG employee account, opens Automotive, and chooses a pain point in Demo controls.
2. Use Presentation mode. Ask the prospect to talk to Axel as they would a BDC representative.
3. “I need an SUV with three rows, AWD, under $50,000.” Inventory tools return actual matching synthetic stock; refine, ask about features, or compare two.
4. Add a trade: “2022 Accord, about 60,000 miles.” Axel captures known details and explains appraisal verification without creating a value. During intake, Axel asks for a name, phone and email; use fictional examples such as Taylor Demo, 202-555-0146 and taylor@example.com. Phone/email format validation does not verify ownership or deliverability.
5. Ask to see a vehicle tomorrow, choose one of the returned slots and agree to the demo booking.
6. Tap **Show dealership view → Enter the dealership CRM**. The demo staff sign-in represents Elena Rivera, fictional BDC Director. It is not a real dealership login and does not solicit a password.
7. Show the customer row, contact details, preferences, booking, trade, handoff, transcript and event timeline. Change the demo staff assignment, stage or notes to show the human continuation. Changes persist only in that fictional customer record.
8. Return to Axel or use the QR/share link. End with a real 15–20 minute Growth Assessment. Pricing is custom to the identified build and only AI Specialists discuss it during the assessment.
9. **New prospect** clears this session's conversation, trade, bookings, financing application and fictional CRM record. It does not alter the real CRM or other visitors.

### Financing handoff

Axel asks whether the shopper wants dealership financing, their own bank/credit union, or to pay in full. When the customer agrees, `open_demo_finance_application` opens a branded form in the conversation. It carries known contact details and the chosen stock; if no stock is supplied, a booked sales vehicle is used when available. The **Open demo financing application** button also demonstrates this deterministic workflow without requiring a live model.

The customer reviews their contact details, selects a vehicle or leaves it undecided, chooses a fixed fictional individual/self-employed/business profile, sample down payment and requested term, then clicks **Submit demo application**. Only a human form submission can mark it submitted; the AI has no submit tool. The fictional CRM shows the reference, contact and vehicle snapshot, sample financial information, a finance-team assignment and submission timeline. No approval or credit decision is generated. No SSN, birth date, bank account, uploaded document or free-entry income/employer field exists. Nothing goes to a lender, a credit bureau or an outbound provider.

Repeated submission is idempotent. Form updates cannot overwrite an in-flight conversation. A submitted application is a snapshot; later chat contact changes do not silently rewrite its submitted details. Opening it again shows its receipt. Start a new prospect to demonstrate another application.

A CRM page open in another tab in the same browser polls every eight seconds. New activity refreshes the record automatically unless staff has unsaved edits, in which case it offers Refresh. Separate browsers cannot open a session merely by copying its URL. A public share link always creates a fresh customer experience, preserving only rep/scenario attribution.

## Scenarios

- Vehicle shopping: discover needs, search and compare.
- Fresh internet lead: simulate a new inquiry; no real lead provider or outbound contact.
- After hours: scenario time 11:47 PM, staff offline, next-day slots and morning handoff.
- Trade-in: capture vehicle/mileage/condition/payoff when known, no valuation.
- Test drive: choose an available stock item and returned sales slot.
- Service: vehicle/year/request, service intake slots, no diagnosis or promised completion.
- Missed call: on-screen recovery example, no connected phone call.
- Reactivation: fictional Marcus, an F-150 inquiry 90 days ago; adapt to changed needs or stop if already purchased.
- Financing: purchase-plan discovery, approved FAQs, an optional fictional application and CRM handoff; no real credit application, SSN, approval, APR or binding payment quote.
- Inventory questions: verify available/pending/sold from synthetic data.

## Live pilot acceptance (requires real provider and device)

Try the 3–5 minute walkthrough in both Speak and Type; switch modes mid-conversation. Confirm quiet speech, normal pauses, explicit interruption, audio finish and typing pauses. Deny microphone access, lose/recover Wi-Fi, refresh, retry a request, open the fictional CRM during the conversation and reset for the next prospect. Check landscape and portrait on the physical iPad.

Also test: used F-150 availability after hours; service on Saturday vs closed Sunday; outside financing and Spanish staff; unavailable/unknown stock; no matches at an impossible budget; 'already bought' during reactivation; changing the old truck inquiry to a family SUV. Confirm no exact trade value or mechanical diagnosis and no claim of a real message being sent.

Automated tests cover deterministic behavior and mocked tool orchestration. They are not a substitute for live voice, model-grounding and real-network checks.
