from django.contrib import admin
from .models import ClientAccount, BusinessProfile, Integration, AIInstance

class BusinessProfileInline(admin.StackedInline):
    model = BusinessProfile
    extra = 0

class AIInstanceInline(admin.TabularInline):
    model = AIInstance
    extra = 0

@admin.register(ClientAccount)
class ClientAccountAdmin(admin.ModelAdmin):
    list_display = ("business_name", "industry", "status", "plan", "activation_status", "created_at")
    search_fields = ("business_name", "contact_email", "contact_phone")
    list_filter = ("status", "activation_status", "plan", "industry")
    inlines = [BusinessProfileInline, AIInstanceInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Inline assistant forms save after the parent. Re-sync so changing only
        # activation_status in admin reliably enables or pauses the assistant.
        form.instance.sync_assistant_activation()

@admin.register(AIInstance)
class AIInstanceAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "industry_template", "status", "widget_primary_color", "embed_enabled", "voice_enabled", "sms_enabled")
    list_filter = ("status", "voice_enabled", "sms_enabled")

@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ("client", "integration_type", "name", "is_active", "created_at")
    list_filter = ("integration_type", "is_active")
