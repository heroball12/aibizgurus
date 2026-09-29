# Lead Finder website research and business verification

This release adds public website research and business operating-status checks. It requires no new API key, subscription, worker or dependency. The existing Render start command runs the two additive research migrations automatically.

## Dig deeper


Every Lead Finder result with a website has **Dig deeper**, also available on saved pipeline leads. It reads the homepage and up to two linked About, Contact or Services pages, respecting robots.txt. It saves public descriptions, contact details, headings, hours when present, and evidence for chat, booking and shopping/ordering tools. Existing contact fields are not overwritten. The report moves with a prospect into the pipeline.

Known AI embed code is distinguished from general chat integrations whose AI mode is unconfirmed. Custom AI-assistant links are reported as offered conversations, not tested agents. This is a bounded public-HTML scan, not a JavaScript browser. Cookie-gated, dynamically injected and sign-in-only tools can be missed. No checkout, appointment, form or conversation is operated. “No evidence found” never means a feature is definitely absent.

Network requests accept only HTTP/S and standard ports, reject credentials and private/reserved addresses, pin the validated address for the connection, check every redirect, validate TLS, cap response size, and use a time budget. There are no cookies or authenticated browsing. Each employee has 20 scans per hour; a row cannot be rescanned more than once in a 30-second window. Website research uses no additional API key.

## Is the business still operating?

New directory searches exclude explicit business lifecycle closures, vacant shops and past end dates, and report the excluded count. An old disused amenity does not suppress a different currently active business at the same site. Normal weekly hours and old COVID-hours exceptions are not interpreted as permanent closures.

**Check operating status → Check public sources** refreshes the exact OpenStreetMap record and scans the business website for prominent closure notices. A renamed listing or closure notice flags the prospect for review. Unavailable websites and directory errors leave the outcome unverified. Neither an accessible site nor the existence of a listing establishes that a business is still operating.

Employees can record a direct confirmation with **I verified this business directly**, explaining how they checked. This saves the outcome, employee and timestamp. Closure/listing-change flags block pipeline conversion until resolved. An inconclusive recheck does not erase an earlier closure flag or direct confirmation. Existing Do Not Contact restrictions remain in effect. Public checks cannot guarantee real-world operating status; direct confirmation is the final step for unclear results. Google Places is not used, as requested.

## Validation

Run `python manage.py test crm.test_website_research crm.test_business_status crm.test_lead_finder --noinput` for focused checks, or `python manage.py test --noinput` for the full suite. Tests cover evidence detection, unsafe URLs, private addresses, redirects, scan limits, ownership, cached research, pipeline transfer, closure filtering and direct employee verification.
