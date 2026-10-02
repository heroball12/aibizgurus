"""Approved sales messaging configuration; drafts reuse OutreachMessage."""
from django.conf import settings
from django.db import models

TONES = [(x, y) for x, y in [('natural','Natural & professional'),('direct','Direct'),('consultative','Consultative'),('friendly','Friendly'),('executive','Executive')]]
LENGTHS = [('short','Short'),('standard','Standard'),('detailed','Detailed')]

class SalesEmailConfig(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=True)
    company_description = models.TextField(max_length=2000)
    assessment_description = models.TextField(max_length=1000)
    forbidden_claims = models.TextField(blank=True, max_length=3000, help_text='Additional forbidden phrases, one per line. Core restrictions always apply.')
    default_tone = models.CharField(max_length=20, choices=TONES, default='natural')
    default_length = models.CharField(max_length=20, choices=[('', 'Use email type default')] + LENGTHS, blank=True)
    include_demo = models.BooleanField(default=True)
    include_assessment = models.BooleanField(default=True)

class SalesEmailType(models.Model):
    slug = models.SlugField(primary_key=True)
    name = models.CharField(max_length=100)
    guidance = models.TextField(max_length=1500)
    default_length = models.CharField(max_length=20, choices=LENGTHS, default='short')
    enabled = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)
    class Meta:
        ordering = ['position', 'slug']

    def __str__(self):
        return self.name

class SalesEmailService(models.Model):
    slug = models.SlugField(primary_key=True)
    name = models.CharField(max_length=100)
    description = models.TextField(max_length=1500)
    enabled = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)
    class Meta:
        ordering = ['position', 'slug']

    def __str__(self):
        return self.name

class SalesProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sales_profile')
    display_name = models.CharField(max_length=150)
    title = models.CharField(max_length=150, blank=True)
    business_email = models.EmailField(blank=True)
    business_phone = models.CharField(max_length=80, blank=True)
    approved_bio = models.TextField(blank=True, max_length=1200, help_text='Approved professional credibility only. No private employee information.')
    scheduling_url = models.URLField(blank=True)
    def signature(self):
        return '\n'.join(x for x in [self.display_name, self.title, 'AI Business Gurus', self.business_email, self.business_phone] if x)
