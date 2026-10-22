"""Shared navigation and explicit search handoffs between lead sources."""
from urllib.parse import urlencode

from django.urls import reverse

from .directory_locations import city_and_state, US_STATES


def finder_url(source, values=None):
    values = values or {}
    allowed = {"industry", "state", "zip_code", "radius", "max_employees", "company_name", "company_id", "website", "page_size", "exclude_major_chains", "sort_order"}
    if source == "people":
        allowed.update({"job_title", "management_level", "person_name", "contact_details"})
    if source == "public":
        allowed = {"industry", "state", "exclude_major_chains"}
    params = {key: int(value) if isinstance(value, bool) else value for key, value in values.items()
              if key in allowed and value not in (None, "")}
    return reverse("lead_finder") + "?" + urlencode({"source": source, **params})


def source_tabs(source, values=None):
    shared = {k: v for k, v in (values or {}).items() if k != "sort_order"}
    return [{"key": key, "label": label, "description": description, "url": finder_url(key, shared), "active": key == source}
            for key, label, description in [
                ("companies", "Businesses", "ZoomInfo company search"),
                ("people", "Decision-makers", "ZoomInfo people search"),
                ("public", "Public listings", "Local directory search"),
            ]]


def public_to_zoominfo(batch):
    # ZoomInfo has no city-name search field. Explicitly offer statewide coverage
    # instead of silently dropping a city or sending unsupported criteria.
    try:
        _, state = city_and_state(batch.location)
    except ValueError:
        state = ""
    values = {"industry": batch.industry, "state": state, "exclude_major_chains": batch.exclude_major_chains}
    return {"url": finder_url("companies", values), "area": US_STATES.get(state, "the US")}
