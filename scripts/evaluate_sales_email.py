"""Synthetic evaluation in a disposable database. Default: context-only, zero API calls.
Run from the repo with .venv/bin/python scripts/evaluate_sales_email.py [--live].
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

CASES=[
 ('Automotive','Summit Valley Motors','Michael Carter','General Sales Manager','Spoke with Michael today. They have a six-person BDC. Fresh leads are handled well, but meaningful follow-up falls off after approximately 30 days. They have a large database of older unsold leads. Michael does NOT want AI replacing his BDC staff. He is interested in using AI to support the team and asked me to email information. They currently use VinSolutions, but integration compatibility has NOT been verified.',['reactivation','automotive','crm']),
 ('Cannabis','Violet Sample Dispensary','Alexis','Owner','Interested in customer-facing AI across phone, website and kiosk. E-commerce platform unknown. Asked for information. No medical advice requested.',['budtender','website_ai','receptionist']),
 ('Med spa','Harbor Sample Spa','Jordan','Manager','Weekend appointment requests wait until Monday. Staff wants help with administrative follow-up, not clinical questions. Scheduling platform unknown.',['lead_response','appointments']),
 ('Insurance','Example Harbor Insurance','Casey','Owner','Renewal follow-up is manual. A receptionist asked that this go to Casey. No conversation with Casey yet.',['reactivation','crm']),
 ('Law','Sample Legal Group','Morgan','Office manager','After-hours intake waits for the office to reopen. Wants human review for every legal question. No legal advice automation requested.',['receptionist','lead_response']),
 ('Home services','Example Climate Services','Jamie','Owner','Misses overflow calls when technicians are on jobs. Current dispatch software is unknown. Wants to keep the dispatch team.',['receptionist','operations']),
 ('Dental','Sample Bay Dental','Taylor','Practice manager','Recall list is worked manually. Wants administrative appointment help only. Asked about phone and website.',['reactivation','appointments']),
 ('Real estate','Sample Coast Realty','Avery','Broker','Older buyer inquiries get little follow-up. Does not want AI replacing agents. No CRM named.',['reactivation','lead_response']),
]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Make up to 32 real generation requests (plus one repair each) with the configured key.')
    parser.add_argument('--output',default='.local-artifacts/sales-email-evaluation.json')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));os.chdir(root)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    with tempfile.TemporaryDirectory(prefix='aibg-email-eval-') as temp:
        from django.conf import settings
        settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':str(Path(temp)/'evaluation.sqlite3')}}
        settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        settings.PUBLIC_BASE_URL='https://aibiz.guru'
        if args.live and not settings.PLATFORM_OPENAI_API_KEY:
            parser.error('No local platform OpenAI key is configured. Reuse the authorized key securely; never paste it in chat. No API calls made.')
        import django;django.setup()
        from django.core.management import call_command
        call_command('migrate',verbosity=0)
        from django.contrib.auth import get_user_model
        from crm.models import Lead,SalesProfile
        from core.models import DemoExperience,DemoRevision
        from crm.email_generator.forms import GenerationForm
        from crm.email_generator.context import assemble
        from crm.email_generator.service import generate,serialize
        from crm.email_generator.policy import EmailError
        e=DemoExperience.objects.create(slug='automotive',name='Synthetic published automotive demo',published=True)
        r=DemoRevision.objects.create(experience=e,version='eval-only',content={});e.current_revision=r;e.save()
        rows=[]
        for i,(industry,business,contact,title,notes,services) in enumerate(CASES):
            rep=get_user_model().objects.create_user(username=f'eval-{i}',first_name='Erykha' if i==0 else 'Sample Rep',role='employee')
            SalesProfile.objects.create(user=rep,display_name=rep.first_name,business_email=f'eval{i}@example.com',approved_bio='14 years in automotive and BDC' if i==0 else '')
            for kind in ['cold','decision_maker','gatekeeper','follow_up']:
                # Match the evidence to the selected conversation instead of manufacturing a contradiction.
                scenario=notes if kind=='decision_maker' else ('No prior conversation. Industry-specific possibilities only.' if kind=='cold' else ('Front desk asked us to send information to the contact. No conversation with the decision maker. '+notes.split('. ')[1] if kind=='gatekeeper' else 'Previous email was sent with relevant information. The next step is to review the workflow. '+notes))
                lead=Lead.objects.create(business_name=business,point_of_contact=contact,contact_role=title,industry=industry,notes=scenario,email=f'prospect{i}@example.com',assigned_to=rep)
                form=GenerationForm({'email_type':kind,'focus':'services','services':services,'include_demo':True,'include_assessment':True,'tone':'natural','length':'standard' if kind=='decision_maker' else 'short','instructions':''})
                assert form.is_valid(),form.errors
                row={'industry':industry,'type':kind,'mode':'live' if args.live else 'context-only','review_criteria':['facts grounded','specific pain prioritized','support employees','no invented integration','no pricing/guarantees','correct demo and assessment CTA','natural concise language']}
                if args.live:
                    try: row['draft']=serialize(generate(lead,rep,form.cleaned_data))
                    except EmailError as exc: row['error']={'message':str(exc),'code':exc.code}
                else:
                    data=form.cleaned_data.copy();data['email_type']=kind
                    row['context'],row['sender'],row['links']=assemble(lead,rep,data,list(data['services']))
                rows.append(row)
        destination=root/args.output;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(rows,indent=2))
        print(f'{len(rows)} synthetic scenarios written to {destination}. Mode: {"live" if args.live else "context-only; no AI output generated"}. Temporary database discarded.')
if __name__=='__main__': main()
