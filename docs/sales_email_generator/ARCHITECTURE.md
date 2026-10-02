# Sales email copilot

Phase 1 replaces direct outreach with generate → review/edit → copy → optionally save → manually mark sent. All production `/crm/outreach/` transport/OAuth endpoints return 410, including direct POSTs. Dormant transport code and encrypted mailbox tables remain for a later explicit project; no sending feature flag exists in this phase.

The feature extends `OutreachMessage` rather than introducing another draft store. Original model output remains immutable in `original_output`; edited body, subject and signature are separate. Each regeneration creates a new row linked through `parent`. Status `marked_sent` means an employee assertion, not provider-confirmed delivery. Existing transport statuses remain backward compatible.

- `crm/email_models.py`: database configuration, types, services and approved sales profiles.
- `crm/email_generator/context.py`: bounded CRM evidence and actual public links.
- `policy.py`: immutable baseline prompt and deterministic output checks.
- `service.py`: existing `PlatformAIService`, one corrective validation retry, persistence and activity events.
- `forms.py`, `views.py`: validated inputs, ownership, CSRF, row locks and manager configuration.
- `static/js/sales-email.js`: draft editor, refinement, browser recovery, serialized autosave and optimistic revisions.

Uses existing lead permissions, `LeadNote`, `LeadActivity`, `ActivityLog`, `UsageRecord`, request budgets, published `DemoExperience`, legacy demo profiles and `crm.sales.BOOKING_URL`. CRM currently has one primary recipient per lead; no multi-contact subsystem is invented. Email may be empty. `Lead.name` is not assumed to be the contact because imports also use it for business names.

Migration `0013_sales_email_copilot` follows the previously uncommitted outreach migration `0012_salessmscontact_salessmsreply_outreachmessage_and_more`, which itself depends on existing `0014_lead_business_verification_and_more`. Django uses dependencies, not numeric filename order. Keep that graph intact; do not fake or rename migrations already applied locally. Migration seeds all defaults. `python manage.py seed_sales_email` restores missing defaults without overwriting approved edits.

Deploy through the normal Render Git workflow and run migrations. Reuses Render's existing platform OpenAI configuration; Gmail OAuth and SMS credentials are unnecessary. This change does not deploy itself. No synthetic evaluation lead belongs in the production database.
