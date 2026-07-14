from django.urls import path
from . import views

urlpatterns = [
    path("", views.owner_dashboard, name="owner_dashboard"),
    path("activity/", views.owner_activity_logs, name="owner_activity_logs"),
    path("users/", views.owner_users, name="owner_users"),
    path("clients/", views.owner_clients, name="owner_clients"),
    path("staff/", views.staff_users, name="staff_users"),
    path("staff/new/", views.staff_user_create, name="staff_user_create"),
    path("staff/<int:pk>/performance/", views.staff_performance, name="staff_performance"),
    path("staff/<int:pk>/edit/", views.staff_user_edit, name="staff_user_edit"),
    path("staff/<int:pk>/deactivate/", views.staff_user_deactivate, name="staff_user_deactivate"),
]
