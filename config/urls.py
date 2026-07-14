from django.contrib import admin
from django.urls import path, include
from core import views as core_views
from clients import views as client_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("portal/", include("clients.urls")),
    path("ai/", include("assistant_ai.urls")),
    path("crm/", include("crm.urls")),
    path("voice/", include("voice.urls")),
    path("billing/", include("billing.urls")),
    path("owner/", include("audit.urls")),
    path("team/", include("audit.team_urls")),
    path("ops/", core_views.ops_dashboard, name="ops_dashboard"),
    path("ops/client/<int:client_id>/", client_views.ops_client_detail, name="ops_client_detail"),
    path("ops/client/<int:client_id>/conversations/<int:conversation_id>/", client_views.ops_conversation_detail, name="ops_conversation_detail"),
]

handler404 = "core.views.page_not_found"
handler500 = "core.views.server_error"
