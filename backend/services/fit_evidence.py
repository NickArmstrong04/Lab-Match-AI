"""Extractive fit evidence: which of the student's own terms appear, word for word, in
the text we hold for an award, and the sentence each one appears in.

Pure module. No network, no database, no LLM, and no import from the rest of the
backend, so it can be exercised with sockets blocked and hand-built rows.

Why it exists (phase 2): the card used to explain fit with "Skills you match" and
"Skills to grow", both computed against `methodologies`, which is our own substring
scan of the award text. Those read as the lab's requirements and no award record states
any. The owner's decision is that an explanation of fit is EXTRACTIVE ONLY: nothing
here writes a sentence. Every `sentence` returned is an exact, unaltered substring of
the stored `grant_title` or `grant_abstract`. That is the invariant; a long sentence is
shortened by choosing a narrower substring and saying so in two boolean fields, never by
editing the text or appending an ellipsis to it.

Evidence is display only. Nothing here feeds the score or the order of the deck.

`methodologies` is never searched: those tags are artifacts of a substring scan (a tag
could be set by a hit inside a longer word), so a "match" against them would be a match
against our own guess.
"""
import re
from typing import Dict, Iterable, List, Optional, Tuple

# Longest quoted span, in characters. A card holds several rows and an NIH abstract
# sentence can run past 600 characters.
MAX_SENTENCE_CHARS = 300

BASIS_HELD_AS_PUBLISHED = "held_as_published"
BASIS_FEDERAL_DESCRIPTION_ONLY = "federal_description_only"
BASIS_LLM_GENERATED = "llm_generated"
BASIS_SAMPLE = "sample"

# A full stop after one of these is not the end of a sentence. Without the list,
# "et al. 2019" and "Dr. Smith" each cut a quote in half. The quote would still be
# verbatim, but it would be a fragment shown with both truncation flags false.
_ABBREVIATIONS = frozenset({
    "dr", "prof", "mr", "mrs", "ms", "st", "fig", "figs", "eq", "ref", "refs", "no",
    "vs", "al", "etc", "inc", "ltd", "co", "approx", "ca", "cf", "e.g", "i.e", "u.s",
    "ph.d", "m.d", "jr", "sr",
})

# Sentence-final punctuation, any closing quote or bracket, then whitespace. Also a
# blank line, which separates paragraphs that do not end in punctuation (headings such
# as "PROJECT SUMMARY"). A single newline is NOT a boundary: stored abstracts are often
# hard-wrapped mid-sentence.
#
# Written so that one pass over the text is linear. Two earlier shapes were not:
#   - the punctuation run had no lookbehind, so inside "......" the engine retried from
#     every dot. A retry from the middle of a run can only fail where the first one did
#     (same tail), so `(?<![.!?])` drops them without changing any match.
#   - the blank-line branch began with `[ \t]*`, which rescanned a long run of spaces
#     from each of its characters. The boundary now starts at the first newline; the
#     spaces before it are trailing whitespace of the sentence, and locate_term strips
#     those anyway, so every quoted substring is the same as before.
_BOUNDARY_RE = re.compile(r"(?P<punct>(?<![.!?])[.!?]+[\"'”’)\]]*)(?P<gap>\s+)|(?P<para>\n[ \t]*\n\s*)")

# How far back from a full stop the word before it is read. The longest listed
# abbreviation is 5 characters; a word that runs past this is neither an abbreviation
# nor an initial, so it never needs to be read whole.
_TOKEN_LOOKBACK = 40


def normalise_text(value) -> str:
    """Lowercased, whitespace-collapsed form used ONLY to compare abstract with title."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).casefold()


def text_provenance(row: dict) -> str:
    """What the stored abstract is, decided at READ time from the row itself.

    Never stored. expand_brief_abstracts.py, recover_unknown_pis.py and the write-back
    helpers in routers/grants.py all rewrite grant_abstract; a verdict saved in a column
    would go stale the first time one of them ran, and LLM text would then be quoted as
    the agency's words.

      abstract_is_generated false           held_as_published
      true, abstract is the title again     federal_description_only
      true otherwise                        llm_generated

    "held_as_published" is deliberately not "verbatim". backfill_abstract_provenance.py
    leaves undecided rows FALSE, so FALSE means "recorded as published", not "re-checked
    against the agency". The card says so, and quotation marks wait for phase 3.

    An empty abstract on a generated row is reported as llm_generated, not as
    federal_description_only: with no abstract at all there is no "short description
    the agency published" to point at, and the llm_generated wording ("nothing to
    quote") is the one that is true.
    """
    row = row or {}
    if not row.get("abstract_is_generated"):
        return BASIS_HELD_AS_PUBLISHED
    abstract = normalise_text(row.get("grant_abstract"))
    if abstract and abstract == normalise_text(row.get("grant_title")):
        return BASIS_FEDERAL_DESCRIPTION_ONLY
    return BASIS_LLM_GENERATED


def clean_term(value) -> str:
    """Trimmed, inner whitespace collapsed. "" for anything that is not a usable term."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def term_key(value) -> str:
    """Identity of a term for de-duplication: case-insensitive, whitespace-insensitive."""
    return clean_term(value).casefold()


def term_is_case_sensitive(term: str) -> bool:
    """True for a term of 3 characters or fewer, or one written in all capitals.

    Short terms and acronyms are where case-insensitive matching goes wrong: "AI"
    against "ai", "CAD" against "cad", "DOE" against the surname "Doe", "R" against any
    "r". Such a term has to appear exactly as the student's profile spells it.
    """
    t = clean_term(term)
    if not t:
        return False
    if len(t) <= 3:
        return True
    # upper() == t alone is also true of "12345" and of scripts without case, so
    # require that lowering changes something.
    return t == t.upper() and t != t.lower()


def compile_term_pattern(term: str, *, case_insensitive: Optional[bool] = None):
    """Whole-word pattern for `term`, or None when the term is empty.

    The term is escaped, so "C++", "5-HT" and "p53" are literals. \\b is not used: it
    needs a word character on one side, so it can never match after the "+" of "C++".
    The lookarounds say the same thing without that flaw: the match may not be preceded
    or followed by a letter, digit or underscore. "ROS" therefore does not match inside
    "microscope" or "ROS1".

    Whitespace inside a term matches any run of whitespace, because stored abstracts
    are hard-wrapped and "machine\\nlearning" is still the phrase.

    case_insensitive=None applies term_is_case_sensitive(); True forces a
    case-insensitive search (used when looking a term up in the student's OWN text,
    where they may have typed "crispr").
    """
    cleaned = clean_term(term)
    if not cleaned:
        return None
    if case_insensitive is None:
        case_insensitive = not term_is_case_sensitive(cleaned)
    body = r"\s+".join(re.escape(part) for part in cleaned.split(" "))
    flags = re.UNICODE | (re.IGNORECASE if case_insensitive else 0)
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", flags)


def _token_before(text: str, end: int) -> str:
    """The run of non-space characters ending at `end`, read backwards and bounded.

    This used to be a regex search for (\\S+)$ over a copy of text[:end], once per full
    stop. The copy made every call cost the length of the text so far, and the search
    itself is quadratic over a long run of non-space characters. Measured on this
    machine: 7.6 s for a 4,000-character token followed by 50 short sentences. A student
    who pastes a sequence or a long URL into their narrative is enough to produce that,
    and these functions run inside async routes, so it stalled every user.
    """
    start = end
    floor = max(0, end - _TOKEN_LOOKBACK)
    while start > floor and not text[start - 1].isspace():
        start -= 1
    if start == floor and start > 0 and not text[start - 1].isspace():
        # Longer than any abbreviation. Reported as "" so neither test below matches.
        return ""
    return text[start:end]


def sentence_boundaries(text: str) -> List[Tuple[int, int]]:
    """(end_of_sentence, start_of_next) pairs for `text`, in order. Linear in len(text)."""
    out = []
    for m in _BOUNDARY_RE.finditer(text):
        if m.group("para") is not None:
            out.append((m.start(), m.end()))
            continue
        punct = m.group("punct")
        if punct.startswith(".") and len(punct.rstrip("\"'”’)]")) == 1:
            token = _token_before(text, m.start()).lstrip("(\"'“‘[")
            # An initial ("J. Smith", "C. elegans") or a listed abbreviation.
            if len(token) == 1 and token.isalpha():
                continue
            if token.casefold() in _ABBREVIATIONS:
                continue
            nxt = text[m.end():m.end() + 1]
            # "approx. the same": a sentence does not start with a lowercase letter.
            if nxt and nxt.islower():
                continue
        out.append((m.start() + len(punct), m.end()))
    return out


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _window(text: str, s: int, e: int, ms: int, me: int) -> Tuple[int, int]:
    """Narrow [s, e) to at most MAX_SENTENCE_CHARS around the match [ms, me), cutting
    only where a word ends. Returns the new (start, end)."""
    if e - s <= MAX_SENTENCE_CHARS:
        return s, e
    budget = MAX_SENTENCE_CHARS - (me - ms)
    left = min(ms - s, budget // 2)
    right = min(e - me, budget - left)
    left = min(ms - s, budget - right)
    ws, we = ms - left, me + right

    if ws > s and not text[ws - 1].isspace() and not text[ws].isspace():
        # Landed inside a word: start after the next whitespace, or at the match.
        gap = re.compile(r"\s+").search(text, ws, ms)
        ws = gap.end() if gap else ms
    if we < e and not text[we].isspace() and not text[we - 1].isspace():
        cut = me
        for gap in re.compile(r"\s+").finditer(text, me, we):
            cut = gap.start()
        we = cut
    return ws, we


def _strip(text: str, s: int, e: int) -> Tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def locate_term(term: str, text: str, *, case_insensitive: Optional[bool] = None,
                boundaries: Optional[List[Tuple[int, int]]] = None) -> Optional[dict]:
    """First sentence of `text` containing `term` as a whole word, or None.

    Returns {sentence, offsets, truncated_start, truncated_end}. `sentence` is
    text[a:b] for some a, b: never edited. `offsets` are [start, end) pairs of every
    occurrence of the term inside `sentence`, counted in UTF-16 code units because the
    consumer is JavaScript, where "\\U0001d6fc".length is 2. For text inside the Basic
    Multilingual Plane they equal Python indices.

    The match is found first and the sentence is drawn around it, so a full stop that
    is part of the term ("C. elegans", "et al.") cannot split the term across two
    sentences.
    """
    if not isinstance(text, str) or not text:
        return None
    pattern = compile_term_pattern(term, case_insensitive=case_insensitive)
    if pattern is None:
        return None
    spans = [(m.start(), m.end()) for m in pattern.finditer(text) if m.end() > m.start()]
    if not spans:
        return None
    ms, me = spans[0]
    if me - ms > MAX_SENTENCE_CHARS:
        return None

    if boundaries is None:
        boundaries = sentence_boundaries(text)
    s, e = 0, len(text)
    for sent_end, next_start in boundaries:
        if next_start <= ms:
            s = next_start
        elif sent_end >= me:
            e = sent_end
            break
    s, e = _strip(text, s, e)
    ws, we = _strip(text, *_window(text, s, e, ms, me))

    sentence = text[ws:we]
    offsets = []
    for a, b in spans:
        if a >= ws and b <= we:
            start = _utf16_len(text[ws:a])
            offsets.append([start, start + _utf16_len(text[a:b])])
    return {
        "sentence": sentence,
        "offsets": offsets,
        "truncated_start": ws > s,
        "truncated_end": we < e,
    }


def normalise_terms(terms: Optional[Iterable]) -> List[dict]:
    """[{term, origin}] with blanks dropped and duplicates (by term_key) collapsed.

    Accepts plain strings or dicts carrying `term` and, optionally, `origin`.
    """
    out, seen = [], set()
    for item in terms or []:
        if isinstance(item, dict):
            term, origin = clean_term(item.get("term")), item.get("origin")
        else:
            term, origin = clean_term(item), None
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        out.append({"term": term, "origin": origin})
    return out


def build_fit_evidence(terms: Optional[Iterable], row: Optional[dict], *,
                       basis: Optional[str] = None) -> dict:
    """{rows, matched, total, basis} for one award.

    `row` carries grant_title, grant_abstract and abstract_is_generated. `basis`
    overrides text_provenance() and exists for the persona decks, whose text is neither
    published nor generated by anyone ("sample").

    One row per term: the first sentence containing it, title before abstract.

    llm_generated text is never searched, the title of such a row included. Its
    `matched` is None, not 0: nothing was counted, and a zero would read as "we looked
    and your terms are not there".
    """
    row = row or {}
    wanted = normalise_terms(terms)
    basis = basis or text_provenance(row)
    total = len(wanted)

    if basis == BASIS_LLM_GENERATED:
        return {"rows": [], "matched": None, "total": total, "basis": basis}

    title = row.get("grant_title") if isinstance(row.get("grant_title"), str) else ""
    abstract = row.get("grant_abstract") if isinstance(row.get("grant_abstract"), str) else ""
    fields = [("title", title)]
    # When the abstract is the title over again there is one text, not two.
    if basis != BASIS_FEDERAL_DESCRIPTION_ONLY:
        fields.append(("abstract", abstract))
    fields = [(name, text, sentence_boundaries(text)) for name, text in fields if text]

    rows = []
    for item in wanted:
        for name, text, bounds in fields:
            hit = locate_term(item["term"], text, boundaries=bounds)
            if hit and hit["offsets"]:
                rows.append({
                    "term": item["term"],
                    "origin": item["origin"],
                    "field": name,
                    **hit,
                })
                break
    return {"rows": rows, "matched": len(rows), "total": total, "basis": basis}


def evidence_card_keys(terms: Optional[Iterable], row: Optional[dict], *,
                       basis: Optional[str] = None) -> Dict[str, object]:
    """The four evidence keys of a deck card.

    `terms` None means the student's terms were not loaded for this card (the saved
    path when the profile read failed, for one). The keys are then null rather than an
    empty list, so the card shows nothing instead of "none of your terms appear".
    """
    row = row or {}
    # Unknown provenance is not "recorded as published". normalize_rpc_grant yields None
    # when neither the RPC row nor the detail read supplied the flag (an older function
    # body, a failed or column-less fetch_grant_details). Before this module that gap
    # only hid an amber pill; here it would put text that may be Gemini's in a quoted
    # position under "recorded as published by <agency>". So nothing is searched and no
    # basis is claimed, and the card draws no block. False still means what it meant.
    if basis is None and row.get("abstract_is_generated") is None:
        return {
            "evidence": None,
            "evidence_matched": None,
            "evidence_total": None,
            "evidence_basis": None,
        }
    if terms is None:
        return {
            "evidence": None,
            "evidence_matched": None,
            "evidence_total": None,
            "evidence_basis": basis or text_provenance(row),
        }
    found = build_fit_evidence(terms, row, basis=basis)
    return {
        "evidence": found["rows"],
        "evidence_matched": found["matched"],
        "evidence_total": found["total"],
        "evidence_basis": found["basis"],
    }
