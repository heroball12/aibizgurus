import uuid
from datetime import time

from django.db import models
from django.db.models import Q


def weekdays():
    return [0, 1, 2, 3, 4]


class OfficeSchedule(models.Model):
    """One owner calendar. Lock this row when changing availability or reserving."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    weekdays = models.JSONField(default=weekdays)
    opens_at = models.TimeField(default=time(9))
    closes_at = models.TimeField(default=time(17))
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    buffer_minutes = models.PositiveSmallIntegerField(default=30)
    notice_hours = models.PositiveSmallIntegerField(default=2)
    horizon_days = models.PositiveSmallIntegerField(default=60)
    notification_email = models.EmailField(blank=True)


class OfficeClosure(models.Model):
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=models.F("starts_at")), name="office_closure_positive")]


class OfficeAppointment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission_key = models.UUIDField(unique=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    blocked_until = models.DateTimeField()
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=80)
    business_name = models.CharField(max_length=200)
    industry = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=[("confirmed", "Confirmed"), ("canceled", "Canceled")], default="confirmed")
    consultation = models.OneToOneField("core.ConsultationRequest", null=True, on_delete=models.SET_NULL)
    lead = models.ForeignKey("crm.Lead", null=True, on_delete=models.SET_NULL, related_name="office_appointments")
    created_at = models.DateTimeField(auto_now_add=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    owner_seen = models.BooleanField(default=False)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["starts_at"], condition=Q(status="confirmed"), name="one_office_booking_per_start"),
            models.CheckConstraint(condition=Q(ends_at__gt=models.F("starts_at")), name="office_booking_positive"),
            models.CheckConstraint(condition=Q(blocked_until__gte=models.F("ends_at")), name="office_booking_buffer"),
        ]


class OfficeBookingEmail(models.Model):
    """Persistent notification outbox; unsuccessful delivery can be retried by the owner."""
    appointment = models.ForeignKey(OfficeAppointment, on_delete=models.CASCADE, related_name="emails")
    kind = models.CharField(max_length=30)
    recipient = models.EmailField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["appointment", "kind"], name="office_email_once_per_kind")]
