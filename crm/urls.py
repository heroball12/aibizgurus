from django.urls import path
from . import views
urlpatterns = [
    path("", views.crm_home, name="crm_home"),
    path("leads/new/", views.lead_create, name="lead_create"),
    path("leads/upload/", views.lead_upload, name="lead_upload"),
    path("leads/export/", views.export_leads, name="lead_export"),
    path("imports/<int:pk>/", views.lead_import_detail, name="lead_import_detail"),
    path("queues/<str:queue_type>/", views.lead_queue, name="lead_queue"),
    path("scorecards/", views.scorecards, name="sales_scorecards"),
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    path("leads/<int:pk>/edit/", views.lead_edit, name="lead_edit"),
    path("leads/<int:pk>/delete/", views.lead_delete, name="lead_delete"),
]
