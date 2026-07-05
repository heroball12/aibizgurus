from django.contrib import admin
from .models import Lead, LeadNote

class LeadNoteInline(admin.TabularInline):
    model = LeadNote
    extra = 0

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "business_name", "lead_type", "status", "value", "created_at")
    search_fields = ("name", "business_name", "email", "phone", "notes")
    list_filter = ("lead_type", "status", "industry")
    inlines = [LeadNoteInline]
