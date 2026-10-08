from django.db import migrations


def configure(apps, schema_editor):
    # Office hours and recipient approved by the owner on October 8, 2026.
    apps.get_model("core", "OfficeSchedule").objects.get_or_create(
        pk=1, defaults={"enabled": True, "weekdays": [0, 1, 2, 3, 4], "notification_email": "james@aibiz.guru"}
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0005_office_booking")]
    operations = [migrations.RunPython(configure, migrations.RunPython.noop)]
