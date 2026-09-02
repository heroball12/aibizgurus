try:
    from celery import shared_task
except ImportError:  # Celery is optional locally; Render can install/run it when Redis is configured.
    def shared_task(*decorator_args, **decorator_kwargs):
        def decorator(func):
            def delay(*args, **kwargs):
                raise RuntimeError("Celery is not installed.")

            func.delay = delay
            return func
        return decorator

from .lead_finder import generate_leads_for_batch


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def process_lead_generation_batch(self, batch_id):
    batch = generate_leads_for_batch(batch_id)
    return {
        "batch_id": batch.pk,
        "status": batch.status,
        "quantity_generated": batch.quantity_generated,
        "duplicates_removed": batch.duplicates_removed,
    }
