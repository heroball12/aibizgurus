from django.db import migrations

OLD = 'A complimentary 15–20 minute video Growth Assessment with an AI Specialist to understand current operations, identify bottlenecks and evaluate relevant AI/software opportunities and an implementation approach.'
NEW = 'A complimentary Growth Assessment with an AI Specialist, available virtually or in person in Temecula, to understand current operations, identify bottlenecks and evaluate relevant AI/software opportunities and an implementation approach.'


def update_default(apps, schema_editor):
    # Preserve any messaging the owner has customized.
    apps.get_model('crm', 'SalesEmailConfig').objects.filter(assessment_description=OLD).update(assessment_description=NEW)


class Migration(migrations.Migration):
    dependencies = [('crm', '0017_calendlyconnection_signing_fingerprint')]
    operations = [migrations.RunPython(update_default, migrations.RunPython.noop)]
