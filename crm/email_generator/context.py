"""Bounded, source-labelled CRM evidence. Never performs external research."""
import re
from urllib.parse import urlsplit
from django.conf import settings
from django.urls import reverse
from django.db.models import Q
from crm.models import SalesProfile
from crm.sales import BOOKING_URL

SENSITIVE = re.compile(r'\b(?:password|passwd|api[_ -]?key|secret|access[_ -]?token|bearer|private note|internal.only|sensitive|confidential)\b|sk-[A-Za-z0-9_-]{12,}', re.I)
PRICE = re.compile(r'[$€£¥]|\b(?:pricing|price|discount|setup fee|monthly fee|USD|dollars?)\b', re.I)

def clean(value, limit=1200):
    # Drop the entire marked block rather than risk exporting a subsequent secret line.
    text = str(value or '')
    if SENSITIVE.search(text):
        return ''
    return '\n'.join(line for line in text.splitlines() if not PRICE.search(line))[:limit]

def safe_url(value):
    try:
        parts = urlsplit(value or '')
        return value if parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password else ''
    except ValueError:
        return ''

def sender_for(user):
    profile = SalesProfile.objects.filter(user=user).first()
    name = user.get_full_name().strip() or user.first_name or 'AI Business Gurus team'
    return {
        'name': profile.display_name if profile else name,
        'email': profile.business_email if profile else '',
        'signature': profile.signature() if profile else name + '\nAI Business Gurus',
        'approved_bio': clean(profile.approved_bio) if profile else '',
        'scheduling_url': safe_url(profile.scheduling_url) if profile else '',
    }

def links_for(lead, sender, options):
    links = {'demo': '', 'assessment': ''}
    base = safe_url(settings.PUBLIC_BASE_URL.rstrip('/'))
    if options['include_demo'] and base:
        try:
            from core.models import DemoExperience
            from core.demo_profiles import profiles
            industry = lead.industry.lower()
            auto = any(x in industry for x in ('auto', 'dealer', 'motor'))
            experience = DemoExperience.objects.filter(slug='automotive', published=True, public_access=True, current_revision__isnull=False).first() if auto else None
            if experience:
                links['demo'] = base + reverse('experience_home')
            elif any(x in industry for x in ('cannabis', 'dispensary')) and any(x['slug'] == 'cannabis' for x in profiles()):
                links['demo'] = base + reverse('demo') + '?industry=cannabis'
            else:
                links['demo'] = base + reverse('demo')
        except Exception:
            # A link lookup must not prevent an otherwise useful draft.
            links['demo'] = ''
    if options['include_assessment']:
        links['assessment'] = sender['scheduling_url'] or safe_url(BOOKING_URL)
    return links

def assemble(lead, user, options, services):
    sender = sender_for(user)
    brief = lead.assessment_brief if isinstance(lead.assessment_brief, dict) else {}
    notes = [{'source': 'CRM note', 'at': n.created_at.isoformat(), 'text': clean(n.note)} for n in lead.lead_notes.filter(is_sensitive=False).order_by('-created_at')[:6]]
    activity_query = lead.activities.filter(is_sensitive=False).exclude(raw_note__in=lead.lead_notes.filter(is_sensitive=True).values('note')).exclude(Q(metadata__has_key='sensitive') & Q(metadata__sensitive=True)).exclude(Q(metadata__has_key='internal_only') & Q(metadata__internal_only=True))
    if lead.notes_sensitive:
        activity_query = activity_query.exclude(Q(raw_note=lead.notes) | Q(cleaned_note=lead.cleaned_notes))
    activities = [{'source': a.activity_type, 'at': a.created_at.isoformat(), 'text': clean(a.cleaned_note or a.raw_note), 'contact': clean(a.contact_person,150)} for a in activity_query.order_by('-created_at')[:6]]
    sent = [{'subject':clean(m.subject,180),'body':clean(m.body,1800),'at':m.sent_at.isoformat() if m.sent_at else '', 'source':'Employee manually marked sent; not provider-verified'} for m in lead.outreach_messages.filter(status='marked_sent', generator_version__gt='').order_by('-sent_at')[:2]]
    research = {}
    if isinstance(lead.website_review, dict) and lead.website_review.get('website') == lead.website:
        # Only structured findings, never raw page HTML or arbitrary nested data.
        research = {k:clean(str(lead.website_review.get(k, '')),600) for k in ('details','findings','limitation')}
    context = {
        'identity': {'business':clean(lead.business_name or lead.name,200),'contact':clean(lead.point_of_contact,150), 'title':clean(lead.contact_role,120),'industry':clean(lead.industry,150),'website':lead.website,'location':clean(', '.join(x for x in (lead.city,lead.state) if x),200),'source':clean(lead.source,150)},
        'stage': lead.get_status_display(), 'next_follow_up':str(lead.next_follow_up_at or lead.follow_up_date or ''),
        'assessment_booked_at':str(lead.appointment_at or ''),
        'main_notes': '' if lead.notes_sensitive else clean(lead.cleaned_notes or lead.notes,2500),
        'recent_notes_newest_first':notes,'recent_activity_newest_first':activities,'previous_sent_emails':sent,
        'discovery':{k:clean(brief.get(k,''),600) for k in ('workflow','tools','bottleneck','goal')},
        'stored_public_research':research,
        'sender':{'name':sender['name'],'approved_bio':sender['approved_bio']},
        'selected_services':[{'id':s.slug,'name':s.name,'approved_description':s.description} for s in services],
        'employee_direction':clean(options['instructions'],1200),
        'email_type':options['email_type'], 'focus':options['focus'], 'tone':options['tone'], 'length':options['length'],
    }
    return context, sender, links_for(lead,sender,options)

def suggestions(lead):
    text = (' '.join([lead.industry, '' if lead.notes_sensitive else clean(lead.notes), *[clean(x) for x in lead.lead_notes.filter(is_sensitive=False).order_by('-created_at').values_list('note',flat=True)[:4]]])).lower()
    rules = [('receptionist',r'missed|after.hours|overflow|weekend','Notes mention call coverage or overflow.'),('reactivation',r'old(?:er)? (?:unsold )?leads|inactive|reactivat','Notes mention older leads or reactivation.'),('crm',r'crm|vinsolutions|hubspot|salesforce','CRM workflows appear in the lead context; compatibility still needs verification.'),('automotive',r'auto|dealer|bdc','Relevant to the automotive / BDC context.'),('budtender',r'cannabis|dispensary','Relevant to cannabis customer education and discovery.')]
    return [{'slug':slug,'reason':why} for slug,pattern,why in rules if re.search(pattern,text)]
