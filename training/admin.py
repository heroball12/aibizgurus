from django.contrib import admin
from . import models


class TrainingAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.role in {"admin", "owner"}

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_owner()

    def has_add_permission(self, request):
        return request.user.is_owner()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.ModuleVersion)
class VersionAdmin(TrainingAdmin):
    list_display = ("module", "number", "policy_version", "status", "published_at")
    list_filter = ("status", "module__track")

    def get_readonly_fields(self, request, obj=None):
        fixed = (
            "status",
            "published_at",
            "retired_at",
            "approved_by",
            "approved_at",
            "created_at",
        )
        return (
            [f.name for f in models.ModuleVersion._meta.fields]
            if obj and obj.status in {"approved", "published", "retired"}
            else fixed
        )


class ContentAdmin(TrainingAdmin):
    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            not obj or obj.version_record().status in {"draft", "owner_review"}
        )


class EvidenceAdmin(TrainingAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


for model in [models.Course, models.Track, models.Module, models.Skill]:
    admin.site.register(model, TrainingAdmin)
for model in [
    models.LessonAsset,
    models.Quiz,
    models.Question,
    models.RolePlayScenario,
]:
    admin.site.register(model, ContentAdmin)
for model in [
    models.EmployeeProgress,
    models.QuizAttempt,
    models.RolePlayAttempt,
    models.EmployeeSkill,
    models.CertificationAttempt,
    models.TrainingAssignment,
    models.ManagerReview,
    models.Certification,
    models.ProctorSession,
]:
    admin.site.register(model, EvidenceAdmin)
