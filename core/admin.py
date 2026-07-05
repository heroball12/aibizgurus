from django.contrib import admin
from .models import IndustryTemplate, ConsultationRequest

@admin.register(IndustryTemplate)
class IndustryTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_supported")
    list_filter = ("category", "is_supported")
    search_fields = ("name", "summary")

@admin.register(ConsultationRequest)
class ConsultationRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "business_name", "industry", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email", "business_name", "industry")
