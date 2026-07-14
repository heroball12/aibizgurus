from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from crm.models import Lead, LeadActivity, LeadImport


class Command(BaseCommand):
    help = "Verify CRM lead import tables/columns needed by CSV/XLSX uploads."

    def handle(self, *args, **options):
        expected = {
            LeadImport._meta.db_table: {
                "original_filename",
                "uploaded_by_id",
                "file_type",
                "sheet_names",
                "row_count",
                "imported_count",
                "updated_count",
                "skipped_count",
                "duplicate_count",
                "error_count",
                "notes_analyzed_count",
                "high_confidence_count",
                "review_count",
                "status",
                "import_summary",
                "created_at",
            },
            Lead._meta.db_table: {
                "lead_type",
                "client_id",
                "ai_instance_id",
                "business_name",
                "phone",
                "email",
                "assigned_to_id",
                "duplicate_key",
                "archived",
                "created_at",
            },
            LeadActivity._meta.db_table: {
                "lead_id",
                "user_id",
                "raw_note",
                "cleaned_note",
                "original_import_id",
                "original_row_number",
                "metadata",
                "created_at",
            },
        }
        existing_tables = set(connection.introspection.table_names())
        missing_tables = [table for table in expected if table not in existing_tables]
        if missing_tables:
            raise CommandError(f"Missing CRM tables: {', '.join(missing_tables)}. Run: python manage.py migrate")

        missing_columns = {}
        with connection.cursor() as cursor:
            for table, columns in expected.items():
                present = {column.name for column in connection.introspection.get_table_description(cursor, table)}
                missing = sorted(columns - present)
                if missing:
                    missing_columns[table] = missing

        if missing_columns:
            details = "; ".join(f"{table}: {', '.join(columns)}" for table, columns in missing_columns.items())
            raise CommandError(f"Missing CRM import columns: {details}. Run: python manage.py migrate")

        self.stdout.write(self.style.SUCCESS("CRM import schema OK."))
        self.stdout.write(f"Lead imports: {LeadImport.objects.count()}")
        self.stdout.write(f"Internal sales leads: {Lead.objects.filter(lead_type='internal_sales').count()}")
