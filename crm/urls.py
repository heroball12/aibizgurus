from django.urls import path
from . import views
urlpatterns = [
    path("", views.crm_home, name="crm_home"),
    path("leads/new/", views.lead_create, name="lead_create"),
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    path("leads/<int:pk>/edit/", views.lead_edit, name="lead_edit"),
]
