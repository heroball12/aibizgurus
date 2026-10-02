import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from crm.models import Lead, LeadNote, LeadActivity, OutreachMessage, SalesEmailConfig, SalesEmailService, SalesEmailType, SalesProfile
from crm.email_generator.defaults import seed
from crm.email_generator.context import assemble, links_for, sender_for, suggestions
from crm.email_generator.forms import GenerationForm
from crm.email_generator.policy import EmailError, validate_text
from crm.email_generator.service import VERSION
from core.models import DemoExperience, DemoRevision
from audit.models import ActivityLog

NOTES='Spoke with Michael today. They have a six-person BDC. Fresh leads are handled well, but meaningful follow-up falls off after approximately 30 days. They have a large database of older unsold leads. Michael does NOT want AI replacing his BDC staff. He is interested in using AI to support the team and asked me to email information. They currently use VinSolutions, but integration compatibility has NOT been verified.'

@override_settings(PUBLIC_BASE_URL='https://aibiz.guru',EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SalesEmailTests(TestCase):
    def setUp(self):
        seed()
        User=get_user_model()
        self.rep=User.objects.create_user(username='email-erykha',first_name='Erykha',last_name='Demo',role='employee')
        self.other=User.objects.create_user(username='email-other',role='employee')
        self.owner=User.objects.create_user(username='email-owner',role='owner')
        self.lead=Lead.objects.create(business_name='Summit Valley Motors',point_of_contact='Michael Carter',contact_role='General Sales Manager',industry='Automotive',email='michael@example.com',notes=NOTES,assigned_to=self.rep)
        SalesProfile.objects.create(user=self.rep,display_name='Erykha Demo',business_email='erykha@example.com',approved_bio='14 years of automotive and BDC experience')
        self.experience=DemoExperience.objects.create(slug='automotive',name='Automotive',published=True)
        revision=DemoRevision.objects.create(experience=self.experience,version='email-test',content={})
        self.experience.current_revision=revision;self.experience.save()
        self.client.force_login(self.rep)
        self.data={'email_type':'decision_maker','focus':'services','services':['reactivation','automotive','crm'],'include_demo':True,'include_assessment':True,'tone':'natural','length':'standard','instructions':''}
        self.output={'subjects':['Following up on older BDC leads','A next step for Summit Valley Motors','Supporting your BDC follow-up'],'body':'Hi Michael,\n\nGreat speaking with you today. Based on what you shared, the opportunity is following up with older unsold leads while supporting your six-person BDC. AI could help maintain those conversations and hand interested prospects back to your team. We would first evaluate the CRM workflow and verify compatibility.\n\nYou can try our automotive demo here: https://aibiz.guru/demo/automotive/\n\nWould a complimentary 15–20 minute Growth Assessment with an AI Specialist be useful to review that workflow? https://calendly.com/theaibizguru/15-minute-intro-to-ai','services_referenced':['reactivation','automotive','crm']}
    def post(self,name,data,args=None,client=None):
        return (client or self.client).post(reverse(name,args=args or [self.lead.pk]),json.dumps(data),content_type='application/json')
    def generate(self,output=None,data=None):
        with patch('crm.email_generator.service.PlatformAIService.structured_json',return_value=(output or self.output,{'status':'success'})) as model:
            response=self.post('sales_email_generate',data or self.data)
        return response,model
    def action(self,draft,action,**extra):
        return self.post('sales_email_action',{'action':action,'revision':draft['revision'],**extra},[self.lead.pk,draft['id']])
    def test_acceptance_dealership_entire_review_workflow(self):
        response,model=self.generate(); self.assertEqual(response.status_code,200,response.content)
        draft=response.json()['draft']; self.assertIn('Erykha Demo',draft['signature'])
        prompt=model.call_args.kwargs['messages'][1]['content']
        for fact in ['six-person BDC','older unsold leads','VinSolutions','NOT been verified','14 years']:
            self.assertIn(fact,prompt)
        for action in ['copy_all','save','sent']:
            response=self.action(draft,action); self.assertEqual(response.status_code,200,response.content);draft=response.json()['draft']
        self.assertEqual(draft['status'],'marked_sent')
        self.assertEqual(LeadActivity.objects.filter(lead=self.lead,activity_type='email').count(),1)
        self.assertFalse(LeadActivity.objects.get(lead=self.lead).metadata['delivery_verified'])
        response=self.action(draft,'sent');self.assertEqual(response.status_code,200)
        self.assertEqual(LeadActivity.objects.filter(lead=self.lead).count(),1)
        self.assertEqual(self.client.get(reverse('sales_email',args=[self.lead.pk])).status_code,200)
    def test_all_four_types_and_general_single_multiple_services(self):
        for kind in ['cold','decision_maker','gatekeeper','follow_up']:
            for service_ids in [[],['reactivation'],['reactivation','crm']]:
                with self.subTest(kind=kind,services=service_ids):
                    output={**self.output,'body':self.output['body'].replace('Great speaking with you today. Based on what you shared,','One area to explore:'),'services_referenced':service_ids}
                    response,_=self.generate(output,{**self.data,'email_type':kind,'focus':'services' if service_ids else 'general','services':service_ids})
                    self.assertEqual(response.status_code,200,response.content)
    def test_focus_validation_and_disabled_services(self):
        for fields in [{'focus':'general'},{'services':[]},{'services':['unknown']}]:
            response,model=self.generate(data={**self.data,**fields});self.assertEqual(response.status_code,400);model.assert_not_called()
        SalesEmailService.objects.filter(pk='crm').update(enabled=False)
        self.assertEqual(self.generate()[0].status_code,400)
    def test_no_email_contact_or_notes_does_not_block(self):
        self.lead.email='';self.lead.point_of_contact='';self.lead.notes='';self.lead.save()
        response,_=self.generate();self.assertEqual(response.status_code,200)
        self.assertContains(self.client.get(reverse('sales_email',args=[self.lead.pk])),'No email address on file')
    def test_notes_privacy_and_bounded_context(self):
        LeadNote.objects.create(lead=self.lead,note='DO NOT EXPORT',is_sensitive=True)
        LeadNote.objects.create(lead=self.lead,note='password: SECRET\naccount login here')
        LeadActivity.objects.create(lead=self.lead,raw_note='PRIVATE ACTIVITY',is_sensitive=True)
        self.lead.notes_sensitive=True;self.lead.save()
        form=GenerationForm(self.data);self.assertTrue(form.is_valid())
        context,_,_=assemble(self.lead,self.rep,form.cleaned_data|{'email_type':'decision_maker'},list(form.cleaned_data['services']))
        encoded=json.dumps(context)
        for word in ['DO NOT EXPORT','SECRET','PRIVATE ACTIVITY','VinSolutions']:self.assertNotIn(word,encoded)
    def test_only_sent_emails_are_conversation_evidence(self):
        d=self.generate()[0].json()['draft']
        _,model=self.generate()
        self.assertNotIn(self.output['subjects'][0],model.call_args.kwargs['messages'][1]['content'])
        self.action(d,'sent')
        _,model=self.generate()
        self.assertIn(self.output['subjects'][0],model.call_args.kwargs['messages'][1]['content'])
    def test_pricing_retries_once_then_safe_error(self):
        bad={**self.output,'body':self.output['body']+'\nSetup fee is $2,500.'}
        with patch('crm.email_generator.service.PlatformAIService.structured_json',side_effect=[(bad,{'status':'success'}),(self.output,{'status':'success'})]) as model:
            response=self.post('sales_email_generate',self.data)
        self.assertEqual(response.status_code,200);self.assertEqual(model.call_count,2)
        response,model=self.generate(bad);self.assertEqual(response.status_code,422);self.assertEqual(model.call_count,2)
        self.assertNotIn('$2,500',response.content.decode())
        self.assertTrue(ActivityLog.objects.filter(message='EMAIL_VALIDATION_FAILED').exists())
    def test_prohibited_claims_integrations_urls_and_malformed_output(self):
        for extra in ['Guaranteed ROI.','We integrate with VinSolutions.','Try https://fake.example/demo/','We offer a discount.','We replace your BDC staff.','<script>alert(1)</script>']:
            with self.subTest(extra=extra):
                response,model=self.generate({**self.output,'body':self.output['body']+'\n'+extra})
                self.assertEqual(response.status_code,422,response.content)
                self.assertEqual(model.call_count,2)
        response,_=self.generate({'body':'bad'});self.assertEqual(response.status_code,422)
    def test_unrelated_numbers_allowed(self):
        validate_text(['Follow up'],'3 locations, 24/7 coverage and a 15–20 minute Growth Assessment.','Erykha',links={})
    def test_cold_prior_conversation_rejected(self):
        self.assertEqual(self.generate(data={**self.data,'email_type':'cold'})[0].status_code,422)
    def test_demo_selection_and_unpublished_fallback(self):
        links=links_for(self.lead,sender_for(self.rep),self.data)
        self.assertEqual(links['demo'],'https://aibiz.guru/demo/automotive/')
        self.experience.published=False;self.experience.save()
        self.assertEqual(links_for(self.lead,sender_for(self.rep),self.data)['demo'],'https://aibiz.guru/demo/')
        self.lead.industry='Cannabis dispensary'
        self.assertEqual(links_for(self.lead,sender_for(self.rep),self.data)['demo'],'https://aibiz.guru/demo/?industry=cannabis')
    def test_lookup_failure_omits_link(self):
        with patch('core.models.DemoExperience.objects.filter',side_effect=RuntimeError):
            self.assertEqual(links_for(self.lead,sender_for(self.rep),self.data)['demo'],'')
        with override_settings(PUBLIC_BASE_URL=''):
            self.assertEqual(links_for(self.lead,sender_for(self.rep),self.data)['demo'],'')
    def test_scheduling_link_and_disable_options(self):
        profile=SalesProfile.objects.get(user=self.rep);profile.scheduling_url='https://example.com/erykha';profile.save()
        self.assertEqual(links_for(self.lead,sender_for(self.rep),self.data)['assessment'],profile.scheduling_url)
        links=links_for(self.lead,sender_for(self.rep),self.data|{'include_demo':False,'include_assessment':False})
        self.assertEqual(links,{'demo':'','assessment':''})
    @override_settings(PUBLIC_BASE_URL='https://www.aibiz.guru')
    def test_approved_www_demo_link_can_generate_save_and_copy(self):
        output=self.output|{'body':self.output['body'].replace('https://aibiz.guru/demo/automotive/','https://www.aibiz.guru/demo/automotive/')}
        response,_=self.generate(output)
        self.assertEqual(response.status_code,200,response.content)
        draft=response.json()['draft']
        draft=self.action(draft,'save').json()['draft']
        self.assertEqual(self.action(draft,'copy_all').status_code,200)
    def test_www_fix_still_rejects_unapproved_and_bare_links(self):
        approved='https://www.aibiz.guru/demo/'
        for link in ['www.aibiz.guru/demo/','https://www.evil.example/','https://www.aibiz.guru/demo/unapproved','javascript:alert(1)']:
            with self.subTest(link=link),self.assertRaises(EmailError):
                validate_text(['An introduction'],'Try '+link,'AI Business Gurus',links={'demo':approved})
    def test_scope_all_endpoints_and_draft_owner(self):
        d=self.generate()[0].json()['draft']
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('sales_email',args=[self.lead.pk])).status_code,404)
        self.assertEqual(self.generate()[0].status_code,404)
        self.assertEqual(self.action(d,'copy_all').status_code,404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('sales_email',args=[self.lead.pk])).status_code,200)
        self.assertEqual(self.action(d,'sent').status_code,403)
    def test_csrf_and_non_employee(self):
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.rep)
        self.assertEqual(self.post('sales_email_generate',self.data,client=strict).status_code,403)
        self.rep.role='client';self.rep.save()
        self.assertEqual(self.generate()[0].status_code,302)
    def test_archived_do_not_contact_and_disabled_config(self):
        self.lead.status='do_not_contact';self.lead.save();response,model=self.generate();self.assertEqual(response.status_code,403);model.assert_not_called()
        self.lead.status='new';self.lead.save();SalesEmailConfig.objects.filter(pk=1).update(enabled=False)
        self.assertEqual(self.generate()[0].status_code,403)
    def test_autosave_policy_copy_validation_and_conflict(self):
        d=self.generate()[0].json()['draft']
        response=self.action(d,'edit',body='Edited $999 draft');self.assertEqual(response.status_code,200)
        self.assertEqual(self.action(d,'save').status_code,409)
        d=response.json()['draft'];self.assertEqual(self.action(d,'copy_all').status_code,400)
        d=self.action(d,'edit',body=self.output['body']).json()['draft']
        self.assertEqual(self.action(d,'save').status_code,200)
    def test_regeneration_preserves_saved_version(self):
        d=self.generate()[0].json()['draft'];d=self.action(d,'save',body=self.output['body']+'\nWould Tuesday work?').json()['draft']
        result,_=self.generate(data=self.data|{'parent':d['id']})
        self.assertEqual(result.status_code,200);self.assertNotEqual(d['id'],result.json()['draft']['id'])
        self.assertTrue(OutreachMessage.objects.get(pk=d['id']).body.endswith('Would Tuesday work?'))
    def test_feedback_and_discard(self):
        d=self.generate()[0].json()['draft'];d=self.action(d,'feedback',feedback='needs_work',feedback_reason='Too generic').json()['draft']
        self.assertEqual(d['feedback'],'needs_work')
        d=self.action(d,'discard').json()['draft'];self.assertEqual(self.action(d,'sent').status_code,409)
    def test_provider_failure_safe_and_no_draft(self):
        with patch('crm.email_generator.service.PlatformAIService.structured_json',return_value=({}, {'status':'error'})):
            response=self.post('sales_email_generate',self.data)
        self.assertEqual(response.status_code,503);self.assertEqual(OutreachMessage.objects.count(),0)
    @override_settings(SALES_EMAIL_MODEL='gpt-5-mini', OPENAI_CHAT_MODEL='gpt-4o-mini')
    def test_email_uses_its_configured_model_and_existing_platform_key(self):
        response,provider=self.generate()
        self.assertEqual(response.status_code,200)
        self.assertEqual(provider.call_args.kwargs['model'],'gpt-5-mini')
        self.assertEqual(OutreachMessage.objects.get().generator_model,'gpt-5-mini')
    def test_structured_output_constrains_selected_and_general_service_references(self):
        _,provider=self.generate()
        schema=provider.call_args.kwargs['json_schema']
        self.assertEqual(schema['properties']['services_referenced']['items']['enum'],self.data['services'])
        self.assertFalse(schema['additionalProperties'])
        output=self.output|{'services_referenced':[]}
        response,provider=self.generate(output=output,data=self.data|{'focus':'general','services':[]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(provider.call_args.kwargs['json_schema']['properties']['services_referenced']['maxItems'],0)
        self.assertEqual(json.loads(provider.call_args.kwargs['schema_hint'])['services_referenced'],[])
    def test_provider_failures_explain_the_required_action(self):
        cases = [
            ({'reason':'PermissionDeniedError','category':'model_access'}, 'ai_model_access', 'model access'),
            ({'reason':'PermissionDeniedError'}, 'ai_permission', 'permissions'),
            ({'reason':'missing_api_key'}, 'ai_configuration', 'not configured'),
            ({'reason':'AuthenticationError'}, 'ai_authentication', 'API key'),
            ({'category':'quota'}, 'ai_quota', 'credit or spending limit'),
            ({'reason':'daily_limit'}, 'ai_daily_limit', 'daily AI allowance'),
            ({'reason':'APITimeoutError'}, 'ai_timeout', 'too long'),
            ({'reason':'RateLimitError'}, 'ai_rate_limit', 'temporarily limiting'),
        ]
        for meta, code, explanation in cases:
            with self.subTest(code=code), patch('crm.email_generator.service.PlatformAIService.structured_json',return_value=({}, {'status':'error', **meta})) as provider:
                response=self.post('sales_email_generate',self.data)
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json()['code'],code)
            self.assertIn(explanation,response.json()['error'])
            self.assertEqual(provider.call_count,1)
        self.assertFalse(OutreachMessage.objects.exists())
    def test_service_suggestions_and_profile_fallback(self):
        self.assertIn('reactivation',[x['slug'] for x in suggestions(self.lead)])
        self.assertIn('14 years',sender_for(self.rep)['approved_bio'])
        self.assertEqual(sender_for(self.other)['signature'],'AI Business Gurus team\nAI Business Gurus')
        self.assertEqual(sender_for(self.other)['email'],'')
    def test_seed_preserves_manager_changes(self):
        SalesEmailService.objects.filter(pk='crm').update(name='Approved CRM title',enabled=False)
        seed();self.assertEqual(SalesEmailService.objects.count(),17);self.assertFalse(SalesEmailService.objects.get(pk='crm').enabled)
    def test_manager_page_and_permissions(self):
        self.assertEqual(self.client.get(reverse('sales_email_manage')).status_code,403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('sales_email_manage')).status_code,200)
    def test_direct_send_routes_disabled(self):
        import uuid
        for name,args in [('outreach_connections',[]),('outreach_google_connect',[]),('outreach_google_callback',[]),('outreach_send',[uuid.uuid4()]),('outreach_draft',[self.lead.pk]),('outreach_sms_inbound',[])]:
            with self.subTest(name=name),patch('crm.outreach_providers.google_json') as gmail,patch('crm.outreach.send_sms') as sms:
                self.assertEqual(self.client.post(reverse(name,args=args)).status_code,410)
                gmail.assert_not_called();sms.assert_not_called()

    def test_sensitive_note_ui_propagates_to_activity(self):
        response=self.client.post(reverse('lead_detail',args=[self.lead.pk]),{'action':'add_note','note':'Manager-only confidential detail','is_sensitive':'on'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(LeadActivity.objects.get(lead=self.lead).is_sensitive)
        _,model=self.generate()
        self.assertNotIn('Manager-only confidential detail',model.call_args.kwargs['messages'][1]['content'])
    def test_reassignment_during_model_call_fails_closed(self):
        def changed(**kwargs):
            Lead.objects.filter(pk=self.lead.pk).update(assigned_to=self.other)
            return self.output,{'status':'success'}
        with patch('crm.email_generator.service.PlatformAIService.structured_json',side_effect=changed):
            response=self.post('sales_email_generate',self.data)
        self.assertEqual(response.status_code,403)
        self.assertFalse(OutreachMessage.objects.exists())
    def test_generation_is_rate_limited(self):
        with patch('crm.email_generator.service.consume_budget',return_value=False):
            response,model=self.generate()
        self.assertEqual(response.status_code,429);model.assert_not_called()
    def test_staff_cannot_modify_another_authors_draft_after_reassignment(self):
        d=self.generate()[0].json()['draft']
        self.lead.assigned_to=self.other;self.lead.save();self.client.force_login(self.other)
        self.assertEqual(self.action(d,'save').status_code,403)
    def test_saved_generation_retains_service_selection_order(self):
        d=self.generate()[0].json()['draft']
        self.assertEqual(d['options']['services'],self.data['services'])

    def test_normal_activities_included_sensitive_duplicates_excluded(self):
        LeadActivity.objects.create(lead=self.lead,raw_note='Normal call: asked about follow-up')
        LeadNote.objects.create(lead=self.lead,note='private-only-note',is_sensitive=True)
        LeadActivity.objects.create(lead=self.lead,raw_note='private-only-note')
        LeadActivity.objects.create(lead=self.lead,raw_note='metadata-private',metadata={'sensitive':True})
        _,model=self.generate()
        prompt=model.call_args.kwargs['messages'][1]['content']
        self.assertIn('Normal call: asked about follow-up',prompt)
        self.assertNotIn('private-only-note',prompt)
        self.assertNotIn('metadata-private',prompt)

    def test_manager_configuration_saves_hidden_primary_keys(self):
        self.client.force_login(self.owner)
        page=self.client.get(reverse('sales_email_manage'))
        data={}
        for field in page.context['form']:
            if field.value() is not None and field.value() is not False: data[field.html_name]=field.value()
        for name in ['services','types','profiles']:
            formset=page.context[name]
            for field in formset.management_form:
                data[field.html_name]=field.value()
            for form in formset:
                for field in form:
                    if field.value() is not None and field.value() is not False: data[field.html_name]=field.value()
        data['services-0-name']='Approved calling assistant'
        response=self.client.post(reverse('sales_email_manage'),data)
        self.assertEqual(response.status_code,302,response.context and [(k,str(response.context[k].errors)) for k in ['form','services','types','profiles']])
        self.assertEqual(SalesEmailService.objects.get(pk='outbound').name,'Approved calling assistant')
