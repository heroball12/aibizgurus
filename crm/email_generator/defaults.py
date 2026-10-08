COMPANY = 'AI Business Gurus builds AI, automation, custom software and technology solutions around how a business actually operates. Start with the business problem, support its team, and identify an appropriate solution.'
ASSESSMENT = 'A complimentary Growth Assessment with an AI Specialist, available virtually or in person in Temecula, to understand current operations, identify bottlenecks and evaluate relevant AI/software opportunities and an implementation approach.'
TYPES = [
 ('cold', 'Cold email', 'No prior conversation or request for information may be implied. Introduce yourself, establish relevance without claiming an unobserved problem, and earn a conversation.', 'short'),
 ('decision_maker', 'Decision maker — requested information', 'A conversation with the decision maker occurred. Prioritize recent call notes and the specific request. Briefly acknowledge that conversation; do not turn this into a brochure.', 'standard'),
 ('gatekeeper', 'Gatekeeper — requested information', 'Spoke with a gatekeeper, NOT necessarily this recipient. Make it easy to forward. Use only known names. Never imply the decision maker spoke with us or the gatekeeper endorsed AIBG.', 'short'),
 ('follow_up', 'Follow-up', 'Review previous SENT emails and activities, find a useful reason to reconnect and move to a specific next step. Drafts are not sent messages. Avoid an empty just-checking-in email.', 'short'),
]
SERVICES = [
 ('outbound', 'Outbound cold calling AI', 'Outbound calling, qualification, database outreach, follow-up, appointments and reactivation where appropriate. Do not promise unrestricted automated cold calling or legal compliance.'),
 ('receptionist', 'Receptionist / intake phone AI', 'Answer calls, after-hours and overflow coverage, FAQs, intake, qualification, routing, appointments and human escalation. Support employees rather than replace them.'),
 ('lead_response', 'Lead response & follow-up AI', 'Respond to leads, qualify, nurture, organize CRM follow-up and support longer-term conversations.'),
 ('appointments', 'Appointment setting AI', 'Qualification, availability, scheduling, rescheduling, confirmations, reminders and handoff. Calendar integrations require verification.'),
 ('customer_service', 'Customer service AI', 'Common questions, order or service information, routing, basic troubleshooting, status requests and human escalation.'),
 ('reactivation', 'Customer reactivation AI', 'Re-engage older unsold leads, past customers, inactive databases and renewal opportunities. Never guarantee conversions.'),
 ('operations', 'Operations automation AI', 'Repetitive administration, data movement, internal workflows, notifications, documents, task routing and employee support.'),
 ('crm', 'CRM automation & integration', 'Lead routing, follow-up, activity logging, data synchronization, pipeline reporting and customer lifecycle workflows. Compatibility depends on verified system/API access.'),
 ('website_ai', 'Website AI / customer concierge', 'Website conversations, service and product questions, qualification, recommendations, appointment assistance, support and routing.'),
 ('knowledge', 'Internal AI employee / knowledge assistant', 'Employee questions, approved company knowledge, procedures, internal search, training and operational assistance.'),
 ('budtender', 'AI Budtender', 'Cannabis product discovery, menu navigation, product education, FAQs, availability, preferences and ordering assistance across phone, website or kiosk. No medical claims or unverified commerce integrations.'),
 ('automotive', 'Automotive AI / BDC automation', 'Internet leads, inventory questions, vehicle discovery, qualification, test drives, trade intake, after-hours, service scheduling, reactivation and BDC handoff. No unverified CRM or DMS compatibility claims.'),
 ('software', 'Custom software development', 'Custom business applications, internal systems, workflow software, client portals, management systems and specialized tools.'),
 ('apps', 'Web / mobile applications', 'Customer-facing or internal applications, mobile applications, SaaS, portals and dashboards.'),
 ('websites', 'Website development', 'Custom business websites, conversion-focused experiences, e-commerce and integrated customer experiences. Avoid generic marketing claims.'),
 ('business_software', 'Business management software', 'Internal operations, employee and customer management, workflow management, reporting and appropriate financial/admin workflows.'),
 ('custom_ai', 'Custom AI solution', 'Custom AI and software systems designed around business workflows when the opportunity does not fit another category.'),
]

def seed(apps=None):
    if apps:
        Config = apps.get_model('crm', 'SalesEmailConfig')
        Type = apps.get_model('crm', 'SalesEmailType')
        Service = apps.get_model('crm', 'SalesEmailService')
    else:
        from crm.models import SalesEmailConfig as Config, SalesEmailType as Type, SalesEmailService as Service
    Config.objects.get_or_create(pk=1, defaults={'company_description': COMPANY, 'assessment_description': ASSESSMENT, 'forbidden_claims': 'guaranteed ROI\nguaranteed revenue\nguaranteed savings\nseamlessly integrates'})
    for i, (slug, name, guidance, length) in enumerate(TYPES):
        Type.objects.get_or_create(slug=slug, defaults={'name':name,'guidance':guidance,'default_length':length,'position':i})
    for i, (slug, name, description) in enumerate(SERVICES):
        Service.objects.get_or_create(slug=slug, defaults={'name':name,'description':description,'position':i})
