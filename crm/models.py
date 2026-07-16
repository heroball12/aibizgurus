from django.conf import settings
from django.db import models


INTERNAL_STATUS_CHOICES = [
    ("new", "New"),
    ("not_contacted", "Not Contacted"),
    ("attempted", "Attempted"),
    ("no_answer", "No Answer"),
    ("disconnected_number", "Disconnected Number"),
    ("wrong_number", "Wrong Number"),
    ("voicemail_left", "Voicemail Left"),
    ("gatekeeper_reached", "Gatekeeper Reached"),
    ("decision_maker_unavailable", "Decision Maker Unavailable"),
    ("decision_maker_reached", "Decision Maker Reached"),
    ("information_requested", "Information Requested"),
    ("email_requested", "Email Requested"),
    ("callback_requested", "Callback Requested"),
    ("follow_up", "Follow-Up Needed"),
    ("warm_lead", "Warm Lead"),
    ("hot_lead", "Hot Lead"),
    ("appointment_scheduled", "Appointment Scheduled"),
    ("appointment_completed", "Appointment Completed"),
    ("proposal_requested", "Proposal Requested"),
    ("proposal_sent", "Proposal Sent"),
    ("corporate_referral", "Corporate Referral"),
    ("existing_vendor", "Existing Vendor"),
    ("already_uses_ai", "Already Uses AI"),
    ("has_internal_marketing", "Has Internal Marketing"),
    ("not_interested", "Not Interested"),
    ("do_not_contact", "Do Not Contact"),
    ("closed_won", "Closed Won"),
    ("closed_lost", "Closed Lost"),
    ("duplicate", "Duplicate"),
    ("duplicate_review", "Duplicate Review"),
    ("permanently_closed", "Permanently Closed"),
    # Legacy platform statuses preserved for backward compatibility.
    ("contacted", "Contacted"),
    ("demo_sent", "Demo Sent"),
    ("client_onboarded", "Client Onboarded"),
]


TEMPERATURE_CHOICES = [
    ("cold", "Cold"),
    ("warm", "Warm"),
    ("hot", "Hot"),
    ("closed", "Closed"),
]


CLASSIFICATION_SOURCE_CHOICES = [
    ("manual", "Manual"),
    ("rule", "Rules Engine"),
    ("ai", "AI Assisted"),
    ("import", "Imported"),
]

class Lead(models.Model):
    LEAD_TYPE_CHOICES = [("internal_sales","Internal Sales Lead"),("client_customer","Client Customer Lead")]
    STATUS_CHOICES = INTERNAL_STATUS_CHOICES
    client = models.ForeignKey("clients.ClientAccount", on_delete=models.CASCADE, null=True, blank=True, related_name="leads")
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads")
    lead_type = models.CharField(max_length=30, choices=LEAD_TYPE_CHOICES, default="internal_sales")
    name = models.CharField(max_length=150, blank=True)
    business_name = models.CharField(max_length=200, blank=True)
    industry = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    point_of_contact = models.CharField(max_length=150, blank=True)
    contact_role = models.CharField(max_length=120, blank=True)
    source = models.CharField(max_length=150, blank=True)
    source_file = models.CharField(max_length=255, blank=True)
    source_sheet = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="new")
    lead_temperature = models.CharField(max_length=20, choices=TEMPERATURE_CHOICES, default="cold")
    notes = models.TextField(blank=True)
    cleaned_notes = models.TextField(blank=True)
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    last_contact_at = models.DateTimeField(null=True, blank=True)
    next_follow_up_at = models.DateTimeField(null=True, blank=True)
    appointment_at = models.DateTimeField(null=True, blank=True)
    classification_confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    classification_source = models.CharField(max_length=20, choices=CLASSIFICATION_SOURCE_CHOICES, default="manual")
    needs_review = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)
    duplicate_key = models.CharField(max_length=255, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["lead_type", "status"]),
            models.Index(fields=["lead_type", "lead_temperature"]),
            models.Index(fields=["lead_type", "archived", "created_at"]),
            models.Index(fields=["lead_type", "assigned_to", "created_at"]),
            models.Index(fields=["lead_type", "source_file"]),
            models.Index(fields=["lead_type", "source_file", "source_sheet", "archived"]),
            models.Index(fields=["client", "lead_type", "created_at"]),
            models.Index(fields=["ai_instance", "created_at"]),
            models.Index(fields=["assigned_to", "follow_up_date"]),
            models.Index(fields=["needs_review", "created_at"]),
        ]

    def __str__(self):
        return self.name or self.business_name or f"Lead {self.pk}"

class LeadNote(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="lead_notes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class LeadImport(models.Model):
    STATUS_CHOICES = [
        ("uploaded", "Uploaded"),
        ("processed", "Processed"),
        ("needs_review", "Needs Review"),
        ("failed", "Failed"),
    ]
    uploaded_file = models.FileField(upload_to="crm/imports/", null=True, blank=True)
    original_filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    file_type = models.CharField(max_length=20, default="csv")
    sheet_names = models.JSONField(default=list, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    notes_analyzed_count = models.PositiveIntegerField(default=0)
    high_confidence_count = models.PositiveIntegerField(default=0)
    review_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="uploaded")
    import_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["uploaded_by", "created_at"]),
        ]

    def __str__(self):
        return self.original_filename


class LeadActivity(models.Model):
    ACTIVITY_CHOICES = [
        ("imported_note", "Imported Note"),
        ("call", "Call"),
        ("email", "Email"),
        ("sms", "SMS"),
        ("follow_up", "Follow-Up"),
        ("status_change", "Status Change"),
        ("manual_note", "Manual Note"),
    ]
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    raw_note = models.TextField(blank=True)
    cleaned_note = models.TextField(blank=True)
    inferred_status = models.CharField(max_length=30, choices=Lead.STATUS_CHOICES, default="new")
    lead_temperature = models.CharField(max_length=20, choices=TEMPERATURE_CHOICES, default="cold")
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    contact_person = models.CharField(max_length=150, blank=True)
    contact_role = models.CharField(max_length=120, blank=True)
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_CHOICES, default="imported_note")
    call_outcome = models.CharField(max_length=120, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    classification_source = models.CharField(max_length=20, choices=CLASSIFICATION_SOURCE_CHOICES, default="rule")
    created_at = models.DateTimeField(auto_now_add=True)
    manually_reviewed = models.BooleanField(default=False)
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corrected_lead_activities",
    )
    original_import = models.ForeignKey(LeadImport, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    original_row_number = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["inferred_status", "lead_temperature"]),
            models.Index(fields=["classification_source", "created_at"]),
        ]

    def __str__(self):
        return f"{self.lead} · {self.get_inferred_status_display()}"


class ClassificationCorrection(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="classification_corrections")
    activity = models.ForeignKey(LeadActivity, on_delete=models.SET_NULL, null=True, blank=True, related_name="corrections")
    original_status = models.CharField(max_length=30, choices=Lead.STATUS_CHOICES, blank=True)
    corrected_status = models.CharField(max_length=30, choices=Lead.STATUS_CHOICES)
    original_temperature = models.CharField(max_length=20, choices=TEMPERATURE_CHOICES, blank=True)
    corrected_temperature = models.CharField(max_length=20, choices=TEMPERATURE_CHOICES)
    original_cleaned_note = models.TextField(blank=True)
    corrected_cleaned_note = models.TextField(blank=True)
    corrected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Correction for {self.lead}"
