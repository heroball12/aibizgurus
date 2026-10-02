# Context assembly

Each request includes primary lead identity, industry, location, selected conversation/focus/services, at most six recent notes, six recent activities, two emails manually marked sent, a bounded main note, workflow/tools/bottleneck/goal fields, next follow-up and assessment date. Timestamped evidence is newest first. No valuation, pricing brief, unrelated lead/client, mailbox tokens or raw website HTML is sent.

Main notes have an email-context exclusion flag; individual notes and activities have `is_sensitive`. Adding a sensitive note copies its flag to its timeline activity. Matching duplicated main-note/activity content is excluded too. Obvious credential/private markers exclude whole text blocks; pricing-containing lines are removed. These filters supplement deliberate marking of sensitive notes. The setting excludes content from this generator; it does not alter permissions for viewing CRM notes or unrelated existing AI tools.

Stored website research can be included only when its recorded website matches the current lead website. It remains limited public-code evidence, not proof of missing capabilities. No website scraping occurs during generation.

Automotive selects `/demo/automotive/` only when the experience is published, public and has a revision. Cannabis resolves MaryJain from the existing public profile catalog. Other cases use the existing public `/demo/` hub. Missing/failed lookup omits a link. Scheduling uses a profile's approved HTTPS URL or the existing shared booking URL; disabling it retains a conversational CTA. No speculative coming-soon route is constructed.

User contact profiles contain only approved business signature fields and professional credibility. Without a profile, the full account name (or team label) and company name form the signature; a private login email is not copied automatically.
