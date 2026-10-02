from django import forms
from crm.models import SalesEmailType, SalesEmailService, SalesEmailConfig, SalesProfile
from crm.email_models import TONES, LENGTHS

class GenerationForm(forms.Form):
    email_type = forms.ModelChoiceField(queryset=SalesEmailType.objects.filter(enabled=True), to_field_name='slug', empty_label=None)
    focus = forms.ChoiceField(choices=[('general','General introduction'),('services','Selected services')])
    services = forms.ModelMultipleChoiceField(queryset=SalesEmailService.objects.filter(enabled=True), to_field_name='slug', required=False, widget=forms.CheckboxSelectMultiple)
    include_demo = forms.BooleanField(required=False, label='Include Demo Center')
    include_assessment = forms.BooleanField(required=False, label='Include scheduling link')
    tone = forms.ChoiceField(choices=TONES)
    length = forms.ChoiceField(choices=LENGTHS)
    instructions = forms.CharField(required=False,max_length=1200,widget=forms.Textarea(attrs={'rows':3,'placeholder':'Anything specific to focus on or leave out?'}))
    parent = forms.UUIDField(required=False, widget=forms.HiddenInput)
    def clean(self):
        data=super().clean()
        selected=data.get('services')
        if data.get('focus')=='services' and not selected:
            self.add_error('services','Select at least one service.')
        if data.get('focus')=='general' and selected:
            self.add_error('services','General introduction cannot include selected services.')
        if selected:
            order = list(self.data.get('services', []))
            data['services'] = sorted(selected, key=lambda service: order.index(service.slug))
        return data

class ConfigForm(forms.ModelForm):
    class Meta:
        model=SalesEmailConfig
        exclude=['id']
        widgets={x:forms.Textarea(attrs={'rows':3}) for x in ['company_description','assessment_description','forbidden_claims']}
class ProfileForm(forms.ModelForm):
    class Meta:
        model=SalesProfile
        fields=['user','display_name','title','business_email','business_phone','approved_bio','scheduling_url']
        widgets={'approved_bio':forms.Textarea(attrs={'rows':2})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        self.fields['user'].queryset=get_user_model().objects.filter(Q(role__in=['employee','admin','owner'])|Q(is_staff=True),is_active=True)
    def clean_scheduling_url(self):
        from .context import safe_url
        url=self.cleaned_data.get('scheduling_url','')
        if url and not safe_url(url):
            raise forms.ValidationError('Use a secure HTTPS scheduling URL without credentials.')
        return url
