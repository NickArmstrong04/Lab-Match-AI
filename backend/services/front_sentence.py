"""The one line under the title on a card front: which sentence, from which field.

Pure module. No network, no database, no LLM, and no import from routers/, database.py
or config.py, so it can be exercised with sockets blocked and hand-built rows.

Why it exists (phase 3): the owner's feedback on the phase 2 card was that it was
accurate and slow. A 2,800-character abstract on the front does not let a student "quickly
grasp if they are interested in the lab". The front gets ONE sentence instead.

What this module will and will not do:

  - It CHOOSES a whole sentence the agency published. It never writes one and never cuts
    one. The first design cut long sentences at a clause; measured over 3,000 stored
    abstracts that produced fragments that reverse the meaning (a sentence cut right
    before ", yet they do not ..."). The cut rule is deleted, not tuned.
  - The chosen text is text[start:end] of the stored field: newlines and double spaces
    included. That is the invariant. The label strip returns an OFFSET for the same
    reason: a caller holding an offset can only ever drop a prefix, it cannot rewrite.
  - Every test below is deliberately biased towards "no sentence". A card with no
    sentence shows its title unclamped and is honest. A card with a fragment, a sentence
    that points at something the student cannot see ("This disease ..."), or an
    unexplained acronym is neither quick nor honest.
  - When nothing qualifies, a stored AI one-liner may be shown, labelled amber. It is
    read from its own column and is never produced here (services/plain_summary.py).

There is no part-of-speech tagger in this codebase and none is added for one line of
text, so "contains a finite verb" and "dangling reference" are word-list heuristics.
They are tuned to miss (report no verb, report a dangling reference) rather than to
pass. The share of awards that end with a sentence is measured, not assumed; see the
phase 3 report.
"""
import re
from typing import Dict, List, Optional, Tuple

from .fit_evidence import normalise_text, sentence_boundaries

SCAN_SENTENCES = 8
MIN_WORDS, MAX_WORDS, MAX_CHARS = 8, 28, 160

SOURCE_NIH_PHR = "nih_phr"
SOURCE_NIH_ABSTRACT = "nih_abstract"
SOURCE_NSF_ABSTRACT = "nsf_abstract"
SOURCE_AI_SUMMARY = "ai_summary"
SOURCE_SAMPLE = "sample"

TAG_NIH_SUMMARY = "NIH summary"
TAG_NIH_ABSTRACT = "NIH abstract"
TAG_NSF_ABSTRACT = "NSF abstract"
TAG_ON_FILE = "Abstract on file"
TAG_AI_SUMMARY = "AI summary"

AI_SUMMARY_INFO = (
    "Written by an AI model from the text {agency} published for this award. "
    "It may be wrong. The agency's own text is in Details."
)

# Duplicated from routers/grants.py (USASPENDING_SOURCES), which this module must not
# import: a service importing a router is circular. Every description on these rows is
# LLM-mediated by construction (USAspending publishes no abstract), so none of them is
# ever a sentence source, whatever their flags say.
_USASPENDING_SOURCES = frozenset({"DOD", "DNR", "DOE", "EPA", "NASA", "USDA"})
_SENTENCE_AGENCIES = frozenset({"NIH", "NSF"})

# ---------------------------------------------------------------------------
# Label strip
# ---------------------------------------------------------------------------

# Allow-list, longest alternative first so "Project Summary/Abstract" is not read as
# "Project Summary" followed by "/Abstract". These are section headings of the NIH
# application form that applicants paste in with their text. Anything not listed is
# left alone: a heading we do not recognise is kept and its "sentence" is then rejected
# as label residue, which costs a sentence and never costs a word of agency text.
#
# "Modified Project Summary/Abstract Section" is not in the addendum's list. It is the
# heading NIH itself puts on abstracts it has edited, it is in the stored sample
# (award 11189779), and it is the abstract-side twin of the listed "Modified Public
# Health Relevance Section".
_LABEL_ALTERNATIVES = (
    r"Modified\s+Public\s+Health\s+Relevance\s+Section",
    r"Modified\s+Project\s+Summary(?:\s*/\s*Abstract)?\s+Section",
    r"Project\s+Narrative\s*/\s*Relevance",
    r"Public\s+Health\s+Relevance(?:\s+(?:Statement|Section))?",
    r"Project\s+Summary(?:\s*/\s*Abstract)?",
    r"Project\s+Narrative",
    r"Project\s+Abstract",
    r"Narrative",
    r"Summary",
    r"Abstract",
)
_LABEL_RE = re.compile(
    r"[ \t\r\n]*(?P<label>" + "|".join(_LABEL_ALTERNATIVES) + r")(?![\w/])",
    re.IGNORECASE,
)
_DASHES = "-–—"
# How far a dash segment ("– Core 5 – Biostatistics and Bioinformatics Core") may run
# before its newline. Past this it is not a heading line, it is prose.
_DASH_SEGMENT_MAX = 140


def _label_is_heading_cased(label: str) -> bool:
    """Starts with a capital: "PROJECT SUMMARY", "Project Summary", "Project abstract".
    A field that opens with a lower-case "abstract" or "summary" is mid-prose."""
    return bool(label) and label[0].isupper()


def strip_label(text: str) -> int:
    """Offset at which the text starts once an allow-listed leading label is skipped.

    0 when nothing matches. Returns an OFFSET so the caller can only ever drop a prefix.

    A label counts only when what follows shows it was a heading:
      - a newline or a colon directly after it, or
      - a dash segment that ends at a newline ("– RP2\\n"), or
      - whitespace and then a capital, a digit or an opening quote or bracket.
    The last case is needed because ingest's clean_abstract_html collapses every
    newline in grant_abstract to a space, so stored abstracts read
    "PROJECT SUMMARY Development is all about timing." It would also strip the first
    word of "Summary Statistics for ...", so a ONE-word label in that position is only
    taken when it is all capitals or the next word is not itself lower-case prose.

    A dash segment with no newline after it ("PROJECT SUMMARY – RP2 Pancreatic ductal
    ...", again the collapsed form) cannot be delimited: nothing says where the heading
    ends and the abstract begins. The text is then left untouched, offset 0, and the
    first sentence is rejected as label residue further down.
    """
    if not isinstance(text, str) or not text:
        return 0
    m = _LABEL_RE.match(text)
    if not m:
        return 0
    label = m.group("label")
    if not _label_is_heading_cased(label):
        return 0
    pos = m.end()
    n = len(text)

    # Spaces, then an optional colon.
    i = pos
    while i < n and text[i] in " \t":
        i += 1
    had_colon = i < n and text[i] == ":"
    if had_colon:
        i += 1
        while i < n and text[i] in " \t":
            i += 1

    if i < n and text[i] in _DASHES and not had_colon:
        newline = text.find("\n", i)
        if newline == -1 or newline - i > _DASH_SEGMENT_MAX:
            return 0
        i = newline

    if i >= n:
        # The whole field is the label.
        return n

    if text[i] in "\r\n" or had_colon:
        while i < n and text[i].isspace():
            i += 1
        return i

    if i == pos:
        # Nothing separates the label from what follows.
        return 0
    nxt = text[i]
    if not (nxt.isupper() or nxt.isdigit() or nxt in "\"'“‘(["):
        return 0
    one_word = len(label.split()) == 1 and "/" not in label
    if one_word and not label.isupper():
        # "Abstract Musculoskeletal (MSK) disorders affect ..." is a heading.
        # "Narrative Medicine is ..." and "Summary Statistics ..." cannot be told from
        # one by shape, so a title-case single word is taken only when the word after
        # it is followed by more prose in the usual way: a capitalised word and then a
        # lower-case one or a bracket. A second capitalised word ("Abstract Expressionist
        # Painting ...") reads as a title and is left alone.
        follow = re.match(r"\S+\s+(\S)", text[i:])
        if not follow or follow.group(1).isupper():
            return 0
    return i


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------

def sentence_spans(text: str, start: int = 0) -> List[Tuple[int, int]]:
    """[start, end) of each sentence from `start`, leading/trailing whitespace excluded.

    Built on fit_evidence.sentence_boundaries, so "et al. 2019", "Dr. Smith" and
    "C. elegans" split nowhere they do not split in the phase 2 evidence rows. The
    boundaries are computed over the WHOLE text and then filtered, because the
    abbreviation guard reads the word before a full stop and a slice would hide it.
    """
    if not isinstance(text, str) or not text:
        return []
    start = max(0, min(int(start or 0), len(text)))
    spans = []
    s = start
    for sent_end, next_start in sentence_boundaries(text):
        if sent_end <= s:
            s = max(s, next_start) if next_start > s else s
            continue
        spans.append((s, sent_end))
        s = next_start
    if s < len(text):
        spans.append((s, len(text)))
    out = []
    for a, b in spans:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def _collapse(sentence: str) -> str:
    return " ".join(sentence.split())


def _words(collapsed: str) -> List[str]:
    """Whitespace tokens that carry a letter or a digit. A lone dash is not a word."""
    return [w for w in collapsed.split(" ") if any(c.isalnum() for c in w)]


# -- label or heading residue ------------------------------------------------

_LABEL_START_RE = re.compile(
    r"(?:" + "|".join(_LABEL_ALTERNATIVES) + r")(?![\w/])", re.IGNORECASE
)
_HEADING_START_RE = re.compile(
    r"(?:specific\s+aims?|aims?\s+\d|aim\s+[ivx]+\b|objective\s+\d|significance\s*:|"
    r"background\s*:|relevance\s*:|overview\s*:|project\s+\d+\s*[:\-–—]|core\s+[a-z0-9]+\s*[:\-–—])",
    re.IGNORECASE,
)
# NSF appends this to every abstract. It says nothing about the award.
_NSF_BOILERPLATE_RE = re.compile(r"this award reflects nsf'?s statutory mission", re.IGNORECASE)
_TERMINAL_RE = re.compile(r"[.!?][\"'”’)\]]*$")
# "The Specific Aims of the Core are: Aim 1." The splitter ends a sentence at the full
# stop after a list number, so what reaches this module is the introduction of a list
# and its first marker. It is whole by the letter of the never-cut rule and a fragment
# to the student (seen on a real card, award "Machine Learning and Image Analysis
# Core"). Three shapes: a colon followed only by a marker, a sentence that ends on a
# marker, and a sentence that announces its aims. The splitter itself is phase 2's
# (fit_evidence.sentence_boundaries) and is not changed: evidence rows depend on it.
_LIST_MARKER = (
    r"(?:\(?\d{1,2}[.)]?|\(?[ivx]{1,4}[.)]|\(?[a-e][.)]|"
    r"(?:specific\s+)?(?:aim|objective|goal|step|task|thrust|phase|project|core)\s*#?\s*\d{1,2})"
)
_LIST_STUB_RE = re.compile(
    r"(?::\s*" + _LIST_MARKER + r"\.?|\b(?:specific\s+)?(?:aim|objective|thrust|task)\s*#?\s*\d{1,2}\.)$",
    re.IGNORECASE,
)
# "Improve- ments in statistical genetics ... per- sonalized medical therapies": a word
# broken at the end of a line in the applicant's PDF and stored that way. The text is
# the agency's and is not repaired here, so the sentence is not shown. "pre- and
# post-treatment" is a suspended hyphen and is fine.
_BROKEN_HYPHEN_RE = re.compile(r"[^\W\d_]-\s+(?!and\b|or\b|to\b|versus\b|vs\b)[a-z]")
# Letters and roman numerals count as a marker only with a bracket: "C. elegans is ..."
# and "A. thaliana ..." open real sentences.
_LIST_ITEM_START_RE = re.compile(r"\(?(?:\d{1,2}[.)]|(?:[ivx]{1,4}|[a-e])\))\s", re.IGNORECASE)
# "Specific aims" only. "This project aims to find which genes are required" has the
# same two words in it and is the sentence we want.
_AIMS_ANNOUNCED_RE = re.compile(
    r"\bspecific\s+aims?\b[^.]{0,80}\b(?:are|is|include|includes|were)\b"
    r"|\bfollowing\s+(?:specific\s+)?(?:aims|objectives|goals)\b|\bas\s+follows\b",
    re.IGNORECASE,
)


def _is_label_residue(collapsed: str, words: List[str]) -> bool:
    if not collapsed:
        return True
    if collapsed[0] in _DASHES + "•*·#|:;,)":
        return True
    # A heading has no full stop. Neither does a field that was truncated in storage,
    # and a sentence that may be missing its end is not shown either.
    if not _TERMINAL_RE.search(collapsed):
        return True
    if not any(c.islower() for c in collapsed):
        return True
    m = _LABEL_START_RE.match(collapsed)
    if m and _label_is_heading_cased(m.group(0)):
        return True
    if _HEADING_START_RE.match(collapsed):
        return True
    if _NSF_BOILERPLATE_RE.search(collapsed):
        return True
    if _BROKEN_HYPHEN_RE.search(collapsed):
        return True
    if (_LIST_STUB_RE.search(collapsed) or _LIST_ITEM_START_RE.match(collapsed)
            or _AIMS_ANNOUNCED_RE.search(collapsed) or collapsed.rstrip(".").endswith(":")):
        return True
    # "SHARED RESOURCE: HIGH THROUGHPUT SCREENING FACILITY The High Throughput ..."
    # Three all-capital words in a row at the start, each longer than an acronym would
    # be on its own, is a heading run into the first sentence by the newline collapse.
    lead = []
    for w in words[:4]:
        core = w.strip(".,;:()[]\"'“”‘’")
        if len(core) >= 2 and core.isupper() and any(c.isalpha() for c in core):
            lead.append(core)
        else:
            break
    if len(lead) >= 3:
        return True
    # A colon inside the first three words, after a capitalised run, is "Heading: text".
    if any(w.endswith(":") for w in words[:3]):
        return True
    return False


# -- subordinators and backwards references ----------------------------------

_SUBORDINATORS = frozenset({
    "although", "despite", "while", "as", "because", "if", "given", "with", "since",
    "when",
    # Same construction, not in the addendum's list: a sentence that opens with one of
    # these is the concession half of a contrast, or a fragment.
    "though", "whereas", "whilst", "unless", "until", "once",
})

# A sentence that opens with one of these continues the one before it.
_BACKWARD_OPENERS = (
    "it", "its", "they", "their", "them", "he", "she", "his", "her", "those", "that",
    "however", "thus", "therefore", "moreover", "furthermore", "additionally", "also",
    "hence", "consequently", "accordingly", "nevertheless", "nonetheless", "instead",
    "indeed", "similarly", "likewise", "conversely", "yet", "but", "and", "or", "so",
    "then", "next", "finally", "second", "secondly", "third", "thirdly", "fourth",
    "lastly", "specifically", "together", "collectively", "importantly", "notably",
    "here", "there", "both", "each", "another", "other", "others", "one", "two",
    "in addition", "in contrast", "in particular", "in turn", "in summary",
    "in conclusion", "to this end", "to that end", "to do so", "for example",
    "for instance", "as a result", "as such", "on the other hand", "taken together",
    "by contrast", "after", "before", "first", "overall", "further", "rather",
    # Sentence adverbs: a comment on what was just said. "Unfortunately, high editing
    # efficiency only occurs on a small subset of all possible DNA targets." was shown
    # on a real card with nothing before it for "unfortunately" to be about.
    "unfortunately", "fortunately", "interestingly", "surprisingly", "remarkably",
    "strikingly", "crucially", "critically", "clearly", "alternatively", "meanwhile",
    "otherwise", "subsequently", "ultimately", "still", "even so", "as an alternative",
    "as a consequence", "in fact", "in short", "in sum", "in other words",
    "in doing so", "in so doing", "in response", "in parallel",
    # A renewal talking about itself to a reader who never saw the first period:
    # "In this renewal, the Program will enhance training in AI genomics."
    "in this renewal", "in this competing renewal", "in this resubmission",
    "in this revision", "in the prior", "in the previous", "in the last", "in the first",
    "in the next", "during the prior", "during the previous", "during the last",
    "over the prior", "over the previous", "over the last",
)
_BACKWARD_OPENER_RE = re.compile(
    r"(?:" + "|".join(re.escape(o).replace(r"\ ", r"\s+") for o in
                      sorted(_BACKWARD_OPENERS, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE,
)
# "Here we propose ..." opens the abstract as often as it continues one, and the noun
# it points at is the award itself. Same for "Here, we".
_HERE_WE_RE = re.compile(r"here,?\s+we\b", re.IGNORECASE)

# What "this" may be followed by when it names the award itself rather than something
# said earlier. These are the purpose cues; a purpose cue is not a dangling reference.
_SELF_NOUNS = (
    r"(?:(?:proposed|new|renewal|competing|collaborative|interdisciplinary|"
    r"multidisciplinary|research|training|career|pilot|planning|small\s+business|"
    r"doctoral\s+dissertation|postdoctoral|five-year|[a-z]+-year)\s+){0,3}"
    r"(?:project|proposal|application|study|research|award|program|programme|grant|"
    r"core|center|centre|work|renewal|supplement|resource|facility|conference|workshop|"
    r"symposium|meeting|site|fellowship|consortium|initiative|effort|investigation|"
    r"plan|component|subproject|sbir|sttr|reu|career|r\d{2}|k\d{2}|t\d{2}|f\d{2}|"
    r"u\d{2}|p\d{2})"
)
_DEMONSTRATIVE_RE = re.compile(r"\b(this|these|such)\b(?!\s*,)\s*(\S*)", re.IGNORECASE)
_THIS_OK_RE = re.compile(r"this\s+" + _SELF_NOUNS + r"\b", re.IGNORECASE)
_EXPLICIT_BACKREF_RE = re.compile(
    r"\b(?:the\s+above|the\s+aforementioned|aforementioned|as\s+described|"
    r"as\s+mentioned|as\s+noted|as\s+discussed|as\s+outlined|described\s+above|"
    r"mentioned\s+above|the\s+latter|the\s+former|the\s+same|see\s+above|"
    # "Our new software methods will therefore unlock ...": the reason is in the
    # sentence before, wherever in this one the word stands.
    r"in\s+this\s+way|that\s+is,|therefore|"
    # A renewal reporting on itself ("In the prior funding period the Core has
    # supported ..."): it says what was done before, to a reader who was not there.
    r"(?:prior|previous|last|past|current|first|next)\s+(?:funding|project|award|grant)\s+"
    r"(?:period|cycle)|funding\s+period)\b",
    re.IGNORECASE,
)


def _has_dangling_reference(collapsed: str) -> bool:
    if _EXPLICIT_BACKREF_RE.search(collapsed):
        return True
    opener = _BACKWARD_OPENER_RE.match(collapsed)
    if opener and not _HERE_WE_RE.match(collapsed):
        return True
    for m in _DEMONSTRATIVE_RE.finditer(collapsed):
        word = m.group(1).lower()
        if word == "such":
            # "such as" introduces examples inside the sentence.
            if m.group(2).lower().strip(".,;:") == "as":
                continue
            return True
        if word == "this" and _THIS_OK_RE.match(collapsed, m.start()):
            continue
        return True
    return False


# -- finite verb -------------------------------------------------------------

# Auxiliaries and modals. Every one of these is finite wherever it stands ("be",
# "been" and "being" are not and are not listed).
_FINITE_AUX = frozenset({
    "is", "are", "was", "were", "am", "has", "have", "had", "will", "would", "can",
    "could", "may", "might", "must", "shall", "should", "does", "do", "did", "cannot",
})
# Third-person forms that are not also everyday nouns. "studies", "aims", "results",
# "uses", "tests", "controls", "models", "leads", "plans", "needs", "causes",
# "increases" and "changes" are left out on purpose: each is a noun at least as often
# in an abstract, and a noun phrase must not pass for a sentence.
_FINITE_S_FORMS = frozenset({
    "seeks", "proposes", "investigates", "examines", "develops", "provides", "supports",
    "focuses", "addresses", "explores", "determines", "identifies", "remains", "affects",
    "plays", "requires", "enables", "contributes", "occurs", "depends", "represents",
    "suggests", "indicates", "regulates", "drives", "involves", "includes", "offers",
    "makes", "brings", "combines", "integrates", "establishes", "creates", "builds",
    "allows", "helps", "serves", "becomes", "begins", "continues", "describes",
    "demonstrates", "reveals", "shows", "exists", "arises", "emerges", "lies", "takes",
    "gives", "holds", "consists", "comprises", "encompasses", "promotes", "mediates",
    "encodes", "binds", "produces", "reduces", "prevents", "kills", "lacks", "relies",
    "trains", "prepares", "funds", "hosts", "advances", "targets", "leverages",
    "employs", "utilizes", "utilises", "applies", "aims",
})
_SUBJECT_PRONOUN_VERB_RE = re.compile(
    r"\b(?:we|they|who|which|i)\s+(?:(?:\w+ly|also|now|first|then|further|therefore|thus)\s+)?"
    r"(?!and\b|or\b|the\b|a\b|an\b|of\b|in\b|to\b)[a-z]{3,}\b",
    re.IGNORECASE,
)
_PAST_THAT_RE = re.compile(r"\b[a-z]{3,}ed\s+that\b", re.IGNORECASE)


def _has_finite_verb(collapsed: str) -> bool:
    tokens = [t.strip(".,;:()[]\"'“”‘’").lower() for t in collapsed.split(" ")]
    tokens = [t for t in tokens if t]
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        if tok in _FINITE_AUX:
            return True
        if tok in _FINITE_S_FORMS:
            # "the aims", "its aims", "specific aims": noun. "to aims" does not occur.
            if tok == "aims" and prev in {"the", "its", "our", "their", "specific",
                                          "these", "three", "two", "four", "of"}:
                continue
            return True
    if _SUBJECT_PRONOUN_VERB_RE.search(collapsed):
        return True
    if _PAST_THAT_RE.search(collapsed):
        return True
    return False


# -- acronyms ----------------------------------------------------------------

# Acronyms a first-year undergraduate reads without an expansion. This list is
# LabMatch's judgement, not a federal one, and is short on purpose: the cost of a
# missing entry is one card without a sentence.
_KNOWN_ACRONYMS = frozenset({
    "DNA", "RNA", "HIV", "AIDS", "COVID", "US", "USA", "UK", "NIH", "NSF", "AI", "3D",
    "2D", "STEM", "MRI", "CRISPR", "PHD", "MD",
})
_ROMAN_RE = re.compile(r"^(?:I{1,3}|IV|V|VI{0,3}|IX|X)$")
_ORDINAL_OR_DECADE_RE = re.compile(r"^\d+(?:st|nd|rd|th|s)$", re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[\s/]+")
_EDGE_PUNCT = ".,;:!?()[]{}\"'“”‘’"


def _acronym_candidates(collapsed: str) -> List[str]:
    """Tokens that read as an acronym, a code or a symbol, in order, without duplicates.

    Two shapes: two or more capitals making up at least half of the letters ("PDAC",
    "HTSF", "mRNA", "scRNA"), and any mixture of letters and digits ("U2AF1", "5mC",
    "p53", "T32"). The second is not strictly an acronym. It is the same problem for the
    reader: a symbol that means nothing unless you already know the field.
    """
    out, seen = [], set()
    for raw in _TOKEN_SPLIT_RE.split(collapsed):
        token = raw.strip(_EDGE_PUNCT)
        if token.endswith(("'s", "’s")):
            token = token[:-2]
        for part in re.split(r"[-–—]", token):
            part = part.strip(_EDGE_PUNCT + "+")
            if len(part) < 2:
                continue
            letters = [c for c in part if c.isalpha()]
            if not letters:
                continue
            has_digit = any(c.isdigit() for c in part)
            uppers = sum(1 for c in letters if c.isupper())
            if has_digit:
                if _ORDINAL_OR_DECADE_RE.match(part):
                    continue
                is_candidate = True
            else:
                core = part[:-1] if part.endswith("s") and part[:-1].isupper() else part
                core_letters = [c for c in core if c.isalpha()]
                uppers = sum(1 for c in core_letters if c.isupper())
                is_candidate = uppers >= 2 and uppers * 2 >= len(core_letters)
                part = core if is_candidate else part
            if not is_candidate or _ROMAN_RE.match(part):
                continue
            if part.upper() in _KNOWN_ACRONYMS:
                continue
            if part not in seen:
                seen.add(part)
                out.append(part)
    return out


def _acronym_is_expanded(acronym: str, collapsed: str) -> bool:
    """True when the sentence itself says what the acronym stands for.

    Accepted: "Residual Cancer Burden (RCB)", where at least two words stand before the
    bracket, and "RCB (Residual Cancer Burden)". A bare "(RCB)" after one word, or an
    acronym that is simply used, is not an expansion.
    """
    esc = re.escape(acronym)
    before = re.search(r"((?:[\w’'-]+\s+){2,})\(\s*" + esc + r"s?\s*[);,]", collapsed)
    if before:
        return True
    after = re.search(r"(?<![\w-])" + esc + r"s?\s*\(\s*(?:[\w’'-]+\s+){1,}[\w’'-]+\s*\)", collapsed)
    return bool(after)


def _has_unexpanded_acronym(collapsed: str) -> bool:
    return any(not _acronym_is_expanded(a, collapsed) for a in _acronym_candidates(collapsed))


# -- housekeeping ------------------------------------------------------------

# Sentences about what happens to the outputs, the money or the building. They are
# short, plain, whole and say "we will" or "this project", so they beat the sentence
# that states the work, which is usually too long to qualify. Two real cards read
# "We will release open access software and summary statistics ..." and "All software
# produced by this project will be made freely available ..." under a genetics title.
# "MaineHealth provided institutional funds to renovate the facility ..." is the same
# failure without a cue.
_HOUSEKEEPING_RE = re.compile(
    r"\b(?:"
    # "release" with its object: calcium release and drug release are science.
    r"releas(?:e|es|ed|ing)\s+(?:of\s+)?(?:(?:all|our|the|any|these|open|free|public)\S*\s+){0,3}"
    r"(?:software|code|data|datasets?|tools?|resources?|results|materials|protocols?|"
    r"pipelines?|packages?|access)\b|disseminat\w+|"
    r"(?:freely|publicly|openly|widely|made|make|making)\s+(?:\w+\s+)?(?:available|accessible)|"
    r"open[- ](?:access|source)|open\s+science|summary\s+statistics|"
    r"(?:will|to)\s+(?:be\s+)?shar(?:e|ed)\b|data[- ]sharing|"
    r"(?:deposited|posted|hosted|archived)\s+(?:in|on|at|to)\b|github|repository|repositories|"
    r"to\s+the\s+(?:broader\s+|wider\s+|general\s+)?(?:scientific|research|biomedical)\s+community|"
    r"broader\s+impacts?|intellectual\s+merit|"
    r"institutional\s+(?:funds?|support|commitment)|matching\s+funds?|cost[- ]shar\w+|"
    r"renovat\w+|footprint|square\s+f(?:ee|oo)t|"
    r"statutory\s+mission|deemed\s+worthy|review\s+criteria|"
    r"budget\w*|"
    r"(?:conference|meeting|workshop|symposium)\s+(?:will\s+be\s+held|will\s+take\s+place)|"
    r"rich\s+content"
    r")",
    re.IGNORECASE,
)


def _is_housekeeping(collapsed: str) -> bool:
    return bool(_HOUSEKEEPING_RE.search(collapsed))


# -- the two public tests ----------------------------------------------------

def disqualified(sentence: str) -> Optional[str]:
    """None when the sentence qualifies, else the first reason that applies.

    Reasons: "too_short", "too_long_words", "too_long_chars", "no_finite_verb",
    "subordinator", "dangling_reference", "unexpanded_acronym", "label_residue",
    "housekeeping" (added after review; not in the phase 3 contract's list).
    Lengths are measured on the whitespace-collapsed form, because a stored sentence
    can be hard-wrapped and the card renders it collapsed. A purpose cue ("this
    project", "this proposal", ...) is NOT a dangling reference.
    """
    if not isinstance(sentence, str):
        return "label_residue"
    collapsed = _collapse(sentence)
    words = _words(collapsed)
    # Residue first: "PROJECT SUMMARY" is two words, and "too_short" would hide what
    # it actually is from anyone reading the counts.
    if _is_label_residue(collapsed, words):
        return "label_residue"
    if len(words) < MIN_WORDS:
        return "too_short"
    if len(words) > MAX_WORDS:
        return "too_long_words"
    if len(collapsed) > MAX_CHARS:
        return "too_long_chars"
    first = words[0].strip(_EDGE_PUNCT).lower()
    if first in _SUBORDINATORS:
        return "subordinator"
    if _has_dangling_reference(collapsed):
        return "dangling_reference"
    if not _has_finite_verb(collapsed):
        return "no_finite_verb"
    if _has_unexpanded_acronym(collapsed):
        return "unexpanded_acronym"
    if _is_housekeeping(collapsed):
        return "housekeeping"
    return None


# What the award sets out to DO. The addendum lists "this project" and "we will" as
# cues; taken bare they matched "All software produced by this project will be made
# freely available", so the subject has to be followed by a verb of doing research.
# "provide", "support", "train", "serve" and "host" are in the list because that IS
# the work of a core, a training grant or a meeting. "release", "share" and "make"
# are not.
_RESEARCH_VERB = (
    r"(?:determin|develop|test|identif|stud|investigat|examin|explor|establish|creat|"
    r"build|defin|characteri[sz]|measur|map|design|elucidat|uncover|understand|evaluat|"
    r"assess|quantif|discover|reveal|engineer|generat|analy[sz]|compar|model|dissect|"
    r"address|focus|us|appl|combin|integrat|leverag|employ|seek|aim|ask|answer|learn|"
    r"find|produc|construct|implement|validat|optimi[sz]|improv|advanc|translat|"
    r"provid|support|train|serv|host|bring|conven|offer|prepar|educat|teach|enhanc|target)"
    r"(?:e|es|ed|s|y|ies|ied|ing)?"
)
_ADVERB = r"(?:(?:also|first|then|now|further|therefore|thus|\w+ly)\s+)?"
_PURPOSE_CUE_RE = re.compile(
    r"\b(?:"
    r"this\s+" + _SELF_NOUNS + r"\s+(?:will\s+)?" + _ADVERB + _RESEARCH_VERB + r"|"
    r"the\s+(?:proposed\s+)?(?:project|proposal|study|research|award|program|work|core|center)\s+"
    r"(?:will\s+)?" + _ADVERB + _RESEARCH_VERB + r"|"
    r"we\s+(?:propose|aim|seek|plan|hypothesize|hypothesise)|"
    r"we\s+(?:will\s+)?" + _ADVERB + _RESEARCH_VERB + r"|"
    r"our\s+(?:overall\s+|long-term\s+|primary\s+|main\s+)?(?:goal|goals|objective|objectives|aim|project)|"
    r"the\s+(?:overall\s+|long-term\s+|primary\s+|main\s+)?(?:goal|goals|objective|objectives|purpose|aim)\s+of|"
    r"aims\s+to|seeks\s+to|"
    r"will\s+" + _ADVERB + _RESEARCH_VERB +
    r")\b",
    re.IGNORECASE,
)


def has_purpose_cue(sentence: str) -> bool:
    """True when the sentence says what the award sets out to do, in its own words."""
    if not isinstance(sentence, str):
        return False
    collapsed = _collapse(sentence)
    return bool(_PURPOSE_CUE_RE.search(collapsed)) and not _is_housekeeping(collapsed)


def _repeats_title(collapsed: str, title: Optional[str]) -> bool:
    """The sentence is the title over again. It would put the same words on the card
    twice, directly under each other."""
    t = normalise_text(title).rstrip(".")
    if len(t) < 12:
        return False
    return normalise_text(collapsed).startswith(t)


# Words too common in titles to show that a sentence is about the same thing.
_TITLE_STOPWORDS = frozenset("""
about across after among analysis approach approaches based between beyond center centre
collaborative conference core development during effects from function functions grant
health human impact into mechanism mechanisms method methods model models multi novel
program project research resource role science sciences site study studies support
system systems their through toward towards training understanding using with within
award career role roles early new data
""".split())


def _title_words(value: Optional[str]) -> set:
    out = set()
    for raw in re.findall(r"[^\W\d_]{4,}", value or "", re.UNICODE):
        w = raw.casefold()
        if w in _TITLE_STOPWORDS:
            continue
        # Plural off, nothing cleverer: "bats" is "bat", "splicing" is not "splice".
        if w.endswith("ies") and len(w) > 5:
            w = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 4:
            w = w[:-1]
        out.add(w)
    return out


def _shares_title_word(collapsed: str, title: Optional[str]) -> bool:
    return bool(_title_words(title) & _title_words(collapsed))


def select_agency_sentence(text: str, *, title: Optional[str] = None) -> Optional[dict]:
    """{"text", "start", "end", "cue": bool} with text == text_in[start:end], or None.

    Among the first SCAN_SENTENCES sentences after the label: the first qualifying one
    that carries a purpose cue, else the first qualifying one THAT SHARES A CONTENT WORD
    WITH THE TITLE.

    The second half is narrower than the addendum's "the first qualifying sentence".
    On real cards that rule put "Aging is a terminal process that affects all
    biological systems." under a title about a frailty index in mice, and a sentence
    about renovating a facility under "Proteomics and Lipidomics Core": accurate, three
    lines tall, and no help in deciding. A background sentence earns the front only if
    it is visibly about what the title names. Without a title there is nothing to hold
    it to, so only a cue sentence can be chosen.

    `title` only ever REMOVES candidates.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    spans = sentence_spans(text, strip_label(text))[:SCAN_SENTENCES]
    first_plain = None
    for a, b in spans:
        sentence = text[a:b]
        if disqualified(sentence) is not None:
            continue
        if title and _repeats_title(_collapse(sentence), title):
            continue
        found = {"text": sentence, "start": a, "end": b, "cue": has_purpose_cue(sentence)}
        if found["cue"]:
            return found
        if first_plain is None and _shares_title_word(_collapse(sentence), title):
            first_plain = found
    return first_plain


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _blank(value) -> bool:
    return not isinstance(value, str) or not value.strip()


def agency_text_for(row: dict) -> Optional[dict]:
    """{"field", "text", "source"} for the ONE field a sentence may come from, or None.

    public_statement (NIH phr_text) when non-blank. Else grant_abstract, and only when
    abstract_is_generated is exactly False and the source is NIH or NSF.

    None and True are both ineligible, the same rule as fit_evidence.evidence_card_keys:
    None means nobody recorded where the text came from, and text that may be Gemini's
    must not stand under "NIH abstract".

    There is no fall-through from a public_statement with no qualifying sentence to the
    abstract. The addendum names one source per award, in that order.
    """
    row = row or {}
    source = row.get("funding_source")
    if source in _USASPENDING_SOURCES:
        return None
    statement = row.get("public_statement")
    if not _blank(statement) and source in _SENTENCE_AGENCIES:
        return {"field": "public_statement", "text": statement, "source": SOURCE_NIH_PHR}
    if source not in _SENTENCE_AGENCIES:
        return None
    if row.get("abstract_is_generated") is not False:
        return None
    abstract = row.get("grant_abstract")
    if _blank(abstract):
        return None
    return {
        "field": "grant_abstract",
        "text": abstract,
        "source": SOURCE_NIH_ABSTRACT if source == "NIH" else SOURCE_NSF_ABSTRACT,
    }


def stored_plain_summary(row: dict) -> Optional[dict]:
    """{"text", "generated_at", "model", "source"} when the row holds a one-liner that
    still stands, else None.

    "Still stands" is decided now, from the row as it is now, by the same two functions
    that decided it when the sentence was written:

      - plain_summary.summary_input(row) must still name the SAME input field. That
        covers an abstract since replaced by Gemini text (expand_brief_abstracts.py,
        recover_unknown_pis.py set abstract_is_generated), an abstract nobody has
        compared with the agency's (abstract_checked_at NULL), and a public_statement
        that has gone.
      - plain_summary.validate_summary() must accept the sentence against the row's
        CURRENT title and text. Nothing stores a hash of the input, so this is what
        notices that the text under the sentence changed (a name or number it uses is
        no longer there), and it is what makes every later tightening of the validator
        apply to sentences stored before it. It is pure and costs a few regexes.

    Stricter than contract 3.3, which asked only for abstract_is_generated False.
    Withheld means the card shows no sentence; the stored columns are not touched.
    """
    row = row or {}
    text = row.get("plain_summary")
    if _blank(text):
        return None
    if row.get("funding_source") not in _SENTENCE_AGENCIES:
        return None
    source = row.get("plain_summary_source")
    if source not in ("nih_phr", "agency_abstract"):
        # No recorded input, or one this code does not know: not shown.
        return None
    # Imported here: plain_summary imports this module at load time.
    from . import plain_summary as _ps
    given = _ps.summary_input(row)
    if given is None or given["source"] != source:
        return None
    accepted, _reasons = _ps.validate_summary(text, title=given["title"], agency_text=given["text"])
    if accepted is None:
        return None
    generated_at = row.get("plain_summary_generated_at")
    return {
        "text": accepted,
        "generated_at": str(generated_at) if generated_at else None,
        "model": row.get("plain_summary_model") or None,
        "source": source,
    }


def _sample_sentence(row: dict) -> Optional[dict]:
    text = (row or {}).get("grant_abstract")
    if _blank(text):
        return None
    return select_agency_sentence(text, title=(row or {}).get("grant_title"))


def front_sentence(row: dict, *, sample: bool = False) -> Optional[dict]:
    """The card key: {"text","source","tag","tone","checked","info"} or None.

    sample=True: the row's grant_abstract is a persona deck's text. Same rule, source
    "sample", no tag: the card's one amber tag already says it is not a federal record,
    and an agency name under the sentence would contradict it.
    """
    row = row or {}
    if sample:
        found = _sample_sentence(row)
        if not found:
            return None
        return {"text": found["text"], "source": SOURCE_SAMPLE, "tag": None,
                "tone": "stone", "checked": False, "info": None}

    agency_text = agency_text_for(row)
    if agency_text:
        found = select_agency_sentence(agency_text["text"], title=row.get("grant_title"))
        if found:
            source = agency_text["source"]
            if source == SOURCE_NIH_PHR:
                # public_statement only ever holds what a fetch returned, so there is no
                # "on file, not re-checked" state for it.
                tag, checked = TAG_NIH_SUMMARY, True
            else:
                checked = bool(row.get("abstract_checked_at"))
                if not checked:
                    tag = TAG_ON_FILE
                else:
                    tag = TAG_NIH_ABSTRACT if source == SOURCE_NIH_ABSTRACT else TAG_NSF_ABSTRACT
            return {"text": found["text"], "source": source, "tag": tag,
                    "tone": "stone", "checked": checked, "info": None}

    summary = stored_plain_summary(row)
    if summary:
        return {
            "text": summary["text"],
            "source": SOURCE_AI_SUMMARY,
            "tag": TAG_AI_SUMMARY,
            "tone": "amber",
            "checked": False,
            "info": AI_SUMMARY_INFO.format(agency=row.get("funding_source")),
        }
    return None


def front_sentence_absent(row: dict, *, sample: bool = False) -> Optional[str]:
    """None when there is a front sentence, else why not: "no_agency_text" (no eligible
    field: generated-only text, unknown provenance, a USAspending source) or
    "none_qualifies" (eligible text, no sentence passed, no one-liner stored).

    For Details and the glanceability script. The front prints nothing in either case.
    """
    row = row or {}
    if front_sentence(row, sample=sample) is not None:
        return None
    if sample:
        return "no_agency_text" if _blank(row.get("grant_abstract")) else "none_qualifies"
    return "no_agency_text" if agency_text_for(row) is None else "none_qualifies"


def rejection_counts(text: str) -> Dict[str, int]:
    """Reason -> count over the scanned sentences. For the measuring scripts, so the
    share without a sentence can be explained and not only counted."""
    counts: Dict[str, int] = {}
    if not isinstance(text, str):
        return counts
    for a, b in sentence_spans(text, strip_label(text))[:SCAN_SENTENCES]:
        reason = disqualified(text[a:b]) or "qualifies"
        counts[reason] = counts.get(reason, 0) + 1
    return counts
