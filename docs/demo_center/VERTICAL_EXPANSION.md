# Expansion after the Automotive field pilot

Keep the existing category demonstrations available. Do not seed superficial copies of the dealership logic into Cannabis, Med Spa, Insurance, Law, Home Services or Dental.

The reusable layer is `DemoExperience` + immutable revision + browser-isolated session + synthetic CRM + events/feedback/access/share/conversion. Automotive-specific filters, slots and policies live in `core/experience/tools.py` and its seed data. A second rich vertical should register its own validated tool schemas, seed content and domain policy and use the same session/permission/provider/analytics boundary. Generalize the route/registry at that point; there is no need to invent domain-specific empty records now.

- Cannabis: approved menu education/search, stock, preferences and a synthetic pickup workflow.
- Med Spa: treatment education, intake, consultation and reactivation; no diagnosis or guarantees.
- Insurance: qualified intake, appointment and renewal workflow; no underwriting decisions.
- Law: matter type/basic intake and handoff; no legal conclusions.
- Home Services: need/urgency, scheduling and escalation.
- Dental: administrative intake, scheduling/recall and human escalation.

## Future phone mode

The existing `voice` app serves real client/Twilio flows. Do not route synthetic demo phone calls into that real-client capture path. A dedicated demo number should resolve to a specific published DemoExperience, create an isolated demo session, and invoke these same tool services through a telephony adapter. Reuse Twilio signature validation and configured provider transport, add spoken demo/privacy disclosure, call-duration/spend limits, session identity and cleanup. Store no audio by default. Verify inbound numbers and webhook configuration with the owner before activation.

Phase 1 has no connected phone number, outbound SMS/email, dealer CRM or real scheduling integration. Those are future implementation choices, not hidden features in this demo. The conceptual channel section and rep guide state that feasibility depends on the customer's systems and build.
