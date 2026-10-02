# Experience Center verification — October 1, 2026

## Automated checks

- 45 Experience Center Django tests pass, including a mocked AI conversation → offered slot → confirmed demo booking → customer in the fictional CRM → staff sign-in workflow.
- 336 Django tests pass in an isolated release snapshot containing the existing application, pending employee dashboard and Experience Center, with the paused AI outreach feature excluded.
- Seven new microphone lifecycle tests pass: quiet input, silence, cancellation, delayed permission, maximum duration, permission denial and microphone release before output audio.
- The existing 49 concierge/sheet frontend tests passed during this implementation. Existing Guru transport and demo character behavior are unchanged.
- JavaScript syntax, Django system checks, migration drift and diff whitespace checks pass.

Contact/financing tests also cover format validation, human-only submission, offered-vehicle association, fixed sample financial data, unknown-field rejection, consent notice, duplicate submission, simultaneous chat writes, pinned content, cross-session access, CSRF, expiry and reset.

Provider calls in automated tests are mocked. They verify the integration contract and state changes, not live model quality, generated speech, provider compatibility or real network latency.

## Browser checks

Checked the original showroom visuals, inventory cards, handoff, fictional CRM sign-in and customer detail, manager dashboard, scenario controls and responsive layouts. Tested 1194×834 landscape, 834×1194 portrait and 390×844 phone viewports. Presentation mode keeps the input and primary controls on screen in the landscape viewport. The phone view has no document-level horizontal overflow.

The CRM visual check used an explicitly labelled fictional developer fixture, not a claimed live AI conversation. The fixture was cleared afterward. No real CRM leads, customer appointments or outbound communications were created by that check. The financing follow-up was also exercised in the browser: open form, invalid-phone feedback without losing other inputs, sample company profile selection, submission receipt, fictional staff sign-in, and the saved phone/email, selected stock, application details and activity in the CRM. The form was checked at a 390×844 phone viewport as well as desktop size.

## Remaining live acceptance

This checkout has no local OpenAI key. Reuse the existing Render OpenAI configuration after deployment, or add that same authorized configuration locally. Follow the live walkthrough in `AUTOMOTIVE_DEMO.md`, including voice/text transitions and the real iPad microphone, speaker and network checks. Browser viewport checks do not substitute for Safari hardware testing. Do not mark the field pilot live-verified until those checks pass.

The feature has not been committed, pushed or deployed by this implementation. Deployment and seed commands are in `ARCHITECTURE.md`. The fictional CRM is session-scoped; it does not connect to an outside dealer CRM or create production dealership accounts.
