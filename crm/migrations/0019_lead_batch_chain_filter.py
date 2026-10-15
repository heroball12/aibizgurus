from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crm", "0018_assessment_format_copy")]

    operations = [
        # Old searches were not filtered; retain that history accurately.
        migrations.AddField(
            model_name="leadgenerationbatch", name="exclude_major_chains",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="leadgenerationbatch", name="exclude_major_chains",
            field=models.BooleanField(default=True),
        ),
    ]
