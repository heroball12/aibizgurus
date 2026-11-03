"""Save selected, server-owned search results without another provider request."""
import csv
import hashlib
import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from . import zoominfo_api as api
from .importers import import_lead_file
from .models import LeadImport, ZoomInfoSearch


def search_csv(kind, results):
    rows = []
    for result in results:
        raw = result.get("raw") or {}
        attrs = raw.get("attributes") or {}
        if not isinstance(attrs, dict):
            raise ValueError("This result has incomplete source data. Run a new search.")
        company = attrs if kind == "companies" else attrs.get("company") or {}
        if not isinstance(company, dict):
            raise ValueError("This result has incomplete company data. Run a new search.")
        row = {
            "ZoomInfo Record Type": "Company" if kind == "companies" else "Person",
            "ZoomInfo Contact ID": result["id"] if kind == "people" else "",
            "First Name": "", "Last Name": "",
        }
        if kind == "people":
            row.update({label: api.text_cell(attrs.get(field)) for field, label in api.CONTACT_MAP.items()})
        row.update({label: api.text_cell(company.get(field)) for field, label in api.COMPANY_MAP.items()})
        row["ZoomInfo Company ID"] = result["id"] if kind == "companies" else result.get("company_id", "")
        row["Company Name"] = row["Company Name"] or result.get("company", "") or (result.get("name", "") if kind == "companies" else "")
        row["Website"] = row["Website"] or result.get("website", "")
        row["ZoomInfo API search result"] = json.dumps(raw, ensure_ascii=False)
        row["ZoomInfo API company response"] = json.dumps(company, ensure_ascii=False)
        rows.append(row)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


@transaction.atomic
def save_results(run, ids, *, user, assignee, manager=False):
    # Serialize repeat clicks on this search. The normal importer also matches
    # stable provider IDs across different searches and later enrichment.
    run = ZoomInfoSearch.objects.select_for_update().get(pk=run.pk, user=user)
    fingerprint = hashlib.sha256(json.dumps([str(run.pk), sorted(ids), getattr(assignee, "pk", None)]).encode()).hexdigest()
    previous = LeadImport.objects.filter(uploaded_by=user, import_summary__zoominfo_selection=fingerprint).first()
    if previous:
        return previous, False
    chosen = [row for row in run.results if row["id"] in ids]
    upload = SimpleUploadedFile("zoominfo-search-results.csv", search_csv(run.kind, chosen))
    imported, parsed = import_lead_file(
        upload, uploaded_by=user, default_assigned_to=assignee,
        force_assigned_to=None if manager else user,
        protect_existing_assignees_for=None if manager else user,
    )
    if parsed.errors:
        raise ValueError("These results could not be saved. " + " ".join(parsed.errors[:2]))
    imported.import_summary = {**imported.import_summary, "zoominfo_selection": fingerprint, "zoominfo_search": str(run.pk)}
    imported.save(update_fields=["import_summary"])
    return imported, True
