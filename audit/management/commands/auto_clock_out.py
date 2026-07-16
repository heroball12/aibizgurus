from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from audit.models import TimeClockEntry
from audit.utils import log_activity


class Command(BaseCommand):
    help = "Automatically clock out open staff shifts that have been open for 8 hours."

    def handle(self, *args, **options):
        now = timezone.now()
        cutoff = now - timedelta(hours=8)
        entries = list(
            TimeClockEntry.objects
            .filter(clock_out__isnull=True, clock_in__lte=cutoff)
            .select_related("employee")
        )
        for entry in entries:
            entry.clock_out = entry.clock_in + timedelta(hours=8)
            auto_note = "Auto clock-out after 8 hours."
            entry.note = f"{entry.note} · {auto_note}" if entry.note and auto_note not in entry.note else (entry.note or auto_note)
            entry.save(update_fields=["clock_out", "note", "updated_at"])
            log_activity(
                action="update",
                model_label="audit.TimeClockEntry",
                object_id=entry.pk,
                object_repr=str(entry),
                message=f"Auto clocked out {entry.employee} after 8 hours.",
            )
        self.stdout.write(self.style.SUCCESS(f"Auto clocked out {len(entries)} overdue shift(s)."))
