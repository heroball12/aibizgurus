from django.urls import path

from . import team_views


urlpatterns = [
    path("messages/", team_views.staff_messages, name="staff_messages"),
    path("messages/new/", team_views.staff_message_create, name="staff_message_create"),
    path("messages/summary/", team_views.staff_message_summary, name="staff_message_summary"),
    path("messages/<int:pk>/", team_views.staff_message_thread, name="staff_message_thread"),
    path("messages/<int:pk>/feed/", team_views.staff_message_feed, name="staff_message_feed"),
    path("messages/attachments/<int:pk>/", team_views.staff_message_attachment, name="staff_message_attachment"),
    path("time-clock/", team_views.staff_time_clock, name="staff_time_clock"),
    path("time-clock/admin/", team_views.staff_time_clock_admin, name="staff_time_clock_admin"),
    path("time-clock/admin/entries/<int:pk>/edit/", team_views.staff_time_clock_entry_edit, name="staff_time_clock_entry_edit"),
    path("time-clock/admin/entries/<int:pk>/clock-out/", team_views.staff_time_clock_entry_clock_out, name="staff_time_clock_entry_clock_out"),
]
