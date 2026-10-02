from django.core import signing
from django.core.exceptions import ValidationError
from django.utils.crypto import salted_hmac
from core.models import DemoRepAccess, DemoShareLink


def manager(user):
    return user.is_authenticated and user.is_active and (user.is_superuser or user.role in ("owner", "admin"))


def salesperson(user):
    return bool(user.is_authenticated and user.is_active and user.is_employee_or_admin() and
                not DemoRepAccess.objects.filter(user=user, enabled=False).exists())


def browser_key(request):
    if not request.session.session_key:
        request.session.create()
    return salted_hmac("experience-browser", request.session.session_key).hexdigest()


def share_token(link):
    return signing.dumps(str(link.pk), salt="experience-share")


def resolve_share(token, experience):
    try:
        pk = signing.loads(token, salt="experience-share", max_age=60 * 86400)
        link = DemoShareLink.objects.select_related("rep").get(pk=pk, experience=experience)
        if link.rep and not salesperson(link.rep):
            return None
        return link
    except (signing.BadSignature, DemoShareLink.DoesNotExist, ValueError, TypeError, ValidationError):
        return None


def assessment_token(session):
    return signing.dumps(str(session.pk), salt="experience-assessment")


def attribute_assessment(request, consultation, lead):
    """Only called AFTER the visitor deliberately submits the real assessment form."""
    from core.models import DemoSession, DemoConversion, DemoEvent
    try:
        pk = signing.loads(request.POST.get("demo_ref", ""), salt="experience-assessment", max_age=7 * 86400)
        session = DemoSession.objects.select_related("revision__experience", "rep").get(pk=pk)
        # A copied assessment URL is attribution, never permission to access a transcript.
    except (signing.BadSignature, DemoSession.DoesNotExist, ValueError, TypeError, ValidationError):
        return
    rep = session.rep if session.rep and salesperson(session.rep) else None
    DemoConversion.objects.create(consultation=consultation, session=session, rep=rep,
        vertical=session.revision.experience.slug, scenario=session.scenario, source=session.source, revision=session.revision.version)
    lead.source = "AI Experience Center · Automotive"
    if rep:
        lead.assigned_to = rep
    lead.save(update_fields=["source", "assigned_to"])
    DemoEvent.objects.create(session=session, kind="assessment_requested")
