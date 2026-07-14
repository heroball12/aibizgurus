from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from core.security import encrypt_value, decrypt_value, mask_value

hex_color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Enter a valid 6-digit hex color, like #7c3aed.",
)

class ClientAccount(models.Model):
    STATUS_CHOICES = [("onboarding","Onboarding"),("active","Active"),("paused","Paused"),("cancelled","Cancelled")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="client_accounts")
    industry_template = models.ForeignKey(
        "core.IndustryTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client_accounts",
    )
    business_name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    industry = models.CharField(max_length=150, blank=True)
    owner_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=80, blank=True)
    website = models.URLField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="onboarding")
    plan = models.CharField(max_length=100, default="starter")
    activation_status = models.CharField(
        max_length=40,
        choices=[
            ("demo", "Demo"),
            ("pending_payment", "Pending Payment"),
            ("active", "Active"),
            ("paused", "Paused"),
            ("cancelled", "Cancelled"),
        ],
        default="demo",
    )
    paid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["activation_status", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.business_name) or "client"
            slug = base
            i = 2
            while ClientAccount.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

        self.sync_assistant_activation()

    def sync_assistant_activation(self):
        """Keep channel availability aligned with the client's paid state."""
        if self.activation_status == "active":
            self.ai_instances.filter(status__in=["draft", "paused"]).update(status="active")
        elif self.activation_status == "paused":
            self.ai_instances.filter(status="active").update(status="paused")
        elif self.activation_status in {"demo", "pending_payment", "cancelled"}:
            self.ai_instances.filter(status="active").update(status="draft")

    @property
    def is_paid_active(self):
        return self.activation_status == "active"

    @property
    def can_publish_assistants(self):
        return self.is_paid_active

    def __str__(self):
        return self.business_name

class BusinessProfile(models.Model):
    client = models.OneToOneField(ClientAccount, on_delete=models.CASCADE, related_name="profile")
    hours = models.TextField(blank=True)
    services = models.TextField(blank=True)
    products = models.TextField(blank=True)
    faqs = models.TextField(blank=True)
    service_area = models.TextField(blank=True)
    policies = models.TextField(blank=True)
    booking_instructions = models.TextField(blank=True)
    escalation_instructions = models.TextField(blank=True)
    brand_voice = models.CharField(max_length=120, default="friendly, helpful, professional")
    extra_context = models.TextField(blank=True)

    def as_knowledge_text(self):
        fields = [
            ("Business", self.client.business_name), ("Industry", self.client.industry),
            ("Website", self.client.website), ("Hours", self.hours), ("Services", self.services),
            ("Products", self.products), ("FAQs", self.faqs), ("Service Area", self.service_area),
            ("Policies", self.policies), ("Booking Instructions", self.booking_instructions),
            ("Escalation Instructions", self.escalation_instructions), ("Extra Context", self.extra_context),
        ]
        return "\n".join([f"{k}: {v}" for k, v in fields if v])

class Integration(models.Model):
    TYPE_CHOICES = [("openai","OpenAI"),("twilio","Twilio"),("stripe","Stripe"),("email","Email"),("crm","CRM"),("pos","POS"),("other","Other")]
    client = models.ForeignKey(ClientAccount, on_delete=models.CASCADE, related_name="integrations")
    integration_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    name = models.CharField(max_length=100, default="Default")
    is_active = models.BooleanField(default=False)
    credentials = models.JSONField(default=dict, blank=True)  # encrypted values
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_credential(self, key, value):
        creds = dict(self.credentials or {})
        if value:
            creds[key] = encrypt_value(value)
        self.credentials = creds

    def get_credential(self, key):
        return decrypt_value((self.credentials or {}).get(key, ""))

    def decrypted_credentials(self):
        return {k: decrypt_value(v) for k, v in (self.credentials or {}).items()}

    def masked_credentials(self):
        return {k: mask_value(decrypt_value(v)) for k, v in (self.credentials or {}).items()}

    @property
    def uses_platform_openai(self):
        return self.integration_type == "openai" and not self.get_credential("api_key")

class AIInstanceManager(models.Manager):
    def create_from_template(self, client, template=None):
        greeting = "Hi! I’m the AI assistant. How can I help today?"
        prompt = "You are a helpful AI receptionist. Answer questions and capture qualified leads."
        if template:
            greeting = template.default_greeting or greeting
            prompt = template.system_prompt or prompt
        return self.create(
            client=client,
            industry_template=template,
            name=f"{client.business_name} AI Receptionist",
            industry=client.industry,
            greeting=greeting,
            system_prompt=prompt,
            status="draft",
        )

class AIInstance(models.Model):
    STATUS_CHOICES = [("draft","Draft"),("active","Active"),("paused","Paused"),("offline","Offline")]
    API_MODE_CHOICES = [("platform","Platform OpenAI Key"),("client","Client OpenAI Key"),("fallback","Fallback Only")]
    client = models.ForeignKey(ClientAccount, on_delete=models.CASCADE, related_name="ai_instances")
    industry_template = models.ForeignKey(
        "core.IndustryTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_instances",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=250, unique=True, blank=True)
    industry = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft")
    greeting = models.TextField(default="Hi! How can I help today?")
    system_prompt = models.TextField(blank=True)
    tone = models.CharField(max_length=150, default="friendly, direct, helpful")
    model = models.CharField(max_length=100, default="gpt-4o-mini")
    openai_api_mode = models.CharField(max_length=30, choices=API_MODE_CHOICES, default="platform")
    widget_primary_color = models.CharField(
        max_length=7,
        default="#7c3aed",
        validators=[hex_color_validator],
        help_text="Primary color for the website chat widget.",
    )
    embed_enabled = models.BooleanField(default=True)
    voice_enabled = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    collect_name = models.BooleanField(default=True)
    collect_phone = models.BooleanField(default=True)
    collect_email = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AIInstanceManager()

    class Meta:
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["industry", "status"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "assistant"
            slug = base
            i = 2
            while AIInstance.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def embed_url(self):
        return reverse("widget", kwargs={"slug": self.slug})

    def iframe_code(self, base_url=""):
        return f'<iframe src="{base_url}{self.embed_url()}" width="100%" height="650" style="border:0;border-radius:16px;"></iframe>'

    def __str__(self):
        return self.name
