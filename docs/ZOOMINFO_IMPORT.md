# ZoomInfo company and contact imports

Open **Sales → Lead sheets → Upload**, or **Companies & people → Import ZoomInfo / CSV**. Upload a ZoomInfo PERSON CSV or XLSX export. The CRM detects its headers and opens a preview with new contacts, existing matches, repeated rows, protected assignments, and every source column. Confirm to save. Existing sales tracker uploads remain supported.

## Companies and people

Each business has a Company record. Each person retains an individual Lead record with their own notes, status, assignment, activity, and follow-up. The Companies & people directory has separate searchable tabs; opening a company lists its accessible contacts and sales records. A company’s spreadsheet and export shortcuts are restricted to that company.

ZoomInfo company IDs group contacts, and contact IDs identify people on repeat imports. Shared company names, websites, and HQ phone numbers never collapse different ZoomInfo contacts into one person. When a contact ID is absent, matching uses a conservative identity based on the person’s email/name and company.

Existing internal leads are grouped during migration by normalized business name, website domain, city, and state. Different spellings or incomplete legacy details can produce separate company records; the migration deliberately avoids guessing. New ordinary internal leads use the same grouping. Client-customer records are excluded. Employees see only contacts within their existing CRM access scope; owners and managers retain their broader access.

## Preserved information

- Every original exported column and cell is retained in the import activity, including unknown columns and blank values. Each contact has a grouped ZoomInfo source profile; the company profile contains company-level research.
- Direct, mobile, and HQ phone numbers stay separate. The working sales phone prefers direct, then mobile, then HQ. Contact and company locations remain separate.
- Revenue and funding retain their exported units and never become a CRM deal value.
- Re-imports fill missing CRM fields and refresh source information while preserving notes, nonempty contact fields, assignment, sales progress, archived status, and follow-ups. Blank cells do not erase earlier source details. Exported do-not-contact flags can strengthen an existing restriction.
- Imports create import activity, not call credit. Imported company certifications and contact accuracy scores are source claims, not live verification.
- The import report provides a source-column CSV download. Downloaded cells are protected against spreadsheet formula execution; this can add a leading apostrophe to values such as international phone numbers. Stored source cells remain unchanged.

## Limits and deployment

Uploads support the existing 5 MB limit and at most 2,500 rows. Preview data is server-owned, private to the uploader, and expires after 30 minutes. Confirmation rechecks matching and assignment permissions, uses a transaction, and is idempotent. Malformed rows, duplicate headers, and unlabeled populated columns stop the import instead of silently discarding data. XLSX files follow the same field mapping.

Apply migrations `0020_zoominfo_company_contacts` and `0021_group_existing_companies` before serving the new code. They depend on the earlier `0019_lead_batch_chain_filter` migration. The existing Render deployment runs migrations automatically. No ZoomInfo API key or plan change is needed for file imports.

Validation coverage is in `crm/test_zoominfo_import.py`; its fixtures are fictional. The supplied five-contact export was also checked in a rolled-back local transaction: all 73 columns and 365 cells were preserved, and a repeat import created no additional people.

## Live API search and Intent signals

The **ZoomInfo & intent** workspace adds explicit company search, people search, and buying-intent research. File import continues to work without API credentials.

Server settings:

- `ZOOMINFO_CLIENT_ID` and `ZOOMINFO_CLIENT_SECRET`: the Client Credentials app values, stored in Render Environment or a private local `.env`.
- `ZOOMINFO_ENABLED=1` (default); set `0` to disable provider calls while retaining saved records.
- Apply `0022_zoominfo_api_intent` before serving this feature. Render's existing migration command covers it.

No browser redirect URI, bearer-token environment variable, webhook, or Gmail connection is required. The server obtains short-lived tokens using HTTP Basic authentication and refreshes them as needed. Company/contact tokens request `api:data:company api:data:contact`; separate Intent tokens request `api:data:intent api:data:lookup`. The app's broader configured scopes are unchanged. Keeping tokens separate allows company/contact searches to work when Intent is not enabled. Token caches include a credential fingerprint, so changed credentials do not reuse old tokens.

Owners/managers can open **Connection & recent searches → Test connection**. Success confirms authentication and contact-field lookup only, not every field entitlement or Intent access. No contact details are purchased by that check. Credentials present is shown separately from a verified connection. The error panel shows the failed operation, HTTP status, bounded provider error codes/explanations, affected fields, support references, time, and a next step. It distinguishes local configuration, authentication, access, request/credit limits, invalid filters, network failures, and provider outages. Credentials, authorization values, echoed search values, email addresses, phone numbers and URLs are redacted from recognized error fields; arbitrary response bodies and headers are never dumped to the page or logs. Contact-detail failures retain these diagnostics with the private search, including across reloads. Other failures survive the redirect to their workspace. Apply `0023_zoominfo_error_details` with the other CRM migrations. A generic 403 is not presented as proof of a particular missing entitlement.

### Company → people → reviewed import

1. Search a business, state, industry, website or ZIP/radius. **Hide major chains** defaults on and removes known national brands from each returned page. It cannot prove that every remaining company is independently owned.
2. Choose **Find people** to prefill the exact ZoomInfo company ID. Person filters include name, title and seniority; location filters refer to company headquarters.
3. Select up to ten people and choose **Get details & preview import**. Search provides identity and availability hints; actual phone/email retrieval is a separate enrichment operation, which can consume credits. The screen discloses the selected count and potential credit usage.
4. Review and confirm through the same private import preview used for CSVs. Full raw search and enrichment records remain in the source profile, including fields without a dedicated CRM column. Company financial values retain API units rather than being reinterpreted as CSV thousands. Existing assignments, notes, restrictions, and pipeline progress remain protected by the shared importer.

Each result snapshot belongs to its searching employee. Search runs expire for new provider requests after 24 hours; previews expire after 30 minutes. Received enrichment responses can reopen an expired preview without another provider call. A transaction reserves the paid request before it is sent. Repeated clicks cannot charge again for that search. An ambiguous network/server failure locks that search against automatic paid retry; check ZoomInfo usage before intentionally starting a new search. A process failure after reservation also stays locked, rather than guessing whether the provider completed it.

The integration uses bounded network timeouts, one token refresh after an explicit 401, no automatic quota-consuming pagination, and shared database request budgets. Per employee: twelve searches/lookup checks per minute and twenty enrichment requests per hour. Account-wide CRM limits: forty searches/checks per minute and fifty enrichment requests per hour. Provider limits can be lower. A 403, timeout or 429 is shown as an error, never as a successful zero-result search. Local raw search/response snapshots remain until removed by an administrator; saved Intent signals retain their capture dates.

### Intent workflow

1. Open **Intent signals → Load ZoomInfo topics**. This reads the provider's topic catalog. Choose up to fifty real topics using the filterable selector.
2. Filter by signal dates, minimum score (60–100), industry, state, ZIP/radius and company employee count. The initial range is the last fourteen days, score 70 or higher. Results are ordered by newest signal date, with explicit pagination.
3. Each card shows company, topic/category, signal date (UTC), score and audience strength. **Save signal** retains that provider record once; multiple employees can save the same signal without duplicating it. Missing company IDs, dates or scores prevent attaching a misleading signal. Recommended contact names are never used to infer company identity.
4. **Saved intent signals** filters the team's saved research by company/topic, age and score. Employees see signals they saved or signals for companies they can access; owners/managers see all saved signals. Company profiles automatically show saved signals with the same ZoomInfo company ID, including companies imported later. The company directory can filter for signals from the last thirty days.
5. **Find people** starts a company-specific contact search. It does not retrieve paid details or create leads automatically.

Intent signals describe company-level content consumption relative to a historical baseline. They do not identify the person doing research, establish consent, confirm an inquiry, create call credit, change a lead stage, or justify claiming a prospect is ready to purchase. Audience A represents a larger research audience than E. Dates remain visible so old signals cannot masquerade as fresh activity.

This release uses manual Intent searches and saved snapshots. It does not activate webhook subscriptions, recurring background polling, automated outreach, or chargeable company-specific Intent enrichment. **Advanced plan membership alone does not establish API Intent access**: ZoomInfo requires the Intent SKU/API entitlement and relevant scopes. Search uses request and returned-record allowances even when it does not consume bulk enrichment credits.

Validation: `crm/test_zoominfo_api.py` covers provider request contracts, token renewal, strict ID matching, source preservation, private access, CSRF, duplicate/uncertain enrichment, Intent validation, late company matching and unchanged call activity. Browser QA uses an isolated database with explicitly fictional data. Account entitlement and real response verification must be performed on the deployed version using the existing Render credentials; no live ZoomInfo credits were used by local tests.

Official references: [Client Credentials](https://docs.gtm.ai/docs/client-credentials-flow), [Search Contacts](https://docs.gtm.ai/reference/searchinterface_searchcontact), [Enrich Contacts](https://docs.gtm.ai/reference/enrichinterface_enrichcontact), [Search Intent](https://docs.gtm.ai/reference/searchinterface_searchintent), [Lookup Data](https://docs.gtm.ai/reference/lookupinterface_lookup).
