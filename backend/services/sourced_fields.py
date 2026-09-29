"""
Sourced card fields: the column list and the three agency-record mappers
(migration 20260928000019), plus the two text helpers they share with ingest.

Why this is its own module and not part of ingest.py: backfill_sourced_fields.py must
map a record exactly as ingest does, and it must not import Gemini or embedding code
(phase 3 addendum, section 6). ingest.py imports both at module level. Everything here
is pure: standard library only, no network, no database, no settings. ingest.py
re-exports every name below, so `from backend.services.ingest import NEW_COLUMNS,
map_nih_record, clean_abstract_html` keeps working and there is still one definition.
"""
import html
import re
from datetime import datetime, timezone
from typing import Optional


def clean_abstract_html(raw_html: str) -> str:

    """
    Remove HTML tags and unescape symbols from grant abstracts.
    """
    if not raw_html:
        return ""
    # Unescape HTML entities
    unescaped = html.unescape(raw_html)
    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', '', unescaped)
    # Replace multiple spaces/newlines
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def parse_nsf_date(date_str: str) -> str:
    """
    Convert NSF dates (MM/DD/YYYY) to ISO format (YYYY-MM-DD).
    """
    if not date_str:
        return None
    try:
        parts = date_str.split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[0]}-{parts[1]}"
    except Exception:
        pass
    return date_str


# ---------------------------------------------------------------------------
# One tuple names the columns and three mappers return exactly those keys, so that
#   * ingest and backend/backfill_sourced_fields.py cannot drift apart: both call the
#     same function on the same agency record;
#   * every row of a bulk upsert has identical keys. PostgREST rejects a page whose rows
#     differ in keys, which is how a partial deploy turns a nightly run into zero inserts.
# The order is the migration's column order and the phase 3 contract's.
# ---------------------------------------------------------------------------
NEW_COLUMNS: tuple = (
    "activity_code", "subproject_id", "project_num", "core_project_num", "fiscal_year",
    "public_statement", "agency_terms",
    "org_name_published", "org_city", "org_state", "org_dept_category",
    "pi_name_published", "pi_title", "pi_source_id", "co_pis",
    "funder_name", "funder_program",
    "source_is_active", "fields_fetched_at",
)
# Stamped by the ingest FETCHERS and process_single_grant, never by a mapper: a mapper
# sees one record and cannot know whether a comparison ran or whether the abstract that
# ends up stored is still the agency's.
INGEST_STAMP_COLUMNS: tuple = ("dates_checked_at", "abstract_checked_at")
# Written by backfill_sourced_fields.py only.
BACKFILL_ONLY_COLUMNS: tuple = ("award_not_found_at", "latest_appl_id")

# Every key the NIH mapper reads from a record. The backfill's key-presence guard uses
# this tuple plus the three it compares itself (award_amount, project_start_date,
# project_end_date). RePORTER drops things silently (see the "abstracttext" comment in
# ingest.fetch_nih_grants): a key that is ABSENT means the API did not send the field, and
# storing that as NULL under a fields_fetched_at stamp would turn a fetch failure into
# "NIH published nothing". A key present with a null value is a real "not published".
NIH_MAPPER_KEYS: tuple = (
    "appl_id", "activity_code", "subproject_id", "project_num", "core_project_num",
    "fiscal_year", "phr_text", "pref_terms", "principal_investigators", "organization",
    "agency_ic_admin", "is_active",
)
# NSF keys that must be PRESENT. coPDPI is deliberately not here: NSF omits the key on
# an award with no co-investigator (5 of the 6 records saved on 2026-09-28 have none),
# so its absence is an answer, not a dropped field.
NSF_MAPPER_KEYS: tuple = (
    "id", "pdPIName", "piId", "awardeeName", "awardeeCity", "awardeeStateCode",
    "orgLongName", "orgLongName2", "fundProgramName", "activeAwd",
)


def utc_now_iso() -> str:
    """UTC now as "2026-09-28T21:40:03+00:00". The one place a stamp is formatted, so
    ingest and the backfill write the same shape and a string comparison of two stamps
    orders them correctly."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text_or_none(value) -> Optional[str]:
    """Trimmed string, or None for a blank or a non-string. Blank is NULL everywhere in
    the new columns: an empty string would read as "the agency published an empty value",
    and NIH sends '' for a PI with no title."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _name_or_none(value) -> Optional[str]:
    """A person's name as published: runs of whitespace collapsed, trimmed, NEVER
    re-cased. clean_pi_name's .title() turns "McDONALD" into "Mcdonald" and "de la Cruz"
    into "De La Cruz"; that output stays in pi_name only because it is embedded."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _source_id(prefix: str, value) -> Optional[str]:
    """'nih:1858136' / 'nsf:269836067'. Namespaced because the two agencies number people
    independently and the card matches "other awards under this researcher" on this id
    alone. bool is refused explicitly: it is an int in Python and would become 'nih:True'."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return f"{prefix}:{value}"
    cleaned = _text_or_none(value)
    return f"{prefix}:{cleaned}" if cleaned else None


def amount_or_none(value) -> Optional[float]:
    """The agency's amount as a float, or None when it published none.

    This used to be `p.get("award_amount", 0)` followed by float(): a missing amount was
    stored as 0.0, a number the agency never published, and phase 1 had to teach the card
    that a stored 0 means "unknown". New rows store NULL instead. Rows written before
    this change still hold 0.0; the backfill reports them and does not rewrite them.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_new_columns() -> dict:
    return {k: None for k in NEW_COLUMNS}


def map_nih_record(p: dict, *, fetched_at: Optional[str] = None) -> dict:
    """The 19 NEW_COLUMNS from one NIH RePORTER project record.

    Pure: no network, no database, and no clock read when fetched_at is given. Never
    raises on a malformed record; a missing or wrongly typed value maps to None. Whether
    the KEYS were present at all is the caller's guard (NIH_MAPPER_KEYS), not this
    function's: map_nih_record({}) returns a stamp and 18 Nones, so a caller must not map
    a record it did not fetch.

    Text is copied, not improved. phr_text keeps its "PROJECT NARRATIVE" label and its
    line breaks (the label is stripped at read time, by offset, so the stored field stays
    the agency's bytes); names and institution are not re-cased.
    """
    out = _empty_new_columns()
    out["fields_fetched_at"] = fetched_at if fetched_at is not None else utc_now_iso()
    if not isinstance(p, dict):
        return out

    out["activity_code"] = _text_or_none(p.get("activity_code"))
    sub = p.get("subproject_id")
    # RePORTER sends the subproject id as a string today ('7679'); stringify a number so
    # the comparison that finds the newest record of the same component cannot miss on type.
    if isinstance(sub, int) and not isinstance(sub, bool):
        sub = str(sub)
    out["subproject_id"] = _text_or_none(sub)
    out["project_num"] = _text_or_none(p.get("project_num"))
    out["core_project_num"] = _text_or_none(p.get("core_project_num"))

    fy = p.get("fiscal_year")
    if isinstance(fy, int) and not isinstance(fy, bool):
        out["fiscal_year"] = fy
    elif isinstance(fy, str) and fy.strip().isdigit():
        out["fiscal_year"] = int(fy.strip())

    phr = p.get("phr_text")
    if isinstance(phr, str) and phr.strip():
        out["public_statement"] = phr  # verbatim: not trimmed, whitespace not collapsed

    terms = p.get("pref_terms")
    if isinstance(terms, str):
        split = [t.strip() for t in terms.split(";")]
        split = [t for t in split if t]
        # None, never []: an empty list would say "NIH assigned no terms", and we only
        # know the field was blank.
        out["agency_terms"] = split or None

    org = p.get("organization")
    if isinstance(org, dict):
        out["org_name_published"] = _text_or_none(org.get("org_name"))
        out["org_city"] = _text_or_none(org.get("org_city"))
        out["org_state"] = _text_or_none(org.get("org_state"))
        # NIH's department CATEGORY ("BIOCHEMISTRY", "PUBLIC HEALTH & PREV MEDICINE"), a
        # coding NIH applies across institutions. It is not the department's name.
        out["org_dept_category"] = _text_or_none(org.get("dept_type"))

    pis = p.get("principal_investigators")
    if isinstance(pis, list):
        people = [pi for pi in pis if isinstance(pi, dict)]
        # Same choice as fetch_nih_grants makes for pi_name: the contact PI, else the
        # first listed. The two must agree or the card names one person and links another.
        contact = next((pi for pi in people if pi.get("is_contact_pi")), people[0] if people else None)
        if contact is not None:
            out["pi_name_published"] = _name_or_none(contact.get("full_name"))
            out["pi_title"] = _text_or_none(contact.get("title"))
            out["pi_source_id"] = _source_id("nih", contact.get("profile_id"))
        co_pis = []
        for pi in people:
            if pi is contact:
                continue
            entry = {
                "name": _name_or_none(pi.get("full_name")),
                "title": _text_or_none(pi.get("title")),
                "source_id": _source_id("nih", pi.get("profile_id")),
            }
            if entry["name"] or entry["source_id"]:
                co_pis.append(entry)
        # [] = the list was there and held nobody else. None (above) = no list.
        out["co_pis"] = co_pis

    admin = p.get("agency_ic_admin")
    if isinstance(admin, dict):
        out["funder_name"] = _text_or_none(admin.get("name"))

    active = p.get("is_active")
    if isinstance(active, bool):
        # Stored as sent and read by nothing a student sees: for NIH this flag describes
        # one fiscal-year application record, not the project (migration 000019 header).
        out["source_is_active"] = active
    return out


def map_nsf_record(a: dict, *, fetched_at: Optional[str] = None) -> dict:
    """The 19 NEW_COLUMNS from one NSF award record. Same contract as map_nih_record.

    piEmail, pi and poEmail are not read, and the email NSF appends to each coPDPI string
    ("Ayana Arce atarce@phy.duke.edu") is removed: no email is stored by this phase.
    """
    out = _empty_new_columns()
    out["fields_fetched_at"] = fetched_at if fetched_at is not None else utc_now_iso()
    if not isinstance(a, dict):
        return out

    out["org_name_published"] = _text_or_none(a.get("awardeeName"))
    out["org_city"] = _text_or_none(a.get("awardeeCity"))
    out["org_state"] = _text_or_none(a.get("awardeeStateCode"))
    out["pi_name_published"] = _name_or_none(a.get("pdPIName"))
    out["pi_source_id"] = _source_id("nsf", a.get("piId"))

    if "coPDPI" in a:
        raw = a.get("coPDPI")
        if isinstance(raw, list):
            co_pis = []
            for item in raw:
                if not isinstance(item, str):
                    continue
                name = " ".join(tok for tok in item.split() if "@" not in tok)
                if name:
                    co_pis.append({"name": name, "title": None, "source_id": None})
            out["co_pis"] = co_pis
        # a null or wrongly typed value stays None
    elif _text_or_none(a.get("id")) is not None:
        # Absent key on a real record: NSF's way of saying "no co-investigator". Only on
        # a record that carries an award id, so that map_nsf_record({}) stays all-None.
        out["co_pis"] = []

    parts = [_text_or_none(a.get("orgLongName")), _text_or_none(a.get("orgLongName2"))]
    parts = [x for x in parts if x]
    out["funder_name"] = ", ".join(parts) or None
    out["funder_program"] = _text_or_none(a.get("fundProgramName"))

    active = a.get("activeAwd")
    if isinstance(active, bool):
        out["source_is_active"] = active
    elif isinstance(active, str) and active.strip().lower() in ("true", "false"):
        out["source_is_active"] = active.strip().lower() == "true"
    return out


def map_usaspending_record(r: dict, *, fetched_at: Optional[str] = None) -> dict:
    """All 19 NEW_COLUMNS as None, fields_fetched_at included, whatever it is given.

    spending_by_award publishes none of these fields, so there is nothing to map and
    nothing was "fetched": a stamp would let a card say "DOE published no award type"
    about a field DOE was never asked for. The function exists so the three sources put
    identical keys into one bulk upsert. fetched_at is accepted and ignored so the three
    signatures match.
    """
    return _empty_new_columns()


def has_keys(record, keys) -> bool:
    """True when every key is PRESENT in the record, whatever its value. A null value is
    an answer from the agency; an absent key is a field the API did not send."""
    return isinstance(record, dict) and all(k in record for k in keys)
