from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from audit.models import ActivityLog

class Command(BaseCommand):
    help = "Check whether the audit activity log table exists"

    def handle(self, *args, **kwargs):
        table = ActivityLog._meta.db_table
        exists = table in connection.introspection.table_names()
        self.stdout.write(f"Audit table: {table}")
        self.stdout.write(f"Audit table exists: {'yes' if exists else 'no'}")
        if exists:
            self.stdout.write(f"Activity logs: {ActivityLog.objects.count()}")
        else:
            raise CommandError("Audit table is missing. Run: python manage.py migrate")
