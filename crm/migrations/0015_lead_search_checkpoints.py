from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0014_lead_business_verification_and_more"),
        ("crm", "0013_sales_email_copilot"),
    ]
    operations = [
        migrations.AddField(model_name="leadgenerationbatch", name="search_state", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="leadgenerationbatch", name="run_token", field=models.UUIDField(blank=True, null=True)),
        migrations.AddField(model_name="leadgenerationbatch", name="lease_expires_at", field=models.DateTimeField(blank=True, null=True)),
    ]
