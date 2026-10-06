from django.core.management.base import BaseCommand
from audit.history import batch

class Command(BaseCommand):
    help = 'Preview historical CRM recovery; --apply creates idempotent, labeled activity events.'
    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
    def handle(self, *args, **options):
        source, after = 'audit', 0
        totals = dict(scanned=0, recovered=0, already_counted=0, unsupported=0)
        while source != 'done':
            result = batch(source, after, apply=options['apply'])
            for key in totals:
                totals[key] += result[key]
            source, after = result['next_source'], result['next_after']
        self.stdout.write(('Applied: ' if options['apply'] else 'Preview only (overlapping sources may merge on apply): ') + str(totals))
