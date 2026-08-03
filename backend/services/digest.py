"""Structured AI digest of a grant abstract.

Turns the raw 250-700 word federal abstract into a scannable card section: one
plain-English TL;DR plus short bullet groups (what the project does, what a student
would work with, who the lab is looking for). Generated once per grant by Gemini,
persisted on labs_cached_grants.abstract_digest, and reused across all students.

Follows the two established LLM conventions in this codebase: structured JSON output
via responseSchema (routers/agent.py) and retry-with-backoff plus a silent non-LLM
fallback (services/ingest.expand_grant_abstract_via_llm). Returns None on any failure;
the card is then served without a digest and the frontend clamps the raw abstract.
"""
import json
import time
import urllib.request
import warnings
from typing import Optional

DIGEST_MODEL = "gemini-2.5-flash"

# Bullet caps per group, applied by sanitize_digest. Kept small on purpose: the digest
# is a 5-second scan aid, not a second abstract.
MAX_PROJECT_BULLETS = 3
MAX_METHODS_BULLETS = 4
MAX_LAB_FIT_BULLETS = 2
MAX_BULLET_CHARS = 220
MAX_TLDR_CHARS = 300

DIGEST_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tldr": {
            "type": "STRING",
            "description": (
                "One plain-English sentence (max ~160 characters) saying what this lab "
                "is doing, written for an undergraduate deciding in 5 seconds."
            ),
        },
        "project": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "1-3 short bullets: what the project does / is trying to find out.",
        },
        "methods": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "2-4 short bullets: concrete methods, tools, and techniques a student "
                "joining the lab would actually work with."
            ),
        },
        "lab_fit": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "1-2 short bullets: the lab's broader focus and what kind of student would thrive there.",
        },
    },
    "required": ["tldr", "project", "methods", "lab_fit"],
}


def _clean_bullets(raw, cap: int) -> list:
    """Non-empty trimmed strings only, truncated and capped. [] if raw isn't a list."""
    if not isinstance(raw, list):
        return []
    bullets = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        if len(text) > MAX_BULLET_CHARS:
            text = text[: MAX_BULLET_CHARS - 1].rstrip() + "…"
        bullets.append(text)
        if len(bullets) >= cap:
            break
    return bullets


def sanitize_digest(raw) -> Optional[dict]:
    """Validate and trim a model-produced digest. None if unusable.

    Only sanitized output is ever persisted: the schema constrains Gemini, but the
    stored shape is what the frontend renders unchecked, so this is the real gate.
    """
    if not isinstance(raw, dict):
        return None
    tldr = raw.get("tldr")
    if not isinstance(tldr, str) or not tldr.strip():
        return None
    tldr = tldr.strip()
    if len(tldr) > MAX_TLDR_CHARS:
        tldr = tldr[: MAX_TLDR_CHARS - 1].rstrip() + "…"

    project = _clean_bullets(raw.get("project"), MAX_PROJECT_BULLETS)
    methods = _clean_bullets(raw.get("methods"), MAX_METHODS_BULLETS)
    lab_fit = _clean_bullets(raw.get("lab_fit"), MAX_LAB_FIT_BULLETS)
    # A digest with a TL;DR but no bullets at all is still an improvement over the raw
    # dump, but an empty methods AND project section means the model produced filler.
    if not project and not methods:
        return None
    return {"tldr": tldr, "project": project, "methods": methods, "lab_fit": lab_fit}


def generate_abstract_digest(grant: dict) -> Optional[dict]:
    """Gemini structured digest of a grant abstract. None on any failure.

    `grant` carries grant_title, grant_abstract, pi_name, university, funding_source,
    methodologies -- the same normalized dict shape expand_grant_abstract_via_llm takes.
    """
    from ..config import settings
    if not settings.gemini_api_key:
        warnings.warn("GEMINI_API_KEY is not configured. Skipping abstract digest.")
        return None

    abstract = (grant.get("grant_abstract") or "").strip()
    if not abstract:
        return None
    title = grant.get("grant_title", "Untitled Research Project")
    pi_name = grant.get("pi_name", "Unknown Investigator")
    university = grant.get("university", "Unknown Institution")
    funding_source = grant.get("funding_source", "Federal Agency")
    methodologies = grant.get("methodologies") or []

    prompt = (
        "You are helping an undergraduate quickly understand a federal research grant. "
        "Summarize the abstract below into a structured digest.\n\n"
        f"Title: {title}\n"
        f"Principal Investigator: {pi_name}\n"
        f"Institution: {university}\n"
        f"Funding Agency: {funding_source}\n"
        f"Methodologies: {', '.join(methodologies) if methodologies else 'Not listed'}\n\n"
        f"Abstract:\n{abstract}\n\n"
        "Rules:\n"
        "- Plain English an undergraduate understands. Expand or drop jargon.\n"
        "- Do NOT invent facts that are not in the abstract or metadata above.\n"
        "- No hype, no adjectives like 'groundbreaking' or 'cutting-edge'.\n"
        "- tldr: ONE sentence, max ~160 characters, what this lab is doing.\n"
        "- project: 1-3 bullets, what the project does / is trying to find out.\n"
        "- methods: 2-4 bullets, concrete tools and techniques a student would work with.\n"
        "- lab_fit: 1-2 bullets, the lab's broader focus and who would thrive there.\n"
        "- Every bullet under ~15 words."
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{DIGEST_MODEL}"
        f":generateContent?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": DIGEST_RESPONSE_SCHEMA,
        },
    }

    max_retries = 3
    backoff = 2.0
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                if response.status != 200:
                    raise Exception(f"API returned status code {response.status}")
                res_body = json.loads(response.read().decode("utf-8"))
                candidates = res_body.get("candidates", [])
                if not candidates:
                    raise Exception("API returned 200 but candidates list is empty.")
                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts or not parts[0].get("text"):
                    raise Exception("API returned 200 but content text is empty.")
                digest = sanitize_digest(json.loads(parts[0]["text"]))
                if digest is not None:
                    return digest
                raise Exception("Model output failed digest validation.")
        except Exception as e:
            print(f"[Gemini Abstract Digest] Error on attempt {attempt + 1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 2.0

    warnings.warn("Failed to generate abstract digest via Gemini. Card serves without one.")
    return None
