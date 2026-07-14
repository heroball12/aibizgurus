from django.contrib import admin
from .models import ClassificationCorrection, Lead, LeadActivity, LeadImport, LeadNote

class LeadNoteInline(admin.TabularInline):
    model = LeadNote
    extra = 0


class LeadActivityInline(admin.TabularInline):
    model = LeadActivity
    extra = 0
    fields = ("activity_type", "inferred_status", "lead_temperature", "confidence_score", "classification_source", "created_at")
    readonly_fields = ("created_at",)

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "business_name", "lead_type", "status", "lead_temperature", "assigned_to", "needs_review", "value", "created_at")
    search_fields = ("name", "business_name", "email", "phone", "notes", "cleaned_notes", "source_file")
    list_filter = ("lead_type", "status", "lead_temperature", "needs_review", "classification_source", "industry")
    readonly_fields = ("created_at", "imported_at")
    date_hierarchy = "created_at"
    inlines = [LeadNoteInline, LeadActivityInline]


@admin.register(LeadImport)
class LeadImportAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "uploaded_by", "status", "imported_count", "duplicate_count", "review_count", "created_at")
    search_fields = ("original_filename", "uploaded_by__username", "uploaded_by__email")
    list_filter = ("status", "file_type", "created_at")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(LeadActivity)
class LeadActivityAdmin(admin.ModelAdmin):
    list_display = ("lead", "activity_type", "inferred_status", "lead_temperature", "confidence_score", "classification_source", "created_at")
    search_fields = ("lead__business_name", "lead__name", "raw_note", "cleaned_note")
    list_filter = ("activity_type", "inferred_status", "lead_temperature", "classification_source", "manually_reviewed")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(ClassificationCorrection)
class ClassificationCorrectionAdmin(admin.ModelAdmin):
    list_display = ("lead", "original_status", "corrected_status", "corrected_by", "created_at")
    search_fields = ("lead__business_name", "lead__name", "reason")
    list_filter = ("corrected_status", "corrected_temperature", "created_at")
    readonly_fields = ("created_at",)
