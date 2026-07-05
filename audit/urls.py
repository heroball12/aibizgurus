from django.urls import path
from . import views

urlpatterns = [
    path("", views.owner_dashboard, name="owner_dashboard"),
    path("activity/", views.owner_activity_logs, name="owner_activity_logs"),
    path("users/", views.owner_users, name="owner_users"),
    path("clients/", views.owner_clients, name="owner_clients"),
]
