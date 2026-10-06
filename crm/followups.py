"""Rep-owned reminders, never unattended outreach."""
from datetime import timedelta
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Lead, SalesFollowUpPlan
from .sales import INACTIVE, STAGES

PLANS = {
    'introduction': ('Introduction', [(2, 'Review and send a relevant email'), (3, 'Call to follow up'), (5, 'Review fit and close the loop')]),
    'demo': ('After a demo', [(1, 'Ask what stood out in the demo'), (3, 'Invite them to a Growth Assessment'), (7, 'Review interest and agree a next step')]),
    'assessment': ('Assessment invitation', [(2, 'Follow up on the assessment invitation'), (4, 'Ask whether the timing is right'), (7, 'Review interest and close the loop')]),
}
STOP = set(INACTIVE + STAGES[3][2] + STAGES[4][2])


def description(plan):
    if plan and plan.active and plan.plan in PLANS:
        steps = PLANS[plan.plan][1]
        if plan.step < len(steps):
            return steps[plan.step][1]
    return ''


def advance(lead, user, choice, date=None):
    plan = SalesFollowUpPlan.objects.filter(lead=lead).first()
    if lead.status in STOP or choice == 'pause':
        if plan:
            plan.active = False
            plan.next_due = None
            plan.save()
        return date
    if choice in PLANS:
        plan, _ = SalesFollowUpPlan.objects.update_or_create(lead=lead, defaults={'plan':choice, 'step':0, 'active':True, 'created_by':user})
    elif plan and plan.active:
        plan.step += 1
    if plan and plan.active:
        steps = PLANS[plan.plan][1]
        if plan.step >= len(steps):
            plan.active, plan.next_due = False, None
        else:
            date = date or timezone.localdate() + timedelta(days=steps[plan.step][0])
            plan.next_due = date
        plan.save()
    return date


@receiver(post_save, sender=Lead)
def stop_restricted_followups(sender, instance, raw=False, **kwargs):
    if not raw and (instance.archived or instance.status in STOP):
        SalesFollowUpPlan.objects.filter(lead=instance, active=True).update(active=False, next_due=None)
