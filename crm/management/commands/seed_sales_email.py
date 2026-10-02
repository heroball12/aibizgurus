from django.core.management.base import BaseCommand
from crm.email_generator.defaults import seed
class Command(BaseCommand):
    help='Seed missing email copilot defaults without overwriting approved configuration.'
    def handle(self,*args,**options):
        seed()
        self.stdout.write(self.style.SUCCESS('Email copilot defaults are ready. Existing settings were preserved.'))
