"""
Known-answer tests for the structured abstract digest (Task: match presentation redesign).

No live calls, no DB, no Gemini quota: urlopen is monkeypatched and the one function
that would touch Supabase (attach_pi_contacts) is stubbed to identity. Run from the
repo root:

    python -u backend/test_abstract_digest.py

The load-bearing cases are (1) sanitize_digest as the gate between model output and
what the frontend renders unchecked, and (2) the enrich_sliced_matches queueing split:
a brief abstract must queue expansion ONLY (never a digest of the brief text -- the
expansion task chains its own digest), and a card that already carries a digest must
queue nothing at all, or every deck load would re-burn a Gemini call per card.
"""
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import BackgroundTasks

from backend.config import settings
from backend.services import digest as digest_mod
from backend.services.digest import generate_abstract_digest, sanitize_digest
from backend.routers import grants as grants_mod
from backend.routers.grants import (
    enrich_sliced_matches,
    expand_and_store_abstract,
    format_match_card,
    generate_and_store_digest,
)

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}\n         got={got!r} want={want!r}", flush=True)
    if not ok:
        failures.append(label)


def check_true(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}", flush=True)
    if not cond:
        failures.append(label)


VALID_DIGEST = {
    "tldr": "This lab builds ML models that predict how proteins misfold in disease.",
    "project": ["Predict protein structures from sequence data."],
    "methods": ["PyTorch pipelines", "Cryo-EM datasets"],
    "lab_fit": ["Computational biochemistry; suits students with Python."],
}


print("\n=== 1. sanitize_digest ===", flush=True)
check("valid payload passes through", sanitize_digest(dict(VALID_DIGEST)), VALID_DIGEST)
check("non-dict refused", sanitize_digest("a string"), None)
check("missing tldr refused", sanitize_digest({k: v for k, v in VALID_DIGEST.items() if k != "tldr"}), None)
check("empty tldr refused", sanitize_digest({**VALID_DIGEST, "tldr": "   "}), None)
check("non-list bullets tolerated as empty",
      sanitize_digest({**VALID_DIGEST, "lab_fit": "not a list"}),
      {**VALID_DIGEST, "lab_fit": []})
check("empty project AND methods refused",
      sanitize_digest({**VALID_DIGEST, "project": [], "methods": []}), None)

capped = sanitize_digest({
    **VALID_DIGEST,
    "project": ["a", "b", "c", "d", "e"],
    "methods": ["1", "2", "3", "4", "5", "6"],
    "lab_fit": ["x", "y", "z"],
})
check("project capped at 3", len(capped["project"]), 3)
check("methods capped at 4", len(capped["methods"]), 4)
check("lab_fit capped at 2", len(capped["lab_fit"]), 2)

long_bullet = "w" * 500
trimmed = sanitize_digest({**VALID_DIGEST, "methods": [long_bullet, "  ", "ok"]})
check_true("overlong bullet truncated", len(trimmed["methods"][0]) <= digest_mod.MAX_BULLET_CHARS,
           f"len={len(trimmed['methods'][0])}")
check("whitespace-only bullet dropped", trimmed["methods"][1], "ok")
long_tldr = sanitize_digest({**VALID_DIGEST, "tldr": "t" * 500})
check_true("overlong tldr truncated", len(long_tldr["tldr"]) <= digest_mod.MAX_TLDR_CHARS,
           f"len={len(long_tldr['tldr'])}")


print("\n=== 2. generate_abstract_digest (urlopen mocked) ===", flush=True)

GRANT = {
    "grant_title": "Deep Learning for Protein Folding",
    "grant_abstract": "word " * 60,
    "pi_name": "Dr. Jane Smith",
    "university": "MIT",
    "funding_source": "NIH",
    "methodologies": ["Machine Learning", "Python"],
}


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return json.dumps(self._body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def gemini_body(digest_dict):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(digest_dict)}]}}]}


_real_urlopen = urllib.request.urlopen
_real_sleep = digest_mod.time.sleep
_real_key = settings.gemini_api_key
digest_mod.time.sleep = lambda *_a, **_k: None  # retries shouldn't slow the suite

try:
    settings.gemini_api_key = ""
    check("missing API key -> None (no HTTP)", generate_abstract_digest(GRANT), None)

    settings.gemini_api_key = "test-key"
    check("empty abstract -> None (no HTTP)",
          generate_abstract_digest({**GRANT, "grant_abstract": "  "}), None)

    calls = {"n": 0}

    def ok_urlopen(req, timeout=None):
        calls["n"] += 1
        return FakeResponse(200, gemini_body(VALID_DIGEST))

    urllib.request.urlopen = ok_urlopen
    check("canned 200 -> parsed digest", generate_abstract_digest(GRANT), VALID_DIGEST)
    check("single call on success", calls["n"], 1)

    calls["n"] = 0

    def failing_urlopen(req, timeout=None):
        calls["n"] += 1
        raise Exception("boom")

    urllib.request.urlopen = failing_urlopen
    check("3 raises -> None fallback, no exception", generate_abstract_digest(GRANT), None)
    check("retried exactly 3 times", calls["n"], 3)

    def junk_urlopen(req, timeout=None):
        return FakeResponse(200, gemini_body({"tldr": "", "project": [], "methods": [], "lab_fit": []}))

    urllib.request.urlopen = junk_urlopen
    check("200 but invalid shape -> None after retries", generate_abstract_digest(GRANT), None)
finally:
    urllib.request.urlopen = _real_urlopen
    digest_mod.time.sleep = _real_sleep
    settings.gemini_api_key = _real_key


print("\n=== 3. format_match_card serialization ===", flush=True)

BASE_GRANT_ROW = {
    "id": "g-1",
    "pi_name": "Dr. Jane Smith",
    "university": "MIT",
    "department": "Biochemistry",
    "grant_title": "Deep Learning for Protein Folding",
    "grant_abstract": "word " * 60,
    "funding_source": "NIH",
    "award_amount": 2400000,
    "methodologies": ["Machine Learning", "Python"],
    "start_date": "2025-01-01",
    "end_date": "2028-01-01",
    "abstract_is_generated": False,
    "award_id": "12345",
}


def card_for(row):
    return format_match_card(
        row,
        score=87,
        score_components={"semantic": 82, "keyword": 71, "campus_boost": 0},
        student_skills=["python"],
        student_roles=["Research Assistant"],
    )


check("digest dict rides through",
      card_for({**BASE_GRANT_ROW, "abstract_digest": VALID_DIGEST})["abstract_digest"], VALID_DIGEST)
check("garbage string -> None",
      card_for({**BASE_GRANT_ROW, "abstract_digest": "junk"})["abstract_digest"], None)
check("absent -> None", card_for(BASE_GRANT_ROW)["abstract_digest"], None)

card = card_for(BASE_GRANT_ROW)
for alias in ("university", "grant_title", "grant_abstract", "compatibility_score",
              "funding_source", "methodologies"):
    check_true(f"test-compat alias key present: {alias}", alias in card)


print("\n=== 4. enrich_sliced_matches queueing ===", flush=True)

# Stub the contact-enrichment tail so no Supabase client is needed.
_real_attach = grants_mod.attach_pi_contacts
grants_mod.attach_pi_contacts = lambda cards, db=None: cards
try:
    brief_card = card_for({**BASE_GRANT_ROW, "id": "g-brief",
                           "grant_abstract": "Too short."})            # < 25 words
    fresh_card = card_for({**BASE_GRANT_ROW, "id": "g-fresh"})          # long, no digest
    done_card = card_for({**BASE_GRANT_ROW, "id": "g-done",
                          "abstract_digest": VALID_DIGEST})             # long, has digest

    bg = BackgroundTasks()
    enrich_sliced_matches([brief_card, fresh_card, done_card], bg, ["python"])
    queued = [(t.func.__name__, t.args[0]) for t in bg.tasks]
    check("brief abstract queues expansion only",
          [q for q in queued if q[1] == "g-brief"], [("expand_and_store_abstract", "g-brief")])
    check("fresh abstract queues digest only",
          [q for q in queued if q[1] == "g-fresh"], [("generate_and_store_digest", "g-fresh")])
    check("card with digest queues nothing", [q for q in queued if q[1] == "g-done"], [])
    check("no extra tasks", len(queued), 2)

    # Digest task must receive the abstract text so no re-fetch is needed to generate.
    digest_task = next(t for t in bg.tasks if t.func.__name__ == "generate_and_store_digest")
    check("digest task carries the abstract text",
          digest_task.args[1].get("grant_abstract"), fresh_card["grant_abstract"])

    bg_none = BackgroundTasks()
    enrich_sliced_matches([fresh_card], None, ["python"])  # no task runner available
    check("no BackgroundTasks -> nothing queued, no crash", len(bg_none.tasks), 0)

    # The cap is what keeps a 12-card deck fetch from firing 12 Gemini calls at once.
    # It must bite on the TAIL: cards arrive score-sorted, so the budget goes to the
    # ones the student sees first.
    many = [card_for({**BASE_GRANT_ROW, "id": f"g-{i:02d}"}) for i in range(12)]
    bg_capped = BackgroundTasks()
    enrich_sliced_matches(many, bg_capped, ["python"])
    capped_ids = [t.args[0] for t in bg_capped.tasks if t.func.__name__ == "generate_and_store_digest"]
    check("digests capped per response", len(capped_ids), grants_mod.MAX_DIGESTS_PER_RESPONSE)
    check("cap keeps the top-ranked cards",
          capped_ids, [f"g-{i:02d}" for i in range(grants_mod.MAX_DIGESTS_PER_RESPONSE)])

    # Brief-abstract expansion is NOT capped: it's the older, rarer path and a brief
    # abstract is a worse defect than a missing digest.
    briefs = [card_for({**BASE_GRANT_ROW, "id": f"b-{i:02d}", "grant_abstract": "Too short."})
              for i in range(8)]
    bg_briefs = BackgroundTasks()
    enrich_sliced_matches(briefs, bg_briefs, ["python"])
    check("expansion not subject to the digest cap", len(bg_briefs.tasks), 8)
finally:
    grants_mod.attach_pi_contacts = _real_attach


print("\n" + "=" * 60, flush=True)
if failures:
    print(f"FAILED: {len(failures)} check(s):", flush=True)
    for f in failures:
        print(f"  - {f}", flush=True)
    sys.exit(1)
print("ALL CHECKS PASSED", flush=True)
