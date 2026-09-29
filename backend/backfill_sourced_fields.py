"""
Backfill for the sourced card fields (migration 20260928000019_sourced_card_fields.sql).

Why this exists: run_grant_ingestion skips every title it has already seen, so a stored
row is never refreshed by the nightly run. The ~39,882 rows stored before phase 3 have
none of the new columns, and their dates and amounts are whatever the agency said on the
day they were ingested. This script re-reads each stored NIH or NSF award BY ITS AWARD
ID, maps it with the same functions ingest uses (services/sourced_fields.py), and
compares dates, amount and abstract with what we hold.

HOW TO RUN IT. From the root of the checkout that holds this file:

    /home/narmstrong/Lab-Match-AI/.venv/bin/python -u -m backend.backfill_sourced_fields --source nih --active-only --limit 200
    /home/narmstrong/Lab-Match-AI/.venv/bin/python -u -m backend.backfill_sourced_fields --source nsf --limit 20
    /home/narmstrong/Lab-Match-AI/.venv/bin/python -u -m backend.backfill_sourced_fields --source nih --active-only --apply

Credentials come from backend/.env (in the lab-fit worktree that file is a git-ignored
symlink to the production one, so THE DATABASE THIS TALKS TO IS PRODUCTION). Default is a
dry run: agency requests are made and stored rows are read by SELECT, nothing is written,
no log file is created. --apply writes. USAspending has no --source here: that API
publishes none of these fields.

This script imports no Gemini and no embedding code. It builds its own Supabase client
instead of importing backend.database, and takes the mappers from sourced_fields.py
instead of services/ingest.py, because both of those modules import the Gemini transport
at load time.

WHAT IT WILL NOT DO
  * write grant_abstract, abstract_is_generated, pi_name, pi_is_generated, grant_title,
    methodologies, embedding, university or any plain_summary* column;
  * overwrite a stored value with a null from the agency (counted and reported);
  * overwrite the stored abstract when the agency's differs (counted and reported);
  * treat "asked for and not returned" as "does not exist" without asking again, alone;
  * store anything from a record that is missing a KEY the mapper reads. RePORTER drops
    things without erroring (the "abstract" vs "abstracttext" trap in services/ingest.py).
    A key present with a null value is the agency saying "not published"; an absent key
    is a field we were not sent, and storing it would turn a fetch failure into "NIH
    published nothing". That aborts the run.

NIH is_active IS PER FISCAL-YEAR RECORD, NOT PER PROJECT (verified live 2026-09-28: appl
11182692, 5U54CA287392-03, FY2025, is_active=false, project end 2028-08-31; its FY2026
successor 11420337 is active). So when the stored appl_id's record is inactive and its
project end date is in the future, the newest record of the same core_project_num and
subproject_id is looked up, and dates, amount and fiscal year come from THAT record;
latest_appl_id records which. "Newest" is LabMatch's selection, not a federal field:
highest fiscal year above the stored record's, supplements (application type 3) left
out because their amount is an add-on and not the year's award, ties broken by the
higher appl_id. Two limits on that, both so that a figure never sits under a label it
does not belong to:
  * fiscal year and amount travel as a PAIR. When the newer record carries no amount,
    dates still come from it, and the amount and its fiscal year both stay the stored
    record's. (Details prints "$417,498, NIH funding for fiscal year 2026 only"; a
    FY2025 figure under that label is a number NIH never published for that year.)
  * a stored record that is ITSELF a supplement gets no newer-record lookup. The
    newest non-supplement record of its project is the parent's full-year award, and
    writing that over an add-on's amount would show the parent's money on the
    supplement's card. It is compared with its own record and counted in the report.

NOT FOUND. award_not_found_at takes a row out of every later run, so it is written
last and reluctantly: after the single-id confirmation, after the run-level share has
been computed WITH the current batch, and not at all during the first 200 ids, whose
stamps are held until the share is known. A run that ends before 200 ids writes its
held stamps only if they are within the 2 percent bound; otherwise it reports them and
leaves the rows for the next run. --recheck-not-found re-reads stamped rows and clears
the stamp of any the agency returns.

WRITES AND THE CHANGES LOG. The owner approved overwriting stored dates and amounts on
the condition that old and new are logged. So the log line is written and flushed
BEFORE the UPDATE is sent, the log file is opened before the first agency request of an
--apply run, and a log that cannot be written ends the run. A line marked
"about_to_write" with no later "write_failed" line for the same id is a change that
was made. Three failed database writes in a row end the run, like three failed agency
requests, and any failed write makes the exit code non-zero.

EXIT CODES. 0 done. 2 refused to start. 3 aborted by a guard. 4 finished with failed
database writes. 5 stopped because the clock reached the nightly window.

CONCURRENCY. Takes the same flock the nightly job takes (scripts/free_fill.sh,
logs/free_fill.lock in the PRODUCTION checkout) and refuses to start while it is held;
while this runs, a nightly run that starts will skip itself. For that reason the
02:30 to 09:00 window applies to DRY RUNS as well as --apply (a dry run writes nothing
and still holds the lock at 03:00), it is checked before every NIH batch and every NSF
award and not only at the start, and the start is refused when the span from now to
the estimated finish touches the window at all. --force-window switches all of it off.
"""
import argparse
import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from .services.sourced_fields import (
    NEW_COLUMNS, NIH_MAPPER_KEYS, NSF_MAPPER_KEYS,
    amount_or_none, clean_abstract_html, has_keys,
    map_nih_record, map_nsf_record, parse_nsf_date, utc_now_iso,
)

MIGRATION_FILE = "20260928000019_sourced_card_fields.sql"
REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"
NSF_URL = "https://api.nsf.gov/services/v1/awards.json"

# The lock scripts/free_fill.sh takes: REPO=/home/narmstrong/Lab-Match-AI, then
# "$REPO/logs/free_fill.lock". Absolute on purpose: this script is run from a worktree,
# and a path relative to the worktree would be a different file that excludes nobody.
# The environment override exists for the offline check of the refusal, nothing else.
PRODUCTION_LOCK_PATH = "/home/narmstrong/Lab-Match-AI/logs/free_fill.lock"
LOCK_ENV = "LABMATCH_FILL_LOCK"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGES_LOG = os.path.join(REPO_ROOT, "logs", "backfill_sourced_fields_changes.jsonl")

# Local time. The nightly cron fires at 03:00; 02:30 leaves it a clear start, and 09:00
# is past the longest run on record.
WINDOW_START = (2, 30)
WINDOW_END = (9, 0)

NIH_BATCH_DEFAULT = 100          # the size verified live against criteria.appl_ids
NSF_LIMIT_DEFAULT = 50
REQUEST_INTERVAL_SECONDS = 1.0   # one request per second, both agencies
CONFIRM_PAUSE_SECONDS = 2.0
MAX_CONSECUTIVE_FAILURES = 3
MAX_CONSECUTIVE_WRITE_FAILURES = 3
BATCH_NOT_FOUND_SHARE = 0.10     # addendum section 6
RUN_NOT_FOUND_SHARE = 0.02       # spec section E6, after the first 200 ids
RUN_NOT_FOUND_AFTER = 200
LOOKUP_CORES_PER_REQUEST = 25
LOOKUP_PAGE_SIZE = 500
LOOKUP_MAX_PAGES = 30
PRINTED_CHANGES_CAP = 60

# What the script itself reads from an NIH record, on top of what the mapper reads.
NIH_COMPARED_KEYS: tuple = ("award_amount", "project_start_date", "project_end_date", "abstract_text")
NIH_GUARD_KEYS: tuple = NIH_MAPPER_KEYS + NIH_COMPARED_KEYS
NIH_LOOKUP_KEYS: tuple = (
    "appl_id", "core_project_num", "subproject_id", "fiscal_year", "project_num",
    "award_type", "award_amount", "project_start_date", "project_end_date",
)
NSF_COMPARED_KEYS: tuple = ("startDate", "expDate", "fundsObligatedAmt")
NSF_GUARD_KEYS: tuple = NSF_MAPPER_KEYS + NSF_COMPARED_KEYS

# pi_name is read for one count in the report (published PI differs from the stored
# one). It is never written.
STORED_COLUMNS = (
    "id, award_id, funding_source, grant_title, grant_abstract, abstract_is_generated, "
    "start_date, end_date, award_amount, pi_name"
)
PROBE_COLUMNS: tuple = NEW_COLUMNS + (
    "dates_checked_at", "abstract_checked_at", "award_not_found_at", "latest_appl_id",
)


class Refused(Exception):
    """The run must not start (lock held, time window, missing migration with --apply)."""


class Abort(Exception):
    """A guard failed. Nothing further is requested or written."""


class RequestFailed(Exception):
    """One agency request failed (network, HTTP status, unreadable body)."""


class Stopped(Exception):
    """The clock reached the nightly window. Not a fault: what was done is reported and
    the rest is left for the next run."""


# ---------------------------------------------------------------------------
# Start conditions
# ---------------------------------------------------------------------------

def in_refusal_window(now: datetime) -> bool:
    minutes = now.hour * 60 + now.minute
    start = WINDOW_START[0] * 60 + WINDOW_START[1]
    end = WINDOW_END[0] * 60 + WINDOW_END[1]
    return start <= minutes < end


def span_touches_window(start: datetime, finish: datetime) -> bool:
    """True when any moment from start to finish lies inside the window. Looking at the
    finish alone let a run estimated from 01:00 to 09:30 through: 09:30 is outside."""
    if finish < start:
        finish = start
    if in_refusal_window(start) or in_refusal_window(finish):
        return True
    opens = start.replace(hour=WINDOW_START[0], minute=WINDOW_START[1], second=0, microsecond=0)
    if opens <= start:
        opens += timedelta(days=1)
    return opens <= finish


def check_time_window(now: datetime, *, apply: bool, force_window: bool) -> None:
    """`apply` only words the message. A dry run is refused too: it takes the same lock,
    and a lock held at 03:00 makes the nightly ingest skip that night."""
    if not force_window and in_refusal_window(now):
        raise Refused(
            f"{'--apply' if apply else 'dry run'} refused: it is {now.strftime('%H:%M')} local, "
            "inside the 02:30 to 09:00 window of the nightly ingest (cron at 03:00 takes the "
            "same lock and upserts the same table). Run it outside the window, or pass "
            "--force-window if the nightly job is known to be off."
        )


def acquire_lock(path: str) -> int:
    """Take the nightly job's flock, non-blocking. Returns the open descriptor, which the
    caller keeps open for the life of the run (closing it releases the lock).

    Opened read-only: flock does not need write access, and this way the file's content
    and mtime are untouched. Created only when it does not exist yet, which is what
    free_fill.sh's `exec 9>` does too.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o664)
        except OSError as e:
            raise Refused(f"cannot open the nightly job's lock file {path}: {e}")
    except OSError as e:
        raise Refused(f"cannot open the nightly job's lock file {path}: {e}")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise Refused(
            f"refused: {path} is held. The nightly ingest (or another backfill) is "
            "running against the same table. Try again when it has finished."
        )
    return fd


# ---------------------------------------------------------------------------
# Agency requests. Module-level callables so the offline checks can replace them.
# ---------------------------------------------------------------------------

def nih_search(payload: dict) -> dict:
    req = urllib.request.Request(
        REPORTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            if response.status != 200:
                raise RequestFailed(f"NIH RePORTER status {response.status}")
            body = json.loads(response.read().decode("utf-8"))
    except RequestFailed:
        raise
    except Exception as e:
        raise RequestFailed(f"NIH RePORTER request failed: {e}")
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise RequestFailed("NIH RePORTER answered without a results list")
    return body


def nsf_fetch(award_id: str) -> dict:
    # No printFields: the full record is what the mapper's keys are checked against.
    url = f"{NSF_URL}?id={urllib.parse.quote(str(award_id))}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            if response.status != 200:
                raise RequestFailed(f"NSF status {response.status}")
            body = json.loads(response.read().decode("utf-8"))
    except RequestFailed:
        raise
    except Exception as e:
        raise RequestFailed(f"NSF request failed: {e}")
    return body


class Throttle:
    """At most one request per REQUEST_INTERVAL_SECONDS, measured start to start."""

    def __init__(self, interval: float, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.interval = interval
        self.sleep = sleep
        self.clock = clock
        self.last: Optional[float] = None
        self.requests = 0

    def wait(self) -> None:
        now = self.clock()
        if self.last is not None:
            remaining = self.interval - (now - self.last)
            if remaining > 0:
                self.sleep(remaining)
        self.last = self.clock()
        self.requests += 1


# ---------------------------------------------------------------------------
# Guards (pure)
# ---------------------------------------------------------------------------

def missing_keys(record, keys) -> List[str]:
    if not isinstance(record, dict):
        return list(keys)
    return [k for k in keys if k not in record]


def check_nih_batch(asked: List[str], results: list) -> Tuple[Dict[str, dict], List[str]]:
    """({appl_id: record}, [ids asked for and not returned]) or Abort.

    Every check here is a way RePORTER could answer 200 with something other than what
    was asked: a criterion it ignored (ids outside the asked set, more rows than ids), or
    a field it dropped (a missing key).
    """
    asked_set = set(asked)
    if len(results) > len(asked):
        raise Abort(f"NIH returned {len(results)} records for {len(asked)} ids asked: "
                    "the appl_ids criterion was not applied as sent")
    found: Dict[str, dict] = {}
    for rec in results:
        gone = missing_keys(rec, NIH_GUARD_KEYS)
        if gone:
            ident = rec.get("appl_id") if isinstance(rec, dict) else None
            raise Abort(f"NIH record {ident} is missing key(s) {gone}: a dropped field "
                        "would be stored as 'not published'")
        appl = str(rec.get("appl_id"))
        if appl not in asked_set:
            raise Abort(f"NIH returned appl_id {appl}, which was not asked for: "
                        "the appl_ids criterion was not applied as sent")
        if appl in found:
            raise Abort(f"NIH returned appl_id {appl} twice in one batch")
        found[appl] = rec
    absent = [a for a in asked if a not in found]
    if asked and len(absent) / len(asked) > BATCH_NOT_FOUND_SHARE:
        raise Abort(f"{len(absent)} of {len(asked)} ids in one batch were not returned "
                    f"(more than {int(BATCH_NOT_FOUND_SHARE * 100)} percent): that is a failing "
                    f"request, not {len(absent)} awards that stopped existing")
    return found, absent


def check_nsf_response(asked_id: str, body) -> Optional[dict]:
    """The award record, None when NSF answered with an empty award list, or
    RequestFailed / Abort. A body without an `award` list is a failed request (NSF sends
    serviceNotification there), never a 'not found'."""
    response = body.get("response") if isinstance(body, dict) else None
    if not isinstance(response, dict) or not isinstance(response.get("award"), list):
        raise RequestFailed(f"NSF answered award {asked_id} without an award list")
    awards = response["award"]
    if not awards:
        return None
    if len(awards) > 1:
        raise Abort(f"NSF returned {len(awards)} awards for the single id {asked_id}")
    rec = awards[0]
    gone = missing_keys(rec, NSF_GUARD_KEYS)
    if gone:
        raise Abort(f"NSF award {asked_id} is missing key(s) {gone}: a dropped field "
                    "would be stored as 'not published'")
    if str(rec.get("id")) != str(asked_id):
        raise Abort(f"NSF returned award {rec.get('id')} for id {asked_id}")
    return rec


# ---------------------------------------------------------------------------
# NIH: the newest record of the same project (pure, except lookup_newer_records)
# ---------------------------------------------------------------------------

def iso_day(value) -> Optional[str]:
    """'2028-08-31T00:00:00' or '2028-08-31' -> '2028-08-31'. None when it is not a date."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    day = value[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    return day


def sub_key(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def needs_newer_lookup(record: dict, today: date) -> bool:
    """Inactive fiscal-year record whose project has not ended. `is False`, not falsy: a
    null is_active is 'not published', not 'inactive'."""
    if record.get("is_active") is not False:
        return False
    end = iso_day(record.get("project_end_date"))
    return end is not None and date.fromisoformat(end) > today


def is_supplement(record: dict) -> bool:
    award_type = str(record.get("award_type") or "").strip()
    project_num = str(record.get("project_num") or "").strip()
    return award_type == "3" or project_num[:1] == "3"


def pick_newest(stored: dict, candidates: List[dict]) -> Optional[dict]:
    """The newest record of the stored record's project and component, or None when none
    is newer than the stored one. Rule in the module docstring."""
    core = stored.get("core_project_num")
    fy = stored.get("fiscal_year")
    if not core or not isinstance(fy, int):
        return None
    sub = sub_key(stored.get("subproject_id"))
    best = None
    for rec in candidates:
        if rec.get("core_project_num") != core or sub_key(rec.get("subproject_id")) != sub:
            continue
        rec_fy = rec.get("fiscal_year")
        if not isinstance(rec_fy, int) or isinstance(rec_fy, bool) or rec_fy <= fy:
            continue
        if is_supplement(rec):
            continue
        try:
            key = (rec_fy, int(rec.get("appl_id")))
        except (TypeError, ValueError):
            continue
        if best is None or key > best[0]:
            best = (key, rec)
    return best[1] if best else None


def lookup_newer_records(stored_records: List[dict], *, search: Callable[[dict], dict],
                         throttle: Throttle, this_year: int) -> Tuple[Dict[str, List[dict]], Dict[str, str]]:
    """({core_project_num: [records]}, {core_project_num: why the lookup cannot be used}).

    One request per LOOKUP_CORES_PER_REQUEST projects rather than one per row. The
    fiscal_years range starts at the stored record's own year so the stored record itself
    must come back: a core whose stored appl_id is absent from a complete answer means the
    project_nums criterion did not match the way we assume, and that core is reported as
    unusable instead of being read as "no newer record".
    """
    by_core: Dict[str, List[dict]] = {}
    unusable: Dict[str, str] = {}
    usable = []
    for rec in stored_records:
        core = rec.get("core_project_num")
        fy = rec.get("fiscal_year")
        if not isinstance(core, str) or not core.strip():
            continue
        if not isinstance(fy, int) or isinstance(fy, bool):
            unusable[core] = "stored record has no fiscal year"
            continue
        usable.append(rec)

    cores = sorted({r["core_project_num"] for r in usable})
    for i in range(0, len(cores), LOOKUP_CORES_PER_REQUEST):
        chunk = cores[i:i + LOOKUP_CORES_PER_REQUEST]
        chunk_set = set(chunk)
        first_fy = min(r["fiscal_year"] for r in usable if r["core_project_num"] in chunk_set)
        years = list(range(first_fy, max(this_year + 1, first_fy) + 1))
        collected: List[dict] = []
        complete = False
        reason = None
        for page in range(LOOKUP_MAX_PAGES):
            payload = {
                "criteria": {"project_nums": chunk, "fiscal_years": years},
                "limit": LOOKUP_PAGE_SIZE,
                "offset": page * LOOKUP_PAGE_SIZE,
            }
            throttle.wait()
            try:
                body = search(payload)
            except RequestFailed as e:
                reason = f"request failed: {e}"
                break
            results = body["results"]
            for rec in results:
                gone = missing_keys(rec, NIH_LOOKUP_KEYS)
                if gone:
                    raise Abort(f"NIH project lookup: record is missing key(s) {gone}")
                if rec.get("core_project_num") not in chunk_set:
                    raise Abort(
                        f"NIH project lookup returned core_project_num "
                        f"{rec.get('core_project_num')!r}, which was not asked for: the "
                        "project_nums criterion was not applied as sent")
                if rec.get("fiscal_year") not in years:
                    raise Abort(
                        f"NIH project lookup returned fiscal year {rec.get('fiscal_year')!r} "
                        f"outside {years[0]} to {years[-1]}: the fiscal_years criterion was "
                        "not applied as sent")
            collected.extend(results)
            meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
            total = meta.get("total")
            if len(results) < LOOKUP_PAGE_SIZE or (isinstance(total, int) and len(collected) >= total):
                complete = True
                break
        if not complete:
            why = reason or f"more than {LOOKUP_MAX_PAGES * LOOKUP_PAGE_SIZE} records, not read to the end"
            for core in chunk:
                unusable[core] = why
            continue
        returned_ids = {str(r.get("appl_id")) for r in collected}
        for core in chunk:
            by_core[core] = [r for r in collected if r.get("core_project_num") == core]
        for rec in usable:
            core = rec["core_project_num"]
            if core in chunk_set and str(rec.get("appl_id")) not in returned_ids:
                unusable[core] = (f"the stored record {rec.get('appl_id')} was not among the "
                                  "records returned for its own project and year")
                by_core.pop(core, None)
    return by_core, unusable


# ---------------------------------------------------------------------------
# Comparison with the stored row (pure)
# ---------------------------------------------------------------------------

def same_amount(a, b) -> bool:
    fa, fb = amount_or_none(a), amount_or_none(b)
    if fa is None or fb is None:
        return fa is None and fb is None
    return abs(fa - fb) < 0.005


def compare_with_stored(row: dict, *, start: Optional[str], end: Optional[str],
                        amount: Optional[float]) -> dict:
    """What differs between the stored row and the agency's values.

    changes:      [{column, old, new}] where the agency's value is non-null and differs.
    agency_nulls: columns where the agency sent null and we hold a value. Never written.
    checked:      the agency returned a non-null end date, so the comparison means
                  something and dates_checked_at may be stamped.
    """
    changes, agency_nulls = [], []
    for column, new in (("start_date", start), ("end_date", end)):
        old = iso_day(row.get(column)) if row.get(column) is not None else None
        if new is None:
            if row.get(column) is not None:
                agency_nulls.append(column)
            continue
        if old != new:
            changes.append({"column": column, "old": row.get(column), "new": new})
    if amount is None:
        if row.get("award_amount") is not None:
            agency_nulls.append("award_amount")
    elif not same_amount(row.get("award_amount"), amount):
        changes.append({"column": "award_amount", "old": row.get("award_amount"), "new": amount})
    return {"changes": changes, "agency_nulls": agency_nulls, "checked": end is not None}


def abstract_verdict(row: dict, live_raw) -> str:
    """'equal' | 'mismatch' | 'agency_blank' | 'stored_generated' | 'stored_unknown'.

    Compared after clean_abstract_html, the cleaning ingest applied before it stored the
    text. A row flagged as generated is not compared: a mismatch there is expected and
    says nothing new. A row whose flag is unknown (NULL) is not stamped either.
    """
    flag = row.get("abstract_is_generated")
    if flag is True:
        return "stored_generated"
    if flag is not False:
        return "stored_unknown"
    live = clean_abstract_html(live_raw) if isinstance(live_raw, str) else ""
    if not live:
        return "agency_blank"
    return "equal" if live == (row.get("grant_abstract") or "") else "mismatch"


def newer_carries_amount(newer: Optional[dict]) -> bool:
    return newer is not None and amount_or_none(newer.get("award_amount")) is not None


def plan_row(row: dict, mapped: dict, *, start, end, amount, live_abstract, stamp: str,
             newer: Optional[dict] = None) -> dict:
    """The UPDATE for one row that the agency returned, and what to report about it.
    Pure: builds the payload, writes nothing.

    With a newer record, the caller passes that record's dates, and its amount ONLY when
    it has one (else the stored record's own amount). fiscal_year follows the amount
    here by the same test, so the two cannot come apart.
    """
    payload = {k: mapped.get(k) for k in NEW_COLUMNS}
    payload["latest_appl_id"] = None
    if newer is not None:
        # Contract 1.3: the stored record supplies the 19 columns; the newer record
        # supplies fiscal year, dates and amount. source_is_active stays the stored
        # record's value: it is that record's flag.
        if newer_carries_amount(newer):
            payload["fiscal_year"] = newer.get("fiscal_year")
        # Set either way: it says which record the DATES were read from.
        payload["latest_appl_id"] = str(newer.get("appl_id"))
    cmp = compare_with_stored(row, start=start, end=end, amount=amount)
    for change in cmp["changes"]:
        payload[change["column"]] = change["new"]
    if cmp["checked"]:
        payload["dates_checked_at"] = stamp
    verdict = abstract_verdict(row, live_abstract)
    if verdict == "equal":
        payload["abstract_checked_at"] = stamp
    return {"payload": payload, "compare": cmp, "abstract": verdict}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class Report:
    def __init__(self, source: str, apply: bool):
        self.source = source
        self.apply = apply
        self.selected = 0
        self.asked = 0
        self.returned = 0
        self.found_on_confirmation = 0
        self.not_found: List[str] = []
        self.unusable_ids: List[str] = []
        self.failed_requests = 0
        self.rows_skipped_by_failed_request = 0
        self.populated = {k: 0 for k in NEW_COLUMNS}
        self.planned = 0
        self.changes: List[dict] = []
        self.rows_with_date_change = 0
        self.rows_with_amount_change = 0
        self.agency_nulls = {"start_date": 0, "end_date": 0, "award_amount": 0}
        self.stored_zero_amount_agency_null = 0
        self.dates_checked = 0
        self.abstract = {"equal": 0, "mismatch": 0, "agency_blank": 0,
                         "stored_generated": 0, "stored_unknown": 0}
        self.abstract_mismatch_ids: List[str] = []
        self.inactive_records = 0
        self.needed_newer = 0
        self.newer_found = 0
        self.newer_none = 0
        self.newer_without_amount = 0
        self.stored_supplements = 0
        self.pi_name_differs: List[str] = []
        self.not_found_stamped = 0
        self.not_found_held: List[str] = []
        self.not_found_cleared = 0
        self.stopped: Optional[str] = None
        self.deferred: List[Tuple[str, str]] = []
        self.front = {"agency_sentence": 0, "needs_ai_one_liner": 0, "no_agency_text": 0}
        self.front_note: Optional[str] = None
        self.examples: List[dict] = []
        self.written = 0
        self.write_failures = 0
        self.aborted: Optional[str] = None

    def count_plan(self, row: dict, plan: dict) -> None:
        self.planned += 1
        payload = plan["payload"]
        for k in NEW_COLUMNS:
            if payload.get(k) is not None:
                self.populated[k] += 1
        cmp = plan["compare"]
        columns = {c["column"] for c in cmp["changes"]}
        if columns & {"start_date", "end_date"}:
            self.rows_with_date_change += 1
        if "award_amount" in columns:
            self.rows_with_amount_change += 1
        for c in cmp["changes"]:
            self.changes.append({"id": row.get("id"), "award_id": row.get("award_id"), **c})
        for col in cmp["agency_nulls"]:
            self.agency_nulls[col] += 1
            if col == "award_amount" and same_amount(row.get("award_amount"), 0):
                self.stored_zero_amount_agency_null += 1
        if cmp["checked"]:
            self.dates_checked += 1
        self.abstract[plan["abstract"]] += 1
        if plan["abstract"] == "mismatch":
            self.abstract_mismatch_ids.append(str(row.get("award_id")))
        if len(self.examples) < 3:
            self.examples.append({
                "id": row.get("id"), "award_id": row.get("award_id"),
                **{k: payload.get(k) for k in ("activity_code", "project_num", "fiscal_year",
                                               "org_name_published", "org_city", "org_state",
                                               "pi_name_published", "pi_title", "pi_source_id",
                                               "funder_name", "funder_program", "latest_appl_id")},
                "agency_terms_count": len(payload["agency_terms"]) if payload.get("agency_terms") else None,
                "public_statement_chars": len(payload["public_statement"]) if payload.get("public_statement") else None,
                "co_pis": payload.get("co_pis"),
            })

    def print(self, *, migration_applied: bool, requests: int) -> None:
        mode = "APPLY" if self.apply else "DRY RUN, nothing was written"
        print("")
        if not migration_applied:
            print(f"MIGRATION {MIGRATION_FILE} IS NOT APPLIED: rows were selected without the "
                  "fields_fetched_at / award_not_found_at predicates, so this sample includes "
                  "rows a real run would also select, and a re-run selects the same rows.")
        print(f"=== backfill_sourced_fields report: source {self.source.upper()}, {mode} ===")
        if self.aborted:
            print(f"ABORTED: {self.aborted}")
        if self.stopped:
            print(f"STOPPED, the rest is left for the next run: {self.stopped}")
        print(f"agency requests made:            {requests}")
        print(f"stored rows selected:            {self.selected}")
        if self.unusable_ids:
            print(f"  award_id unusable as an id:    {len(self.unusable_ids)}  {self.unusable_ids[:5]}")
        print(f"asked:                           {self.asked}")
        print(f"returned:                        {self.returned}")
        if self.found_on_confirmation:
            print(f"  of which on the confirmation:  {self.found_on_confirmation}")
        print(f"not found (confirmed, asked twice): {len(self.not_found)}  {self.not_found[:10]}")
        if self.apply:
            print(f"  award_not_found_at stamped:    {self.not_found_stamped}")
        if self.not_found_held:
            print(f"  NOT stamped, left for a later run: {len(self.not_found_held)}  "
                  f"{self.not_found_held[:10]} (the run ended before the not-found share "
                  "could be trusted, or the share was over the bound)")
        if self.not_found_cleared:
            print(f"  earlier not-found stamps cleared, the agency returned the award: "
                  f"{self.not_found_cleared}")
        print(f"failed requests:                 {self.failed_requests} "
              f"({self.rows_skipped_by_failed_request} rows left for a later run)")
        n = self.planned
        print(f"rows with a usable agency record: {n}")
        if self.source == "nih":
            print(f"  stored record is_active=false: {self.inactive_records}")
            print(f"  needed a newer-record lookup:  {self.needed_newer} "
                  "(inactive record, project end date in the future)")
            print(f"    newer record found:          {self.newer_found}")
            print(f"    none newer than the stored:  {self.newer_none}")
            print(f"    newer record has no amount:  {self.newer_without_amount} "
                  "(dates from the newer record; amount and fiscal year stay the stored record's)")
            print(f"  stored record is a supplement: {self.stored_supplements} "
                  "(no newer-record lookup; compared with its own record)")
            print(f"    deferred, lookup unusable:   {len(self.deferred)}")
            for ident, why in self.deferred[:5]:
                print(f"      {ident}: {why}")
        print("per-column population (non-null of rows with a usable record):")
        for k in NEW_COLUMNS:
            rate = f"{100.0 * self.populated[k] / n:5.1f}%" if n else "  n/a"
            print(f"  {k:<22} {self.populated[k]:>5} / {n:<5} {rate}")
        print(f"dates_checked_at would be stamped: {self.dates_checked} "
              "(agency returned a non-null end date)")
        print(f"rows whose start or end date differs: {self.rows_with_date_change}")
        print(f"rows whose amount differs:           {self.rows_with_amount_change}")
        print("agency sent null where we hold a value (never overwritten): "
              f"start_date {self.agency_nulls['start_date']}, end_date {self.agency_nulls['end_date']}, "
              f"award_amount {self.agency_nulls['award_amount']} "
              f"(of which stored amount is 0, an ingest stand-in: {self.stored_zero_amount_agency_null})")
        verb = "changed" if self.apply else "would change"
        shown = self.changes[:PRINTED_CHANGES_CAP]
        if shown:
            print(f"values that {verb} (old -> new):")
            for c in shown:
                print(f"  {c['award_id']:<12} {c['column']:<13} {c['old']!s:<14} -> {c['new']}")
            if len(self.changes) > len(shown):
                print(f"  ... and {len(self.changes) - len(shown)} more")
        a = self.abstract
        print(f"abstract compared with the agency's: equal {a['equal']}, MISMATCH {a['mismatch']}, "
              f"agency published none {a['agency_blank']}, not compared because the stored text is "
              f"flagged AI-generated {a['stored_generated']}, not compared because the flag is "
              f"unknown {a['stored_unknown']}")
        if self.abstract_mismatch_ids:
            print(f"  mismatching award ids (stored abstract NOT overwritten): {self.abstract_mismatch_ids[:20]}")
        print(f"published PI is not the stored pi_name's person: {len(self.pi_name_differs)}  "
              f"{self.pi_name_differs[:10]} (the card shows the published name; the lookup link "
              "and drafts use the stored one, so these cards do not offer outreach as primary)")
        if self.front_note:
            print(f"front sentence: NOT COUNTED ({self.front_note})")
        else:
            f = self.front
            print(f"front sentence: agency sentence qualifies {f['agency_sentence']}, "
                  f"would need an AI one-liner {f['needs_ai_one_liner']}, "
                  f"no agency text at all {f['no_agency_text']}")
        for ex in self.examples:
            print("example: " + json.dumps(ex, ensure_ascii=False, default=str))
        if self.apply:
            print(f"rows written: {self.written}, write failures: {self.write_failures}")
            if self.write_failures:
                print("  A failed write left its row as it was. Its 'about_to_write' lines in the "
                      "changes log are followed by a 'write_failed' line.")
            print(f"changes log: {CHANGES_LOG}")
        else:
            print("rows written: 0 (dry run)")


# ---------------------------------------------------------------------------
# Front-sentence count. Read-only use of the card's own rule, so the number printed here
# is the number of cards that will show an agency sentence, not an approximation of it.
# ---------------------------------------------------------------------------

def load_front_rule():
    try:
        from .services import front_sentence as fs
        return fs, None
    except Exception as e:  # module not written yet, or it fails to import
        return None, f"services/front_sentence.py could not be imported: {e}"


def count_front(report: Report, fs, row: dict, payload: dict, source: str) -> None:
    if fs is None or report.front_note:
        return
    card_row = {
        "funding_source": source.upper(),
        "grant_title": row.get("grant_title"),
        "grant_abstract": row.get("grant_abstract"),
        "abstract_is_generated": row.get("abstract_is_generated"),
        "public_statement": payload.get("public_statement"),
        "abstract_checked_at": payload.get("abstract_checked_at"),
        "plain_summary": None,
    }
    try:
        if fs.front_sentence(card_row) is not None:
            report.front["agency_sentence"] += 1
        elif fs.front_sentence_absent(card_row) == "none_qualifies":
            report.front["needs_ai_one_liner"] += 1
        else:
            report.front["no_agency_text"] += 1
    except Exception as e:
        report.front_note = f"services/front_sentence.py raised {type(e).__name__}: {e}"


def count_pi_difference(report: Report, row: dict, payload: dict) -> None:
    """Read-only use of the card's own test (services/card_front.py, a pure module), so
    the rows counted here are the rows whose card withholds the primary outreach button."""
    try:
        from .services.card_front import pi_names_conflict
        if pi_names_conflict(row.get("pi_name"), payload.get("pi_name_published")):
            report.pi_name_differs.append(str(row.get("award_id")))
    except Exception:
        # A count for the report. It must not decide whether a row is written.
        pass


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def connect():
    """A Supabase client built here, not imported from backend.database: that module
    loads the embedding code, which this script must not import."""
    from supabase import create_client
    from .config import settings
    if not settings.supabase_url or not settings.supabase_key:
        raise Refused("SUPABASE_URL / SUPABASE_KEY are not set. Run from the checkout root so "
                      "backend/.env is found.")
    return create_client(settings.supabase_url, settings.supabase_key)


def migration_applied(db) -> bool:
    try:
        db.table("labs_cached_grants").select(", ".join(PROBE_COLUMNS)).limit(1).execute()
        return True
    except Exception:
        return False


def base_query(db, args, *, has_columns: bool, columns: str, count: Optional[str] = None):
    q = db.table("labs_cached_grants")
    q = q.select(columns, count=count) if count else q.select(columns)
    q = q.eq("funding_source", args.source.upper()).not_.is_("award_id", "null")
    if has_columns and getattr(args, "recheck_not_found", False):
        # The stamped rows and only those. fields_fetched_at is NULL on all of them.
        q = q.not_.is_("award_not_found_at", "null")
    elif has_columns:
        q = q.is_("award_not_found_at", "null")
        if args.recheck_dates_before:
            q = q.lt("dates_checked_at", args.recheck_dates_before)
        else:
            q = q.is_("fields_fetched_at", "null")
    if args.active_only:
        q = q.gte("end_date", date.today().isoformat())
    return q


def count_rows(db, args, *, has_columns: bool) -> Optional[int]:
    try:
        res = base_query(db, args, has_columns=has_columns, columns="id", count="exact").limit(1).execute()
        return res.count
    except Exception:
        return None


def select_rows(db, args, *, has_columns: bool, last_id: Optional[str], n: int) -> List[dict]:
    """Keyset on id, never OFFSET: a finished row stops matching the predicate, so an
    OFFSET would skip the rows that slide into its place."""
    q = base_query(db, args, has_columns=has_columns, columns=STORED_COLUMNS)
    if last_id is not None:
        q = q.gt("id", last_id)
    return q.order("id").limit(n).execute().data or []


def write_row(db, row_id: str, payload: dict) -> None:
    db.table("labs_cached_grants").update(payload).eq("id", row_id).execute()


def check_changes_log() -> None:
    """Create and open the log for append, before any agency request. Refused when that
    fails: an --apply run that cannot record what it overwrites must not start."""
    try:
        os.makedirs(os.path.dirname(CHANGES_LOG), exist_ok=True)
        with open(CHANGES_LOG, "a", encoding="utf-8"):
            pass
    except OSError as e:
        raise Refused(f"--apply refused: the changes log {CHANGES_LOG} cannot be written ({e}). "
                      "No agency request was made and nothing was written.")


def log_changes(changes: List[dict]) -> None:
    """Append and force to disk. Raises OSError; the caller turns that into an Abort."""
    if not changes:
        return
    os.makedirs(os.path.dirname(CHANGES_LOG), exist_ok=True)
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        for c in changes:
            fh.write(json.dumps({"at": utc_now_iso(), **c}, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, db, args, report: Report, throttle: Throttle, *,
                 has_columns: bool, today: Optional[date] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], datetime] = datetime.now,
                 planned: Optional[int] = None):
        self.db = db
        self.args = args
        self.report = report
        self.throttle = throttle
        self.has_columns = has_columns
        self.today = today or date.today()
        self.sleep = sleep
        self.now = now
        self.planned = planned
        self.consecutive_failures = 0
        self.consecutive_write_failures = 0
        # (row, stamp) confirmed absent and not yet stamped. See write_not_found.
        self.held_not_found: List[Tuple[dict, str]] = []
        self.fs, note = load_front_rule()
        if note:
            report.front_note = note

    # -- shared ----------------------------------------------------------
    def request_failed(self, e: Exception, rows: int) -> None:
        self.report.failed_requests += 1
        self.report.rows_skipped_by_failed_request += rows
        self.consecutive_failures += 1
        print(f"  request failed: {e}")
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            raise Abort(f"{MAX_CONSECUTIVE_FAILURES} requests in a row failed")

    def check_clock(self) -> None:
        """Before every NIH batch and every NSF award. The start check alone let a run
        that was slower than its estimate go on writing at 03:00 with the lock held."""
        if getattr(self.args, "force_window", False):
            return
        now = self.now()
        if in_refusal_window(now):
            raise Stopped(f"it is {now.strftime('%H:%M')} local, inside the 02:30 to 09:00 "
                          "window of the nightly ingest")

    def check_pace(self, started: float, rows_done: int) -> None:
        """After the first NIH batch: the estimate printed at the start is a guess, this
        one is measured. Stops here, with one batch done, if the rest cannot finish
        before the window."""
        if getattr(self.args, "force_window", False) or not self.planned or not rows_done:
            return
        left = max(0, self.planned - rows_done)
        seconds = (time.monotonic() - started) / rows_done * left
        now = self.now()
        finish = now + timedelta(seconds=seconds)
        print(f"  measured pace: about {int(seconds // 60)} min {int(seconds % 60)} s for the "
              f"remaining {left} rows, finishing {finish.strftime('%Y-%m-%d %H:%M')} local")
        if span_touches_window(now, finish):
            raise Stopped("at the measured pace the run would reach the 02:30 to 09:00 "
                          "window of the nightly ingest")

    def not_found_share_exceeded(self) -> bool:
        r = self.report
        return bool(r.asked) and len(r.not_found) / r.asked > RUN_NOT_FOUND_SHARE

    def check_run_not_found(self) -> None:
        r = self.report
        if r.asked > RUN_NOT_FOUND_AFTER and self.not_found_share_exceeded():
            raise Abort(f"{len(r.not_found)} of {r.asked} ids confirmed not found, more than "
                        f"{int(RUN_NOT_FOUND_SHARE * 100)} percent")

    def write_failed(self, row: dict, e: Exception) -> None:
        self.report.write_failures += 1
        self.consecutive_write_failures += 1
        print(f"  write failed for {row.get('id')}: {e}")
        try:
            log_changes([{"event": "write_failed", "id": row.get("id"),
                          "award_id": row.get("award_id"), "error": str(e)[:300]}])
        except OSError:
            pass  # the run is about to end on the write failures or go on without this line
        if self.consecutive_write_failures >= MAX_CONSECUTIVE_WRITE_FAILURES:
            # The agency side has had this rule from the start. Without it a database
            # that was down let the NSF run ask for 8,187 awards at one a second, hold
            # the nightly lock for hours, write nothing and exit 0.
            raise Abort(f"{MAX_CONSECUTIVE_WRITE_FAILURES} database writes in a row failed")

    def commit(self, row: dict, plan: dict) -> None:
        self.report.count_plan(row, plan)
        count_front(self.report, self.fs, row, plan["payload"], self.args.source)
        count_pi_difference(self.report, row, plan["payload"])
        if not self.args.apply:
            return
        payload = dict(plan["payload"])
        if getattr(self.args, "recheck_not_found", False):
            payload["award_not_found_at"] = None
        changes = [{"event": "about_to_write", "id": row.get("id"), "award_id": row.get("award_id"),
                    "latest_appl_id": payload.get("latest_appl_id"), **c}
                   for c in plan["compare"]["changes"]]
        try:
            # BEFORE the UPDATE. Logged after it, a full disk or a kill between the two
            # calls left the stored value overwritten and recorded nowhere.
            log_changes(changes)
        except OSError as e:
            raise Abort(f"the changes log could not be written ({e}); row {row.get('id')} "
                        "was NOT updated")
        try:
            write_row(self.db, row["id"], payload)
        except Exception as e:
            self.write_failed(row, e)
            return
        self.consecutive_write_failures = 0
        self.report.written += 1
        if getattr(self.args, "recheck_not_found", False):
            self.report.not_found_cleared += 1

    def confirmed_not_found(self, row: dict, stamp: str) -> None:
        """Counted now, stamped later (write_not_found): the count is what the run-level
        guard is computed from, and the guard has to run before the stamp."""
        self.report.not_found.append(str(row.get("award_id")))
        self.held_not_found.append((row, stamp))

    def write_not_found(self, *, final: bool = False) -> None:
        """Stamp the held rows, if the share allows it.

        Called after check_run_not_found, so past the first 200 ids an over-the-bound
        share has already aborted the run with nothing of this batch stamped. Within
        the first 200 the stamps stay held. At the end of a run that never got that
        far (`final`), they are written only if they are within the bound; a small
        sample over it is reported and left alone.
        """
        if not self.held_not_found:
            return
        small = self.report.asked <= RUN_NOT_FOUND_AFTER
        if small and not final:
            return
        if small and self.not_found_share_exceeded():
            self.report.not_found_held.extend(str(r.get("award_id")) for r, _ in self.held_not_found)
            self.held_not_found = []
            return
        held, self.held_not_found = self.held_not_found, []
        if not self.args.apply:
            return
        for row, stamp in held:
            try:
                # fields_fetched_at stays NULL: the card says "not loaded yet", never
                # "not published", about an award we could not read.
                write_row(self.db, row["id"], {"award_not_found_at": stamp})
            except Exception as e:
                self.write_failed(row, e)
                continue
            self.consecutive_write_failures = 0
            self.report.written += 1
            self.report.not_found_stamped += 1

    def abandon_held(self) -> None:
        """The run is ending on an Abort or a Stop: nothing held is stamped."""
        self.report.not_found_held.extend(str(r.get("award_id")) for r, _ in self.held_not_found)
        self.held_not_found = []

    def batches(self, size: int):
        remaining = self.args.limit if self.args.limit else None
        last_id = None
        while remaining is None or remaining > 0:
            n = size if remaining is None else min(size, remaining)
            self.check_clock()
            try:
                rows = select_rows(self.db, self.args, has_columns=self.has_columns, last_id=last_id, n=n)
            except Exception as e:
                # Uncaught, this ended the run with a traceback and no report.
                raise Abort(f"the selection read failed: {e}")
            if not rows:
                return
            last_id = rows[-1]["id"]
            self.report.selected += len(rows)
            if remaining is not None:
                remaining -= len(rows)
            yield rows
            if len(rows) < n:
                return

    # -- NIH -------------------------------------------------------------
    def nih_request(self, ids: List[str]) -> dict:
        self.throttle.wait()
        return nih_search({
            "criteria": {"appl_ids": [int(i) for i in ids]},
            # Always sent. RePORTER's default page is smaller than a batch, and an
            # unsent limit would look like awards that do not exist.
            "limit": self.args.batch_size,
            "offset": 0,
        })

    def run_nih(self) -> None:
        started = time.monotonic()
        rows_done = 0
        for rows in self.batches(self.args.batch_size):
            if rows_done and rows_done <= self.args.batch_size:
                self.check_pace(started, rows_done)
            rows_done += len(rows)
            by_award: Dict[str, dict] = {}
            for row in rows:
                aid = str(row.get("award_id") or "").strip()
                if not aid.isdigit() or aid in by_award:
                    self.report.unusable_ids.append(aid)
                    continue
                by_award[aid] = row
            asked = list(by_award)
            if not asked:
                continue
            try:
                body = self.nih_request(asked)
            except RequestFailed as e:
                self.request_failed(e, len(asked))
                continue
            self.consecutive_failures = 0
            stamp = utc_now_iso()
            self.report.asked += len(asked)
            found, absent = check_nih_batch(asked, body["results"])
            self.report.returned += len(found)
            print(f"  batch: asked {len(asked)}, returned {len(found)}, absent {len(absent)}")

            confirmed_absent: List[str] = []
            for aid in absent:
                self.sleep(CONFIRM_PAUSE_SECONDS)
                try:
                    again = self.nih_request([aid])
                except RequestFailed as e:
                    # Unconfirmed: neither found nor not found. Left for a later run.
                    self.request_failed(e, 1)
                    continue
                self.consecutive_failures = 0
                confirmed, still_absent = check_nih_single(aid, again["results"])
                if confirmed is not None:
                    found[aid] = confirmed
                    self.report.returned += 1
                    self.report.found_on_confirmation += 1
                elif still_absent:
                    confirmed_absent.append(aid)

            # A stored supplement is never sent to the lookup (module docstring).
            self.report.stored_supplements += sum(1 for rec in found.values() if is_supplement(rec))
            need = [rec for rec in found.values()
                    if needs_newer_lookup(rec, self.today) and not is_supplement(rec)]
            self.report.inactive_records += sum(1 for rec in found.values() if rec.get("is_active") is False)
            self.report.needed_newer += len(need)
            by_core, unusable = ({}, {})
            if need:
                by_core, unusable = lookup_newer_records(
                    need, search=nih_search, throttle=self.throttle, this_year=self.today.year)

            # Every guard of this batch, the run-level not-found share included, is
            # evaluated before the first write of the batch. The share is computed with
            # this batch's confirmed absences counted and none of them stamped.
            for aid in confirmed_absent:
                self.confirmed_not_found(by_award[aid], stamp)
            self.check_run_not_found()
            self.write_not_found()

            for aid, rec in found.items():
                row = by_award[aid]
                newer = None
                if needs_newer_lookup(rec, self.today) and not is_supplement(rec):
                    core = rec.get("core_project_num")
                    if core in unusable or core not in by_core:
                        # Written in a later run. Storing this record's amount and year
                        # now would stamp a superseded fiscal year as checked.
                        self.report.deferred.append((aid, unusable.get(core, "no project number on the record")))
                        continue
                    newer = pick_newest(rec, by_core[core])
                    if newer is None:
                        self.report.newer_none += 1
                    else:
                        self.report.newer_found += 1
                source = newer if newer is not None else rec
                # The amount comes from the record whose fiscal year the row will carry.
                money = source if (newer is None or newer_carries_amount(newer)) else rec
                if newer is not None and money is rec:
                    self.report.newer_without_amount += 1
                plan = plan_row(
                    row, map_nih_record(rec, fetched_at=stamp),
                    start=iso_day(source.get("project_start_date")),
                    end=iso_day(source.get("project_end_date")),
                    amount=amount_or_none(money.get("award_amount")),
                    live_abstract=rec.get("abstract_text"),
                    stamp=stamp, newer=newer,
                )
                self.commit(row, plan)
        self.write_not_found(final=True)

    # -- NSF -------------------------------------------------------------
    def nsf_request(self, award_id: str) -> Optional[dict]:
        self.throttle.wait()
        return check_nsf_response(award_id, nsf_fetch(award_id))

    def run_nsf(self) -> None:
        for rows in self.batches(50):
            for row in rows:
                self.check_clock()
                aid = str(row.get("award_id") or "").strip()
                if not aid:
                    self.report.unusable_ids.append(aid)
                    continue
                try:
                    rec = self.nsf_request(aid)
                except RequestFailed as e:
                    self.request_failed(e, 1)
                    continue
                self.consecutive_failures = 0
                stamp = utc_now_iso()
                self.report.asked += 1
                if rec is None:
                    self.sleep(CONFIRM_PAUSE_SECONDS)
                    try:
                        rec = self.nsf_request(aid)
                    except RequestFailed as e:
                        self.request_failed(e, 1)
                        continue
                    self.consecutive_failures = 0
                    if rec is None:
                        self.confirmed_not_found(row, stamp)
                        self.check_run_not_found()
                        self.write_not_found()
                        continue
                    self.report.found_on_confirmation += 1
                self.report.returned += 1
                plan = plan_row(
                    row, map_nsf_record(rec, fetched_at=stamp),
                    start=iso_day(parse_nsf_date(rec.get("startDate"))),
                    end=iso_day(parse_nsf_date(rec.get("expDate"))),
                    # fundsObligatedAmt is the field ingest stores in award_amount.
                    amount=amount_or_none(rec.get("fundsObligatedAmt")),
                    live_abstract=rec.get("abstractText"),
                    stamp=stamp,
                )
                self.commit(row, plan)
        self.write_not_found(final=True)


def check_nih_single(asked_id: str, results: list) -> Tuple[Optional[dict], bool]:
    """(record, False) when the confirmation found it, (None, True) when it is absent
    again. Same guards as a batch, without the share rule (one of one is 100 percent)."""
    if len(results) > 1:
        raise Abort(f"NIH returned {len(results)} records for the single id {asked_id}")
    if not results:
        return None, True
    rec = results[0]
    gone = missing_keys(rec, NIH_GUARD_KEYS)
    if gone:
        raise Abort(f"NIH record {asked_id} is missing key(s) {gone}")
    if str(rec.get("appl_id")) != str(asked_id):
        raise Abort(f"NIH returned appl_id {rec.get('appl_id')} for the single id {asked_id}")
    return rec, False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m backend.backfill_sourced_fields",
        description="Re-read stored NIH/NSF awards and fill the sourced card fields. Dry run by default.")
    ap.add_argument("--source", required=True, choices=["nih", "nsf"])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run, nothing is written)")
    ap.add_argument("--limit", type=int, default=None,
                    help=f"rows to process; 0 = all. Default: all for nih, {NSF_LIMIT_DEFAULT} for nsf")
    ap.add_argument("--active-only", action="store_true", help="only rows with end_date >= today")
    ap.add_argument("--batch-size", type=int, default=NIH_BATCH_DEFAULT,
                    help="NIH ids per request (default 100, the size verified live)")
    ap.add_argument("--recheck-dates-before", metavar="DATE", default=None,
                    help="re-read rows whose dates_checked_at is older than DATE (YYYY-MM-DD)")
    ap.add_argument("--recheck-not-found", action="store_true",
                    help="re-read the rows stamped award_not_found_at, and clear the stamp of "
                         "any the agency returns")
    ap.add_argument("--force-window", action="store_true",
                    help="allow a run between 02:30 and 09:00 local time, and do not stop "
                         "when the clock reaches it")
    args = ap.parse_args(argv)
    if args.recheck_not_found and args.recheck_dates_before:
        ap.error("--recheck-not-found and --recheck-dates-before select different rows; pass one")
    if args.limit is None:
        args.limit = NSF_LIMIT_DEFAULT if args.source == "nsf" else 0
    if args.limit < 0:
        ap.error("--limit must be 0 or more")
    if not 1 <= args.batch_size <= 100:
        ap.error("--batch-size must be between 1 and 100")
    if args.recheck_dates_before:
        try:
            date.fromisoformat(args.recheck_dates_before)
        except ValueError:
            ap.error("--recheck-dates-before must be YYYY-MM-DD")
    return args


def estimate_seconds(source: str, rows: int, batch_size: int) -> float:
    """Rough, and said to be rough when printed. NSF: one request per award. NIH: the
    2026-09-28 dry run of 200 rows took about 4 seconds, two batch requests and the
    lookups they needed; the first figure written here (6 s a batch plus 16 s of lookups
    per 25 rows) put that run at 140 s and the whole corpus at three hours, which
    refused an evening run that would have taken minutes. Doubled from the measurement
    for slower nights. run_nih replaces it with a measured pace after its first batch."""
    if source == "nsf":
        return rows * 1.6
    batches = -(-rows // batch_size)
    return batches * 4.0


def main(argv=None) -> int:
    args = parse_args(argv)
    now = datetime.now()
    try:
        check_time_window(now, apply=args.apply, force_window=args.force_window)
        lock_fd = acquire_lock(os.environ.get(LOCK_ENV) or PRODUCTION_LOCK_PATH)
    except Refused as e:
        print(str(e))
        return 2

    try:
        try:
            db = connect()
        except Refused as e:
            print(str(e))
            return 2
        has_columns = migration_applied(db)
        if not has_columns and (args.apply or args.recheck_dates_before or args.recheck_not_found):
            print(f"refused: the columns of supabase/migrations/{MIGRATION_FILE} are not in the "
                  "database. Apply the migration first. No agency request was made.")
            return 2

        total = count_rows(db, args, has_columns=has_columns)
        planned = total if total is not None else None
        if planned is not None and args.limit:
            planned = min(planned, args.limit)
        print(f"source {args.source.upper()}, {'APPLY' if args.apply else 'dry run'}, "
              f"limit {args.limit or 'none'}, active-only {args.active_only}, "
              f"migration applied: {has_columns}")
        print(f"rows matching the selection: {total if total is not None else 'count failed'}; "
              f"this run will process up to {planned if planned is not None else args.limit or 'all'}")
        if planned:
            seconds = estimate_seconds(args.source, planned, args.batch_size)
            finish = now + timedelta(seconds=seconds)
            print(f"estimated finish: {finish.strftime('%Y-%m-%d %H:%M')} local "
                  f"(about {int(seconds // 60)} min {int(seconds % 60)} s; a rough figure)")
            if not args.force_window and span_touches_window(now, finish):
                print("refused: between now and the estimated finish the run would be inside the "
                      "02:30 to 09:00 window of the nightly ingest, holding its lock. Use a "
                      "smaller --limit, start earlier, or pass --force-window.")
                return 2
        if args.apply:
            try:
                check_changes_log()
            except Refused as e:
                print(str(e))
                return 2

        report = Report(args.source, args.apply)
        throttle = Throttle(REQUEST_INTERVAL_SECONDS)
        run = Run(db, args, report, throttle, has_columns=has_columns, planned=planned)
        code = 0
        try:
            if args.source == "nih":
                run.run_nih()
            else:
                run.run_nsf()
        except Abort as e:
            run.abandon_held()
            report.aborted = str(e)
            code = 3
        except Stopped as e:
            run.abandon_held()
            report.stopped = str(e)
            code = 5
        report.print(migration_applied=has_columns, requests=throttle.requests)
        if code == 0 and report.write_failures:
            code = 4
        return code
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
