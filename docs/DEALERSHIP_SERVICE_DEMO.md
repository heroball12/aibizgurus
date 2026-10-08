# Velocity Motors service department demo

The existing dealership experience now covers sales and service in the same isolated fictional customer session. Choose **Service** in the customer workspace, or **Explore the service department** from the hero.

## Demonstration flow

1. Speak or type to Axel about a fictional vehicle and service request. Axel gathers known vehicle/year, mileage, concerns, requested work, waiting/drop-off preference and customer contact details, one question at a time. Phone and email are optional.
2. Axel saves a numbered `DEMO-RO` service order and can open its prefilled review form. Customers can also open **Start service intake** themselves. The form works without an AI connection.
3. Pick a returned intake slot or save intake first and schedule through Axel later. Sales and service times are validated separately. An appointment is an intake time, not a promised repair completion time.
4. Follow **Open the service CRM**, then enter the simulated staff workspace. The service desk shows the same customer, vehicle, requested work, appointment and order.
5. Demonstrate scheduled → checked in → inspection → awaiting customer approval → work in progress → ready for pickup → closed. Unscheduled intake can check in as a walk-in. Assign a service advisor and technician and add fictional findings. Work cannot start without a technician, notes and explicit simulated customer approval. Cancellation is available before work begins.
6. Return to Axel and ask for service status. The status tool reads the saved order; the AI cannot independently approve or finish repairs. The customer panel also has **Refresh service status**.

## Data and access

- One active service order per demo prospect, linked to its existing `DemoCRMLead` snapshot. Start **New prospect** for the next presentation. Reset clears service data and activity along with the rest of that prospect's demo.
- No new production CRM models, real appointments, charges, emails or external dealer integrations. Existing sales, trade and financing demonstrations remain available.
- The public website and private iPad routes both use the same service implementation. Browser/session ownership, private employee access, CSRF, expiration and reset boundaries remain enforced.
- Advisor updates are audited. Session locks and optimistic order versions prevent conflicting customer/staff edits. Intake becomes read-only to the customer after check-in.
- Voice/text use the existing configured platform AI service; this checkout does not have a local platform AI key. Automated AI tests mock provider responses. A live spoken smoke test on the configured deployment is still needed.

## Deployment

Deploy the code and collected static assets normally. The service state uses the existing JSON session/snapshot fields; no service-specific schema migration is required.

The standard build runs `python manage.py seed_demo_center` to update stock content revisions 1.1/1.2 to `velocity-2026.1.3`, including the revised service scenario instructions/label. It preserves publication settings, manager-authored revisions and historical sessions. Run the same command manually if using a different deployment pipeline. The new tools and forms also work with existing content revisions.

## Verification

Backend coverage exercises customer form → linked appointment/order → staff progression → AI status readback, invalid input, wrong-department slots, duplicate saves, stale edits, cancellation, browser isolation, CSRF and reset. The existing sales, financing, voice/session and iPad tests run alongside it. Browser QA uses a fictional customer in an isolated preview database.
