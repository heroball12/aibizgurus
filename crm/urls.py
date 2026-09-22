from django.urls import path
from . import views
from . import workspace_views
from . import sheet_views
urlpatterns = [
    path("sheets/", sheet_views.hub, name="lead_sheets"),
    path("sheets/new/", sheet_views.editor, name="lead_sheet_new"),
    path("sheets/save/", sheet_views.save, name="lead_sheet_save"),
    path("sheets/open-file/", sheet_views.import_preview, name="lead_sheet_import"),
    path("sheets/export/", sheet_views.export, name="lead_sheet_export"),
    path("sheets/<uuid:pk>/", sheet_views.editor, name="lead_sheet"),
    path("sheets/<uuid:pk>/export/", sheet_views.export, name="lead_sheet_file"),
    path("", views.crm_home, name="crm_home"),
    path("pipeline/", workspace_views.pipeline, name="sales_pipeline"),
    path("assessments/", workspace_views.assessments, name="sales_assessments"),
    path("leads/<int:pk>/progress/", workspace_views.lead_progress, name="lead_progress"),
    path("lead-finder/", views.lead_finder, name="lead_finder"),
    path("lead-finder/history/", views.lead_generation_history, name="lead_generation_history"),
    path("lead-finder/batches/<int:pk>/status/", views.lead_generation_batch_status, name="lead_generation_batch_status"),
    path("lead-finder/batches/<int:pk>/", views.lead_generation_batch_detail, name="lead_generation_batch_detail"),
    path("lead-finder/batches/<int:pk>/assign/", views.lead_generation_batch_assign, name="lead_generation_batch_assign"),
    path("lead-finder/staging/<int:pk>/<str:action>/", views.lead_staging_action, name="lead_staging_action"),
    path("leads/new/", views.lead_create, name="lead_create"),
    path("leads/upload/", views.lead_upload, name="lead_upload"),
    path("leads/actions/", views.lead_bulk_action, name="lead_bulk_action"),
    path("leads/export/", views.export_leads, name="lead_export"),
    path("imports/<int:pk>/delete-sheet/", views.lead_import_delete_sheet, name="lead_import_delete_sheet"),
    path("imports/<int:pk>/", views.lead_import_detail, name="lead_import_detail"),
    path("queues/<str:queue_type>/", views.lead_queue, name="lead_queue"),
    path("scorecards/", views.scorecards, name="sales_scorecards"),
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    path("leads/<int:pk>/edit/", views.lead_edit, name="lead_edit"),
    path("leads/<int:pk>/delete/", views.lead_delete, name="lead_delete"),
]
