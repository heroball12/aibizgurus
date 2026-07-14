import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from .intelligence import classify_sales_note, duplicate_fingerprint
from .models import Lead, LeadActivity, LeadImport


User = get_user_model()

CSV_ALIASES = {
    "name": ["name", "contact_name", "full_name", "person"],
    "business_name": ["business_name", "business", "company", "company_name", "organization", "agency_name", "dispensary_name", "lead_name"],
    "industry": ["industry", "category", "vertical"],
    "phone": ["phone", "phone_number", "mobile", "cell", "main_phone"],
    "email": ["email", "email_address"],
    "website": ["website", "web_site", "url", "site"],
    "address": ["address", "street", "street_address"],
    "city": ["city"],
    "state": ["state", "st"],
    "zip_code": ["zip", "zipcode", "zip_code", "postal_code"],
    "point_of_contact": ["poc", "point_of_contact", "contact_person", "contact", "decision_maker"],
    "contact_role": ["role", "contact_role", "title", "position"],
    "source": ["source", "lead_source"],
    "status": ["status", "stage", "outcome"],
    "notes": ["notes", "note", "comments", "description", "call_notes", "sdr_notes"],
    "value": ["value", "deal_value", "estimated_value"],
    "assigned_to": ["assigned_to", "assigned", "owner", "user", "sdr", "rep"],
    "follow_up_date": ["follow_up_date", "followup_date", "follow_up", "next_follow_up", "callback_date"],
    "last_contact": ["last_contact", "last_contacted", "last_call", "called_at"],
}

STATUS_VALUES = {choice[0] for choice in Lead.STATUS_CHOICES}
STATUS_LABELS = {
    label.lower().replace("-", "_").replace(" ", "_"): value
    for value, label in Lead.STATUS_CHOICES
}


@dataclass
class ParsedLeadRow:
    row_number: int
    source_sheet: str
    data: dict
    raw: dict = field(default_factory=dict)
    duplicate_detected: bool = False


@dataclass
class ImportParseResult:
    rows: list[ParsedLeadRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sheet_names: list[str] = field(default_factory=list)
    skipped_count: int = 0
    duplicate_count: int = 0


def csv_key(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def csv_value(row, field):
    for alias in CSV_ALIASES[field]:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def parse_decimal(value, row_number, errors):
    if not value:
        return Decimal("0")
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        errors.append(f"Row {row_number}: value must be a number.")
        return Decimal("0")


def parse_status(value, row_number, errors):
    if not value:
        return ""
    normalized = csv_key(value)
    if normalized in STATUS_VALUES:
        return normalized
    if normalized in STATUS_LABELS:
        return STATUS_LABELS[normalized]
    errors.append(f"Row {row_number}: status '{value}' is not valid.")
    return ""


def parse_date_value(value, row_number, errors, field_name="date"):
    if not value:
        return None
    parsed = parse_date(value)
    if not parsed:
        errors.append(f"Row {row_number}: {field_name} must be YYYY-MM-DD.")
    return parsed


def parse_assigned_to(value, row_number, errors):
    if not value:
        return None
    user = User.objects.filter(username=value).first() or User.objects.filter(email=value).first()
    if not user:
        errors.append(f"Row {row_number}: assigned_to user '{value}' was not found.")
    return user


def normalize_rows_from_dicts(dict_rows, source_sheet="CSV", starting_row=2):
    result = ImportParseResult(sheet_names=[source_sheet])
    for offset, raw_row in enumerate(dict_rows):
        row_number = starting_row + offset
        if row_number > 2501:
            result.errors.append("Import is limited to 2,500 rows at a time.")
            break
        row = {csv_key(key): str(value or "").strip() for key, value in raw_row.items() if key is not None}
        if not any(row.values()):
            result.skipped_count += 1
            continue
        parsed = build_parsed_row(row, row_number, source_sheet, result.errors)
        if parsed:
            result.rows.append(parsed)
    if not result.rows and not result.errors:
        result.errors.append("File did not contain any lead rows.")
    return result


def build_parsed_row(row, row_number, source_sheet, errors):
    name = csv_value(row, "name")
    business_name = csv_value(row, "business_name")
    email = csv_value(row, "email")
    phone = csv_value(row, "phone")
    website = csv_value(row, "website")
    address = csv_value(row, "address")
    notes = csv_value(row, "notes")
    imported_status = parse_status(csv_value(row, "status"), row_number, errors)

    if not any([name, business_name, email, phone]):
        errors.append(f"Row {row_number}: include at least one of name, business_name, email, or phone.")

    if email:
        try:
            validate_email(email)
        except ValidationError:
            errors.append(f"Row {row_number}: email '{email}' is not valid.")

    classification = classify_sales_note(notes, imported_status=imported_status)
    if notes and getattr(settings, "AI_SALES_INTELLIGENCE_ENABLED", False) and classification.confidence < Decimal("0.72"):
        classification = ai_enhance_classification(notes, classification)
    follow_up = parse_date_value(csv_value(row, "follow_up_date"), row_number, errors, "follow_up_date")
    if not follow_up:
        follow_up = classification.follow_up_date
    duplicate_key = duplicate_fingerprint(
        business_name=business_name,
        phone=phone,
        website=website,
        email=email,
        address=address,
    )
    duplicate_detected = bool(duplicate_key and Lead.objects.filter(lead_type="internal_sales", duplicate_key=duplicate_key).exists())
    if duplicate_detected:
        classification.status = "duplicate_review"
        classification.temperature = "cold"
        classification.needs_review = True

    final_status = imported_status if imported_status and imported_status not in {"new", "not_contacted"} else classification.status
    data = {
        "lead_type": "internal_sales",
        "client": None,
        "ai_instance": None,
        "name": name,
        "business_name": business_name,
        "industry": csv_value(row, "industry"),
        "phone": phone,
        "email": email,
        "website": website,
        "address": address,
        "city": csv_value(row, "city"),
        "state": csv_value(row, "state"),
        "zip_code": csv_value(row, "zip_code"),
        "point_of_contact": csv_value(row, "point_of_contact") or classification.contact_person,
        "contact_role": csv_value(row, "contact_role") or classification.contact_role,
        "source": csv_value(row, "source") or "Sales Intelligence Import",
        "source_file": "",
        "source_sheet": source_sheet,
        "status": final_status,
        "lead_temperature": classification.temperature,
        "notes": notes,
        "cleaned_notes": classification.cleaned_note,
        "value": parse_decimal(csv_value(row, "value"), row_number, errors),
        "assigned_to": parse_assigned_to(csv_value(row, "assigned_to"), row_number, errors),
        "follow_up_date": follow_up,
        "imported_at": timezone.now(),
        "last_contact_at": None,
        "classification_confidence": classification.confidence,
        "classification_source": classification.source,
        "needs_review": duplicate_detected or classification.needs_review,
        "duplicate_key": duplicate_key,
    }
    return ParsedLeadRow(row_number=row_number, source_sheet=source_sheet, data=data, raw=row, duplicate_detected=duplicate_detected)


def ai_enhance_classification(notes, fallback_classification):
    try:
        from assistant_ai.services import PlatformAIService
    except Exception:
        return fallback_classification

    schema_hint = {
        "status": "one valid CRM status slug",
        "temperature": "cold|warm|hot|closed",
        "cleaned_note": "professional CRM note",
        "confidence": "number from 0 to 1",
        "contact_role": "optional role",
        "needs_review": "boolean",
    }
    service = PlatformAIService(assistant_role="sdr_assistant")
    data, meta = service.structured_json(
        messages=[
            {"role": "system", "content": "Classify SDR call notes for AI Business Gurus. Preserve meaning, never invent details, and return strict JSON only."},
            {"role": "user", "content": notes[:1500]},
        ],
        schema_hint=schema_hint,
        fallback={},
        metadata={"feature": "sales_note_classification"},
    )
    if meta.get("status") != "success" or not data:
        return fallback_classification

    status = data.get("status")
    temperature = data.get("temperature")
    if status in STATUS_VALUES:
        fallback_classification.status = status
    if temperature in {"cold", "warm", "hot", "closed"}:
        fallback_classification.temperature = temperature
    if data.get("cleaned_note"):
        fallback_classification.cleaned_note = str(data["cleaned_note"])[:4000]
    try:
        fallback_classification.confidence = Decimal(str(data.get("confidence", fallback_classification.confidence))).quantize(Decimal("0.01"))
    except Exception:
        pass
    if data.get("contact_role"):
        fallback_classification.contact_role = str(data["contact_role"])[:120]
    if "needs_review" in data:
        fallback_classification.needs_review = bool(data["needs_review"])
    fallback_classification.source = "ai"
    return fallback_classification


def parse_csv_file(uploaded_file):
    try:
        text = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return ImportParseResult(errors=["CSV must be UTF-8 encoded."])
    try:
        reader = csv.DictReader(io.StringIO(text))
    except csv.Error as exc:
        return ImportParseResult(errors=[f"CSV could not be read: {exc}"])
    if not reader.fieldnames:
        return ImportParseResult(errors=["CSV must include a header row."])
    normalized_headers = [csv_key(header) for header in reader.fieldnames]
    if not any(alias in normalized_headers for aliases in CSV_ALIASES.values() for alias in aliases):
        return ImportParseResult(errors=["CSV headers were not recognized. Use headers like business_name, phone, email, notes, status."])
    return normalize_rows_from_dicts(reader, source_sheet="CSV", starting_row=2)


def _cell_index(cell_ref):
    letters = re.sub(r"[^A-Z]", "", (cell_ref or "").upper())
    total = 0
    for char in letters:
        total = total * 26 + (ord(char) - 64)
    return max(total - 1, 0)


def _text_from_node(node, ns):
    values = []
    for text_node in node.findall(".//main:t", ns):
        values.append(text_node.text or "")
    return "".join(values)


def _read_shared_strings(zf):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    return [_text_from_node(si, ns) for si in root.findall("main:si", ns)]


def _read_workbook_sheets(zf):
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pkg:Relationship", ns)
    }
    sheets = []
    for sheet in workbook.findall(".//main:sheet", ns):
        rel_id = sheet.attrib.get(f"{{{ns['rel']}}}id")
        target = rel_targets.get(rel_id, "")
        if target:
            clean_target = target.replace("../", "").lstrip("/")
            path = clean_target if clean_target.startswith("xl/") else f"xl/{clean_target}"
            if path not in zf.namelist():
                path = f"xl/{clean_target.removeprefix('xl/')}"
            sheets.append((sheet.attrib.get("name", "Sheet"), path))
    return sheets


def _read_xlsx_sheet(zf, path, shared_strings):
    root = ET.fromstring(zf.read(path))
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows = []
    for row_node in root.findall(".//main:sheetData/main:row", ns):
        values = []
        for cell in row_node.findall("main:c", ns):
            index = _cell_index(cell.attrib.get("r", "A1"))
            while len(values) <= index:
                values.append("")
            cell_type = cell.attrib.get("t")
            if cell_type == "s":
                raw_index = cell.findtext("main:v", default="", namespaces=ns)
                try:
                    values[index] = shared_strings[int(raw_index)]
                except (ValueError, IndexError):
                    values[index] = ""
            elif cell_type == "inlineStr":
                values[index] = _text_from_node(cell, ns)
            else:
                values[index] = cell.findtext("main:v", default="", namespaces=ns) or ""
        if any(str(value).strip() for value in values):
            rows.append(values)
    return rows


def _find_header_row(rows):
    for index, row in enumerate(rows[:15]):
        normalized = {csv_key(value) for value in row}
        matches = sum(1 for aliases in CSV_ALIASES.values() if any(alias in normalized for alias in aliases))
        if matches >= 1 and ("business_name" in normalized or "business" in normalized or "company" in normalized or "phone" in normalized or "notes" in normalized):
            return index
    return None


def parse_xlsx_file(uploaded_file, selected_sheet=""):
    try:
        workbook_bytes = uploaded_file.read()
        zf = zipfile.ZipFile(io.BytesIO(workbook_bytes))
    except zipfile.BadZipFile:
        return ImportParseResult(errors=["Excel file could not be read. Upload a valid .xlsx workbook."])

    result = ImportParseResult()
    shared_strings = _read_shared_strings(zf)
    sheets = _read_workbook_sheets(zf)
    if not sheets:
        return ImportParseResult(errors=["Excel workbook does not contain readable worksheets."])

    selected_sheet = (selected_sheet or "").strip()
    for sheet_name, path in sheets:
        if selected_sheet and sheet_name != selected_sheet:
            continue
        rows = _read_xlsx_sheet(zf, path, shared_strings)
        if not rows:
            continue
        result.sheet_names.append(sheet_name)
        header_index = _find_header_row(rows)
        if header_index is None:
            result.skipped_count += len(rows)
            result.errors.append(f"Sheet '{sheet_name}': no recognizable header row found.")
            continue
        headers = [csv_key(value) for value in rows[header_index]]
        dict_rows = []
        for values in rows[header_index + 1:]:
            row = {headers[i]: values[i] if i < len(values) else "" for i in range(len(headers)) if headers[i]}
            dict_rows.append(row)
        parsed = normalize_rows_from_dicts(dict_rows, source_sheet=sheet_name, starting_row=header_index + 2)
        result.rows.extend(parsed.rows)
        result.errors.extend(parsed.errors)
        result.skipped_count += parsed.skipped_count
        result.duplicate_count += parsed.duplicate_count

    if selected_sheet and not result.sheet_names:
        result.errors.append(f"Sheet '{selected_sheet}' was not found.")
    if not result.rows and not result.errors:
        result.errors.append("Excel workbook did not contain any importable lead rows.")
    return result


def parse_lead_file(uploaded_file, selected_sheet=""):
    filename = uploaded_file.name.lower()
    if filename.endswith(".csv"):
        return parse_csv_file(uploaded_file)
    if filename.endswith(".xlsx"):
        return parse_xlsx_file(uploaded_file, selected_sheet=selected_sheet)
    return ImportParseResult(errors=["Unsupported file type. Upload .csv or .xlsx."])


def import_lead_file(uploaded_file, *, uploaded_by=None, selected_sheet=""):
    original_filename = uploaded_file.name
    file_type = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "csv"
    parsed = parse_lead_file(uploaded_file, selected_sheet=selected_sheet)
    if parsed.errors:
        return None, parsed

    existing_keys = set(
        Lead.objects.filter(lead_type="internal_sales")
        .exclude(duplicate_key="")
        .values_list("duplicate_key", flat=True)
    )
    import_seen = set()
    duplicate_count = 0
    for row in parsed.rows:
        row.data["source_file"] = original_filename
        key = row.data.get("duplicate_key", "")
        if key and (key in existing_keys or key in import_seen):
            row.data["status"] = "duplicate_review"
            row.data["needs_review"] = True
            row.duplicate_detected = True
            duplicate_count += 1
        if key:
            import_seen.add(key)
    parsed.duplicate_count = duplicate_count

    with transaction.atomic():
        lead_import = LeadImport.objects.create(
            original_filename=original_filename[:255],
            uploaded_by=uploaded_by,
            file_type=file_type,
            sheet_names=parsed.sheet_names,
            row_count=len(parsed.rows) + parsed.skipped_count,
            imported_count=len(parsed.rows),
            skipped_count=parsed.skipped_count,
            duplicate_count=duplicate_count,
            error_count=0,
            notes_analyzed_count=sum(1 for row in parsed.rows if row.data.get("notes")),
            high_confidence_count=sum(1 for row in parsed.rows if row.data.get("classification_confidence", 0) >= Decimal("0.80")),
            review_count=sum(1 for row in parsed.rows if row.data.get("needs_review")),
            status="needs_review" if any(row.data.get("needs_review") for row in parsed.rows) else "processed",
            import_summary={
                "sheets": parsed.sheet_names,
                "duplicates": duplicate_count,
                "classification": "rule-first with optional AI extension",
            },
        )
        leads = [Lead.objects.create(**row.data) for row in parsed.rows]
        activities = []
        for lead, row in zip(leads, parsed.rows):
            activities.append(LeadActivity(
                lead=lead,
                user=uploaded_by,
                raw_note=row.data.get("notes", ""),
                cleaned_note=row.data.get("cleaned_notes", ""),
                inferred_status=row.data.get("status", "new"),
                lead_temperature=row.data.get("lead_temperature", "cold"),
                confidence_score=row.data.get("classification_confidence", Decimal("0")),
                contact_person=row.data.get("point_of_contact", ""),
                contact_role=row.data.get("contact_role", ""),
                activity_type="imported_note",
                call_outcome=row.data.get("status", "new"),
                follow_up_date=row.data.get("follow_up_date"),
                classification_source=row.data.get("classification_source", "rule"),
                original_import=lead_import,
                original_row_number=row.row_number,
                metadata={"source_sheet": row.source_sheet, "duplicate_detected": row.duplicate_detected},
            ))
        LeadActivity.objects.bulk_create(activities)
    return lead_import, parsed
