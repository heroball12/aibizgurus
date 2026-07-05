from django.db.models.signals import post_migrate
from django.dispatch import receiver

@receiver(post_migrate)
def seed_industries_after_migrate(sender, **kwargs):
    # Only run once for the core app after migrations.
    if sender.name != "core":
        return
    try:
        from .seed import seed_industries
        seed_industries()
    except Exception:
        # Never block migrations because of seed data.
        pass
