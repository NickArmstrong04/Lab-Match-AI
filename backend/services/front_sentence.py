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

Refined 2026-09-29 against a labelled sample. 150 sentences the first rule had put on
a front were read and classed: 54 said what the project does (12 of those only what it
hopes to bring about), 60 were field background ("Gliomas are aggressive brain tumors
with a dismal prognosis."), 17 leaned on a sentence the student cannot see, 7 were
administrative, 3 described the applicant, 8 were jargon, 1 announced a list. Accurate,
whole, sourced, and no help in deciding. What changed:

  - A sentence is shown only when it says what THE AWARD does: an award-naming subject
    ("This project", "We", "The proposed study") followed by a verb of doing the work.
    The old fallback (first qualifying sentence that shares a title word) is gone. It
    was the source of 58 of the 60 background sentences and of 8 good ones.
  - The bare "will <verb>" cue is gone: its subject was whatever stood before it ("The
    ability to regulate internal salt ... will ultimately determine which populations
    survive").
  - A sentence that states only a hoped-for outcome ("will lead to better understanding
    of ...") is a second choice, taken only when no sentence in the scan states the work.
  - New rejections: self-description and track record, administrative sentences
    (students trained, workforce, mentorship), list announcements, and more ways of
    leaning on an earlier sentence ("also", "that gap", "The second goal", "The results").
  - The sentence splitter is local (_sentence_boundaries). Phase 2's splitter in
    fit_evidence.py is unchanged, because evidence rows depend on where it splits.

Coverage fell and that is the intended direction: a card with no agency sentence gets a
labelled AI one-liner or nothing, both of which are honest.

Repaired 2026-09-29 (same day, after two reviewers read 120 of the 474 sentences the
refined rule showed). What they found and what changed:

  - Sentences that state a procedure and no topic ("The research team will develop
    prototypes and evaluate them in real-world settings."). A sentence now has to carry
    MIN_TOPIC_WORDS words that are not function words, award words, generic verbs or
    generic nouns (_topic_words).
  - Sentences that wrap the title in "This project will ...". _repeats_title compared
    the start of the sentence with the title; it now counts the topic words the sentence
    ADDS to the title and skips the sentence when there are fewer than MIN_NEW_WORDS.
  - Status reports ("is currently examining results"), a training sentence on an
    instrument award ("training of early-career researchers"), "makes use of" and "take
    advantage of" read as work, a question taken from a list of questions, and a bare
    "The goal is", which leans on the sentence before it.
  - Jargon is still not solved. Three cheap shapes are now rejected (four modifiers in a
    row, "addresses a fundamental step", a symbol such as "mmWave"); the rest pass.
"""
import re
from typing import Dict, List, Optional, Tuple

from .fit_evidence import normalise_text

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

# The splitter. Local to this module on purpose: fit_evidence.sentence_boundaries decides
# where phase 2 evidence rows begin and end, and changing it would move them. This one
# only ever has to be right about ONE sentence per card, and wrong in one direction:
# when it is not sure a full stop ends a sentence it does not split. Two sentences
# joined are too long to qualify and nothing is shown. A sentence split at "Aim 1." or
# "e.g." is a fragment that can pass every other test.
#
# Same regex as phase 2 (one linear pass; see the comment there about the two shapes
# that were quadratic).
_BOUNDARY_RE = re.compile(
    r"(?P<punct>(?<![.!?])[.!?]+[\"'”’)\]]*)(?P<gap>\s+)|(?P<para>\n[ \t]*\n\s*)"
)
_TOKEN_LOOKBACK = 40
_SPLIT_ABBREVIATIONS = frozenset({
    # Phase 2's list.
    "dr", "prof", "mr", "mrs", "ms", "st", "fig", "figs", "eq", "ref", "refs", "no",
    "vs", "al", "etc", "inc", "ltd", "co", "approx", "ca", "cf", "e.g", "i.e", "u.s",
    "ph.d", "m.d", "jr", "sr",
    # Added here. Titles and citations, taxonomy ("Candida sp. isolates", "var.
    # japonica"), and the forms abstracts use for figures, equations and volumes.
    "drs", "profs", "eqs", "eqn", "eqns", "tab", "sec", "vol", "vols", "pp", "nos",
    "sp", "spp", "subsp", "ssp", "var", "viz", "resp", "est", "dept", "univ", "corp",
    "mt", "ft", "gen", "gov", "hon", "rev", "u.k", "u.s.a", "d.c", "a.m", "p.m",
    "b.s", "m.s", "b.a", "m.a", "sc.d", "d.o", "r.n",
})
# A number after one of these is a list or section label, not the end of a sentence:
# "Aim 1. Determine how ...", "Objective 2. Test whether ...".
_SPLIT_LIST_WORDS = frozenset({
    "aim", "aims", "objective", "objectives", "goal", "goals", "step", "steps", "task",
    "tasks", "thrust", "thrusts", "phase", "phases", "project", "projects", "core",
    "cores", "specific", "sa", "hypothesis", "hypotheses", "part", "parts", "study",
    "experiment", "experiments", "question", "questions", "theme", "themes", "area",
    "areas", "component", "components", "module", "modules", "stage", "stages", "track",
    "activity", "activities", "approach", "focus", "direction", "pillar",
})
_SPLIT_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"})
_MULTI_DOT_RE = re.compile(r"(?:[^\W\d_]{1,3}\.)+[^\W\d_]{1,3}", re.UNICODE)
_OPENING_PUNCT = "(\"'“‘["


def _token_before(text: str, end: int) -> Tuple[str, int]:
    """(token, start) of the run of non-space characters ending at `end`, read backwards
    and bounded (see fit_evidence._token_before for why it is bounded)."""
    start = end
    floor = max(0, end - _TOKEN_LOOKBACK)
    while start > floor and not text[start - 1].isspace():
        start -= 1
    return text[start:end], start


def _is_list_position(text: str, token_start: int) -> bool:
    """The token at token_start stands where a list marker stands: at the start of the
    text, after the end of a sentence or a colon, or after a word such as "Aim"."""
    i = token_start
    while i > 0 and text[i - 1].isspace():
        i -= 1
    if i == 0:
        return True
    prev, _ = _token_before(text, i)
    if prev[-1:] in ".:;!?":
        return True
    return prev.strip(_OPENING_PUNCT + ".,:;#").casefold() in _SPLIT_LIST_WORDS


def _sentence_boundaries(text: str) -> List[Tuple[int, int]]:
    """(end_of_sentence, start_of_next) pairs, in order. Linear in len(text).

    A full stop is NOT a boundary after: an initial ("J. Smith", "C. elegans"), a listed
    abbreviation, a dotted abbreviation of any kind ("e.g.", "i.e.", "U.S.", "Ph.D."), a
    list number or roman numeral in list position ("Aim 1.", "2.", "ii."), or when the
    next character is lower case. Decimals ("1.5") never reach here: the regex needs
    whitespace after the full stop.
    """
    out = []
    for m in _BOUNDARY_RE.finditer(text):
        if m.group("para") is not None:
            out.append((m.start(), m.end()))
            continue
        punct = m.group("punct")
        if punct.startswith(".") and len(punct.rstrip("\"'”’)]")) == 1:
            raw, raw_start = _token_before(text, m.start())
            token = raw.lstrip(_OPENING_PUNCT)
            low = token.casefold()
            if len(token) == 1 and token.isalpha():
                continue
            if low in _SPLIT_ABBREVIATIONS or _MULTI_DOT_RE.fullmatch(token):
                continue
            if ((token.isdigit() and len(token) <= 2) or low in _SPLIT_ROMAN) \
                    and _is_list_position(text, raw_start):
                continue
            nxt = text[m.end():m.end() + 1]
            if nxt and nxt.islower():
                continue
        out.append((m.start() + len(punct), m.end()))
    return out


def sentence_spans(text: str, start: int = 0) -> List[Tuple[int, int]]:
    """[start, end) of each sentence from `start`, leading/trailing whitespace excluded.

    Built on this module's own _sentence_boundaries. The boundaries are computed over
    the WHOLE text and then filtered, because the abbreviation guard reads the word
    before a full stop and a slice would hide it.
    """
    if not isinstance(text, str) or not text:
        return []
    start = max(0, min(int(start or 0), len(text)))
    spans = []
    s = start
    for sent_end, next_start in _sentence_boundaries(text):
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
# A sentence that ends by announcing a list the card will not show: "... through the
# following three steps.", "... through three research thrusts." (both were on a front
# in the labelled sample). "the following" anywhere is the same promise.
_LIST_NOUN = (
    r"(?:steps?|thrusts?|aims?|objectives?|goals?|tasks?|parts?|components?|directions?|"
    r"areas?|themes?|questions?|phases?|pillars?|stages?|projects?|activities|efforts|"
    r"topics?|modules?|elements?|contributions?|innovations?|hypotheses|challenges?|"
    r"approaches|tracks?|cores?|studies)"
)
_NUMBER_WORD = r"(?:two|three|four|five|six|seven|several|multiple|\d{1,2})"
_LIST_ANNOUNCED_RE = re.compile(
    r"\bthe\s+following\b|\bfollowing\s+" + _NUMBER_WORD + r"\b|"
    r"\b(?:through|via|by|in|into|around|along|under|with|of|has|have|pursue|pursues|"
    r"address|addresses|includes?|comprises?|contains?)\s+" + _NUMBER_WORD + r"\s+"
    r"(?:[\w-]+\s+){0,3}" + _LIST_NOUN + r"[.:]?$|"
    # "The project integrates two tightly linked research thrusts."
    r"\b" + _NUMBER_WORD + r"\s+(?:[\w-]+\s+){0,3}(?:thrusts|aims|objectives|tasks|steps|"
    r"phases|pillars|themes|modules|parts|components|directions)[.:]?$|"
    r"\b" + _NUMBER_WORD + r"\s+(?:[\w-]+\s+){0,2}" + _LIST_NOUN + r"\s*:",
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
    # What the local splitter joins on purpose: "Aim 1. Determine ...", "e.g. ..." at
    # the very end, a sentence that stops on an abbreviation.
    if re.search(r"(?:\be\.g|\bi\.e|\bet\s+al|\bvs|\bFig|\bDr|\bProf|\betc)\.$", collapsed):
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
    # From the labelled sample: each of these opened a sentence that had been shown.
    # "More broadly, understanding how seafloor communities recover ...", "Technically,
    # the project focuses on ...", "Known as the gravitational redshift, the effect ...".
    "more broadly", "more generally", "more specifically", "more importantly",
    "more recently", "broadly", "technically", "practically", "concretely", "briefly",
    "in brief", "known as", "at the same time", "in this context", "in this regard",
    "in that context", "to address this", "to address these", "to achieve this",
    "to accomplish this", "to fill this", "to test this", "to overcome this",
    "toward this", "towards this", "beyond this", "building on", "based on this",
    "with this", "along with", "as part of", "success will", "success in",
    "successful completion", "completion of", "upon completion", "if successful",
    "once completed", "when completed", "besides", "simultaneously", "lastly",
    "in the long term", "in the long run", "long term", "long-term",
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


# Dependence the opener test cannot see. Every shape is from a sentence that had been
# shown on a front (labelled sample, class "depends on an earlier sentence").
_DEPENDS_RE = re.compile(
    r"(?:"
    # "The Core will also provide", "This project also aims", "Vision also influences":
    # "also" next to the main verb says there was a first thing. Further in ("tests the
    # hypothesis that heme is also a driver of pain") it belongs to a clause of its own.
    # "not only ... but also" is self-contained.
    r"^(?:\S+\s+){1,5}?(?<!but\s)also\b|"
    r"\b(?:will|would|shall|can|may|we|project|proposal|study|core|program|research|work|"
    r"award|team|center)\s+(?:will\s+|would\s+)?also\b|"
    # "discover those key traits": which traits was said in the sentence before.
    r"\bthose\s+(?!who\b|that\b|which\b|with\b|of\b|in\b|from\b|at\b)\w+|\bas\s+well\.$|\bin\s+addition\b|\badditionally\b|\bfurthermore\b|"
    # "addresses that fundamental gap": "that" as a demonstrative. Only after a verb or
    # preposition and before a noun of this kind, because "that" is a relative pronoun
    # everywhere else.
    r"\b(?:address(?:es|ing)?|fill(?:s|ing)?|clos(?:e|es|ing)|bridg(?:e|es|ing)|meets?|"
    r"answers?|tackl(?:e|es|ing)|solv(?:e|es|ing)|overcom(?:e|es|ing)|of|in|to|for|"
    r"with|from|on|toward|towards|at)\s+that\s+(?:[\w-]+\s+){0,2}"
    r"(?:gap|need|problem|question|challenge|goal|end|limitation|issue|hypothesis|"
    r"context|purpose|regard|respect|aim|effort|direction|barrier|shortcoming|vision)\b|"
    # "The second goal is", "The other aim": one of a list the student cannot see.
    r"\bthe\s+(?:first|second|third|fourth|fifth|final|last|other|next|remaining|"
    r"latter|former|same)\s+(?:[\w-]+\s+)?(?:goal|aim|objective|project|thrust|part|"
    r"component|step|phase|task|study|approach|question|theme|area|hypothesis|core)\b|"
    # "The new strain will facilitate", "the new approach": something introduced
    # earlier as new.
    r"\bthe\s+(?:new|novel)\s+[\w-]+|"
    # What comes of the work, said after the work was described.
    r"\b(?:the|these|our|such)\s+(?:results?|findings|outcomes?|insights|data\s+generated|"
    r"knowledge\s+gained|tools\s+developed|methods\s+developed)\b|"
    r"\bresults?\s+(?:from|of)\s+(?:this|the|these|our)\b|"
    r"\b(?:is|are)\s+expected\s+to\b|"
    r"\bthe\s+effect\s+predicts\b|"
    # "to test our hypotheses using ...": which hypotheses was said earlier. "tests the
    # hypothesis that heme drives pain" states it and is left alone.
    r"\b(?:our|these|the|its)\s+(?:(?:central|working|overall|main|key)\s+)?"
    r"hypothes[ie]s\b(?!\s+(?:that|is|are)\b)|"
    # "is currently examining results in comparison with previous ... screens": a
    # progress report. The results are of work the student has not been told about.
    r"\b(?:examin|analy[sz]|compar|interpret|evaluat|review)\w*\s+(?:the\s+)?results\b"
    r")",
    re.IGNORECASE,
)
# "P. palmivora" as the subject: a genus abbreviated because it was spelled out
# earlier. Inside the sentence ("the role of C. auris proteins") it is left alone.
_GENUS_OPENER_RE = re.compile(r"(?:\w+\s+){0,3}(?:caused\s+by\s+|of\s+|in\s+)?[A-Z]\.\s+[a-z]{3,}")


def _has_dangling_reference(collapsed: str) -> bool:
    if _EXPLICIT_BACKREF_RE.search(collapsed):
        return True
    opener = _BACKWARD_OPENER_RE.match(collapsed)
    if opener and not _HERE_WE_RE.match(collapsed):
        return True
    if _DEPENDS_RE.search(collapsed) or _GENUS_OPENER_RE.match(collapsed):
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
    # Reach the candidate test only since the inner-capital shape was added (below).
    "MRNA", "PH",
})
_ROMAN_RE = re.compile(r"^(?:I{1,3}|IV|V|VI{0,3}|IX|X)$")
_ORDINAL_OR_DECADE_RE = re.compile(r"^\d+(?:st|nd|rd|th|s)$", re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[\s/]+")
_EDGE_PUNCT = ".,;:!?()[]{}\"'“”‘’"


def _acronym_candidates(collapsed: str, known: Optional[frozenset] = None) -> List[str]:
    """Tokens that read as an acronym, a code or a symbol, in order, without duplicates.

    `known` replaces _KNOWN_ACRONYMS: plain_summary passes its own, shorter list, since
    an AI sentence is held to a stricter standard than the agency's own words.

    Third shape, added in the repair: a capital anywhere after the first character
    ("mmWave", "scRNAseq", "bnAbs", "eDNA"). The half-of-the-letters test let these
    through because most of their letters are lower case. "McDonald" and "MacArthur"
    have the same shape and cost a sentence; a person's name on the front is refused
    elsewhere anyway (_ADMIN_RE). A capital in first position only ("Tregs", "Wnt")
    cannot be told from "Florida" and is not caught here.

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
                if not is_candidate and any(c.isupper() for c in part[1:]):
                    is_candidate = True
            if not is_candidate or _ROMAN_RE.match(part):
                continue
            # "U.S." reaches here as "U.S": the same word as "US".
            part = part.replace(".", "") if re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]", part) else part
            if part.upper() in (_KNOWN_ACRONYMS if known is None else known):
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


# -- training awards ---------------------------------------------------------

# On a training award the training IS the work, so "trains students in genetics" is the
# sentence that says what the award does. On every other award it is the broader-impacts
# paragraph. NIH activity codes whose official name is a training, education or
# institutional career programme; an NSF award is recognised by its title prefix.
_TRAINING_CODES = frozenset({
    "T32", "T34", "T35", "T37", "T90", "R90", "T15", "TL1", "TL4", "T42", "T14", "T36",
    "D43", "D71", "K12", "KL2", "R25", "R38", "TU2", "RL5", "UE5", "K30",
})
_TRAINING_TITLE_RE = re.compile(
    r"\b(?:REU\s+Site|RET\s+Site|training\s+(?:program|programme|grant|in\b)|"
    r"(?:pre|post)doctoral\s+training|traineeship|research\s+experiences?\s+for|"
    r"scholarships?|CyberCorps|CyberTraining|S-STEM|bootcamp|summer\s+(?:school|institute))",
    re.IGNORECASE,
)


def is_training_award(activity_code: Optional[str] = None, title: Optional[str] = None) -> bool:
    code = (activity_code or "").strip().upper() if isinstance(activity_code, str) else ""
    if code in _TRAINING_CODES:
        return True
    return bool(isinstance(title, str) and _TRAINING_TITLE_RE.search(title))


# -- administrative ----------------------------------------------------------

# People trained, workforce, mentoring, outreach. 5 of the 7 administrative sentences in
# the labelled sample carried a purpose cue, because "train" and "host" were in the
# research-verb list. Skipped on a training award (see above).
_STUDENT_TRAINING_RE = re.compile(
    r"\b(?:"
    r"train(?:s|ed|ing)?\s+(?:\w+\s+){0,4}?(?:students?|undergraduates?|graduates?|"
    r"postdoc\w*|trainees|fellows|researchers|scientists|technicians|teachers|"
    r"professionals|engineers|clinicians|workforce|generation)|"
    # "supports training of early-career researchers" was shown on an instrument award
    # (Gemini Planet Imager 2.0): "of" and "early-career" stood between "training" and
    # the people, and the card then said the award was about training.
    r"training\s+(?:of|for)\b|early[- ]career|early[- ]stage\s+(?:investigators?|researchers?)|"
    r"junior\s+(?:researchers?|investigators?|faculty|scientists?)|"
    r"(?:graduate|undergraduate|doctoral|high[- ]school|k-12|community\s+college)\s+"
    r"(?:and\s+\w+\s+)?students?|"
    r"students?\b|trainees?\b|education(?:al)?\b|technicians?\b|"
    r"mentor(?:s|ed|ing|ship)?\b|workforce|career\s+development|professional\s+development|"
    r"research\s+capacity|capacity[- ]building|build(?:s|ing)?\s+capacity|"
    r"educational?\s+(?:and\s+\w+\s+)?(?:activities|outreach|opportunities|programs?|"
    r"materials|modules|component|plan)|outreach|curricul\w+|bootcamps?|"
    r"next\s+generation\s+of|pipeline\s+of|"
    r"internships?|scholarships?|stipends?"
    r")",
    re.IGNORECASE,
)
# Administrative on any award, a training award included.
_ADMIN_RE = re.compile(
    r"\b(?:"
    r"(?:serv(?:e|es|ing)|in)\s+the\s+national\s+interest|national\s+(?:interest|leadership|"
    r"security\s+needs)|"
    r"the\s+title\s+of\s+(?:the|this)\s+(?:project|award|fellowship)|"
    r"this\s+(?:award|fellowship)\s+to\b|"
    r"(?:is|are)\s+located\s+(?:in|at|on)|"
    r"(?:is|are|was|were|will\s+be)\s+(?:jointly\s+|co-?)?(?:funded|supported|sponsored|"
    r"administered|managed)\s+by|jointly\s+(?:funded|supported)|co-?funded|"
    r"(?:nsf|nih)\s+(?:program|directorate|division|institute|office)|"
    r"established\s+program\s+to\s+stimulate|epscor|"
    r"principal\s+investigators?\s+(?:is|are|will)|advisory\s+(?:board|committee)|"
    r"steering\s+committee|(?:annual|site)\s+(?:report|visit)|"
    r"letters?\s+of\s+support|sub-?awards?|subcontract\w*|"
    # "research opportunities", "opportunities within state government", "a two-week
    # summer bootcamp": what is on offer to people, which the front may not imply
    # even on a training award.
    r"(?:research|training|mentorship|internship|learning|career|employment)\s+opportunities|"
    r"opportunities\s+(?:for|within|to)\b|bootcamps?|internships?|\d+-week|"
    # Who the work is done with, who hosts it, who else pays: "This work is conducted
    # in collaboration with Dr. ... at Oak Ridge National Laboratory" was on four
    # fronts of the first 100 drawn after the refinement. A person's title anywhere in
    # the sentence is the same thing: the front names the work, not the people.
    r"in\s+(?:close\s+)?collaboration\s+with|in\s+partnership\s+with|hosted\s+(?:by|at)|"
    r"underrepresented|under-represented|broaden(?:s|ing)?\s+participation|"
    r"(?:increas|improv|broaden)\w*\s+(?:the\s+)?(?:representation|diversity|participation)|"
    r"funded\s+by|supported\s+by\s+the|existing\s+infrastructure|"
    r"(?:dr|drs|prof|profs|professor)\.?\s+[A-Z]"
    r")",
    re.IGNORECASE,
)


def _is_administrative(collapsed: str, training_award: bool = False) -> bool:
    if _ADMIN_RE.search(collapsed):
        return True
    return (not training_award) and bool(_STUDENT_TRAINING_RE.search(collapsed))


# -- self-description and track record ---------------------------------------

# What the applicant is, has, or has already done. It reads as a description of the lab
# and tells the student nothing about what the award will do: "We have gathered more
# than 17,000 case reports ...", "The research plan builds on recent advancements ...,
# including contributions from the team members.", "... is a new Program within the
# Sidney Kimmel Comprehensive Cancer Center".
_PAST_PARTICIPLE = (
    r"(?:\w+ed|shown|found|built|begun|made|led|seen|grown|given|taken|written|run|"
    r"drawn|known|held|brought|done|been)"
)
_SELF_DESCRIPTION_RE = re.compile(
    r"\b(?:"
    r"(?:we|our\s+(?:group|lab|laboratory|team|center|program|consortium)|"
    r"the\s+(?:pi|pis|team|investigators?|applicants?|candidate|program|core|center|"
    r"consortium|laboratory|lab|group))\s+(?:has|have|had)\s+(?:\w+ly\s+|also\s+|"
    r"now\s+|already\s+|long\s+|since\s+){0,2}" + _PAST_PARTICIPLE + r"|"
    r"we\s+(?:recently|previously|first|originally)\s+\w+|"
    r"we\s+(?:showed|found|discovered|demonstrated|identified|reported|observed|"
    r"established|created|generated|pioneered|invented|published)\b|"
    r"our\s+(?:previous|prior|preliminary|recent|earlier|past|published|own)\s+"
    r"(?:work|studies|study|data|results|findings|research|efforts|publications?)|"
    r"preliminary\s+(?:data|results|studies|findings|work|evidence)|"
    r"build(?:s|ing)?\s+(?:up)?on\b|built\s+(?:up)?on\b|"
    r"contributions?\s+(?:from|of|by)\s+(?:the\s+)?(?:team|pi|pis|investigators?|group)|"
    r"track\s+record|long-?standing|well[- ]positioned|uniquely\s+(?:positioned|qualified|"
    r"suited)|(?:extensive|strong|deep|complementary|combined)\s+(?:expertise|experience)|"
    r"expertise\s+(?:in|of)|years?\s+of\s+(?:experience|research|work|funding|support)|"
    r"(?:is|are)\s+a\s+(?:new|newly|recently)\s+[\w\s-]{0,40}?(?:program|center|centre|"
    r"core|institute|consortium|unit|division|department)\s+(?:within|at|of|in)\b|"
    r"(?:was|were)\s+(?:established|founded|created|launched|formed)\s+in\b|"
    r"since\s+its\s+(?:inception|founding|establishment)|"
    r"has\s+been\s+(?:continuously\s+)?(?:funded|supported|in\s+operation)|"
    r"(?:is|are)\s+(?:led|directed|headed|co-led)\s+by"
    r")",
    re.IGNORECASE,
)
# Renewal history beyond what _EXPLICIT_BACKREF_RE and the openers already catch.
_RENEWAL_RE = re.compile(
    r"\b(?:renewal|resubmission|continuation|competing\s+(?:renewal|continuation)|"
    r"(?:now\s+)?in\s+its\s+\w+\s+(?:year|decade|cycle)|"
    r"(?:for|over)\s+(?:the\s+)?(?:past|last)\s+\w+\s+(?:years|decades)|"
    r"previous(?:ly)?\s+funded|prior\s+(?:support|award|funding))\b",
    re.IGNORECASE,
)


def _is_self_description(collapsed: str) -> bool:
    return bool(_SELF_DESCRIPTION_RE.search(collapsed) or _RENEWAL_RE.search(collapsed))


# -- the two public tests ----------------------------------------------------

def disqualified(sentence: str, *, training_award: bool = False) -> Optional[str]:
    """None when the sentence qualifies, else the first reason that applies.

    Reasons: "too_short", "too_long_words", "too_long_chars", "no_finite_verb",
    "subordinator", "dangling_reference", "unexpanded_acronym", "label_residue",
    "housekeeping" (added after review; not in the phase 3 contract's list),
    "list_announcement", "self_description", "administrative", "hype_or_jargon" (added
    2026-09-29 from the labelled sample), "question", "no_topic" (added in the repair of
    the same day). `training_award` lifts the student-training half of
    "administrative" and nothing else.

    Qualifying is necessary and not sufficient: select_agency_sentence also requires
    the sentence to state the work (cue_strength).
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
    if _LIST_ANNOUNCED_RE.search(collapsed):
        return "list_announcement"
    # A question is one of a run of questions, or rhetoric. The one that was shown was
    # the third of three examples on an REU site about music and the brain, and it was
    # about deaf children: the card misdescribed the site.
    if collapsed.rstrip("\"'”’)]").endswith("?"):
        return "question"
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
    if _is_self_description(collapsed):
        return "self_description"
    if _is_administrative(collapsed, training_award):
        return "administrative"
    if _EMPTY_WORDS_RE.search(collapsed) or _has_stacked_modifiers(collapsed):
        return "hype_or_jargon"
    if len(_topic_words(collapsed)) < MIN_TOPIC_WORDS:
        return "no_topic"
    return None


# -- does the sentence say what the award does? -------------------------------

# The first rule had one regex with a bare "will <research verb>" alternative, and a
# verb list that held "provide", "train" and "host". Of 66 sampled sentences with that
# cue, 46 stated the work; the other 20 were broader-impacts, outcomes and background
# whose subject was not the award. The cue is now read in three steps: an award-naming
# SUBJECT at the start of the clause, then what stands between it and the verb ("will",
# "aims to", an adverb), then the VERB, which decides between "states the work" and
# "states only a hoped-for outcome".
_AWARD_SUBJECT_RE = re.compile(
    r"(?<![\w-])(?:"
    r"this\s+" + _SELF_NOUNS + r"|"
    r"the\s+(?:(?:proposed|present|current|planned)\s+)?(?:(?:research|project)\s+)?"
    r"(?:project|proposal|study|studies|research|work|application|award|program|"
    r"investigation|experiments|team|investigators?|researchers|conference|workshop)|"
    r"the\s+(?:proposed|planned)\s+(?:research|work|studies|study|experiments|project)|"
    r"the\s+[\w’'-]+\s+(?:lab|laboratory|group)|"
    r"our\s+(?:lab|laboratory|group|team|project|research|proposal|study|work)|"
    r"we|investigators|researchers"
    r")(?![\w-])",
    re.IGNORECASE,
)
# What may stand before the subject: nothing, or a short introductory phrase that ends
# in a comma or is one of these. "All software produced by this project will ..." has a
# subject of its own before "this project" and is not read as a cue.
_CUE_INTRO_RE = re.compile(
    r"(?:(?:here|can|could|how\s+can|how\s+do|how\s+will),?|"
    r"(?:in|by|using|through|with|for|to|toward|towards|under)\s+[^.;:]{0,90},|"
    r"in\s+this\s+(?:project|proposal|study|application|work|research|award),?|"
    r"in\s+the\s+proposed\s+(?:project|study|research|work),?)\s*$",
    re.IGNORECASE,
)
_GOAL_RE = re.compile(
    r"(?:the|our)\s+(?:(?:overall|primary|main|central|principal|major|overarching|"
    r"immediate|specific|key|core|broad|general)\s+)?(?:goal|objective|purpose|aim)s?\s+"
    r"(?:(?:of|for)\s+(?:this|the|our)\s+(?:[\w-]+\s+){0,3}?(?:project|proposal|study|"
    r"research|work|application|award|program|effort|investigation)\s+)?"
    r"(?:is|are)\s+(?:to\s+)?",
    re.IGNORECASE,
)
_GOAL_OWNED_RE = re.compile(r"our\b|.*\b(?:of|for)\s+(?:this|the|our)\b", re.IGNORECASE)
_CUE_SKIP = frozenset({
    "will", "would", "shall", "is", "are", "also", "first", "then", "further",
    "thus", "directly", "both", "to",
})
# Next to the main verb these make the sentence a status report on work under way ("The
# team is currently examining results ...", "This component currently supports
# correlative science for tissues being collected from eight trials"). They were in
# _CUE_SKIP, so the rule stepped over them and read the verb behind as the work.
_CUE_STATUS = frozenset({"currently", "now", "presently", "already", "continually",
                         "continuously", "routinely"})
_CUE_INTENT = frozenset({
    "aim", "aims", "seek", "seeks", "propose", "proposes", "plan", "plans", "intend",
    "intends", "strive", "strives", "attempt", "attempts", "designed", "intended",
    "hope", "hopes",
})
# Verbs of doing the work. Matched as a prefix of the word, so "investigates",
# "investigating" and "investigate" are one entry.
_WORK_VERBS = (
    "investigat", "stud", "examin", "explor", "determin", "identif", "characteri",
    "test", "measur", "map", "defin", "elucidat", "uncover", "dissect", "decipher",
    "probe", "probes", "probing", "develop", "build", "design", "creat", "engineer", "construct", "establish",
    "use", "uses", "using", "appl", "combin", "integrat", "leverag", "employ", "utili",
    "analy", "compar", "model", "quantif", "evaluat", "assess", "focus", "ask",
    "discover", "find", "implement", "validat", "optimi", "synthesi", "simulat",
    "track", "monitor", "screen", "sequenc", "imag", "translat", "adapt", "extend",
    "formulat", "deriv", "prove", "proves", "proving", "comput", "collect", "survey", "interview", "record",
    "isolat", "purif", "fabricat", "demonstrat", "search", "look", "describ",
    "document", "reconstruct", "resolv", "clarif", "unravel", "interrogat", "delineat",
    # "make" and "take" were here. "makes use of well established Drosophila models"
    # and "take advantage of viral protein expression" name a technique and not the
    # question; "makes", "takes" state no work on their own.
    "understand", "learn", "explain", "bring",
    "support", "address", "tackl", "pursu", "conduct", "perform", "carry", "carries",
    "targets", "target",
)
# On a training award these are the work. Anywhere else they are administrative.
_TRAINING_VERBS = ("train", "educat", "prepar", "host", "mentor", "teach", "offer",
                   "provid", "recruit", "equip", "serv")
# Verbs that state what is hoped to come of the work, not the work: "will provide new
# insights", "will lead to", "will enhance clinical practice". Always second choice.
_OUTCOME_VERBS = (
    "provid", "generat", "enhanc", "lead", "result", "reveal", "yield", "enabl",
    "advanc", "contribut", "inform", "help", "facilitat", "transform", "revolutioni",
    "produc", "offer", "shed", "lay", "pave", "open", "increas", "benefit", "impact",
    "fill", "allow", "promot", "foster", "strengthen", "expand", "improv", "reduc",
    "accelerat", "deepen", "broaden", "serv", "have", "has", "be", "become", "justif",
    "chang", "sav", "aid",
)
# After "aims to" / "seeks to" the verb is the applicant's own statement of the work, so
# only these stay second choice there ("aims to improve voltage indicators" is work;
# "aims to revolutionize spectral analysis" is a hope).
_OUTCOME_VERBS_AFTER_INTENT = (
    "reveal", "guid", "inform", "expand", "revolutioni", "transform", "advanc", "enhanc", "contribut", "benefit", "serv",
    "address", "increas", "fill", "help", "facilitat", "promot", "foster", "broaden",
    "strengthen", "meet", "have", "be",
)
_OUTCOME_ONLY_RE = re.compile(
    r"\b(?:will|would|may|could|can|should)\s+(?:ultimately\s+|also\s+|thus\s+|\w+ly\s+)?"
    r"(?:lead|result|contribute|pave|shed|lay)\b|"
    r"\b(?:improved|better|deeper|new|greater|fuller|mechanistic|fundamental)\s+"
    r"(?:understanding|insights?|knowledge)\b|"
    r"\bnew\s+(?:\w+\s+)?(?:insights?|knowledge)\b|\binsights?\s+into\b|"
    r"\brelevan(?:t|ce)\s+to\s+public\s+health\b|\blong[- ]term\s+(?:goal|objective|aim)|"
    r"\bhas\s+the\s+potential\b|\bhave\s+the\s+potential\b|\bpotential\s+to\b|\bultimately\b|"
    r"\bimportant\s+implications\b|\bbroad\s+implications\b|\bimplications\s+for\b",
    re.IGNORECASE,
)
# Words that carry no content and came with weak sentences in the sample. Not a reason
# to reject ("aims to revolutionize saffron production through the development of
# lab-grown Crocus sativus stigma tissue" does say what is built): a sentence without
# them is preferred when there is one.
_HYPE_RE = re.compile(
    r"\b(?:revolutioni[sz]\w*|unprecedented|novel|state-of-the-art|holistic|"
    r"cutting-edge|paradigm\w*|transformative|groundbreaking|game-chang\w+|"
    r"next-generation|world-class|innovative)\b",
    re.IGNORECASE,
)

# Rejected outright, unlike _HYPE_RE: words that say nothing and stood in sentences that
# said nothing else ("developing holistic approaches to integrating representation
# learning ..."), and the "-mediated" compound, which no reader outside the field can
# unpack ("oxidative stress-mediated pulmonary vascular remodeling"). This is a small
# part of what makes a sentence jargon. 8 of the 150 labelled sentences were jargon and
# these two patterns catch 3 of them; the rest pass, and that is reported, not solved.
_EMPTY_WORDS_RE = re.compile(
    r"\b(?:revolutioni[sz]\w*|unprecedented|state[- ]of[- ]the[- ]art|holistic|"
    r"cutting[- ]edge|paradigm-shifting|game-chang\w+|[\w-]+-mediated|"
    # Added in the repair. "state of the art" without hyphens walked past the hyphenated
    # entry. "premier" and "world-class" praise the place. The last two are abstraction
    # with no object: "addresses a fundamental step in distributional data analysis",
    # "bring a new level of scalability and transparency to machine learning".
    r"transformative|premier|world[- ]class|"
    r"(?:address(?:es)?|tackl(?:e|es)|solv(?:e|es))\s+an?\s+(?:fundamental|critical|key|"
    r"important|central|major)\s+(?:step|challenge|problem|question|issue|need|gap)\b"
    r"(?!\s+(?:of|in\s+how)\b|:)|"
    r"a\s+new\s+level\s+of)\b",
    re.IGNORECASE,
)

# Four modifiers in a row before a noun: "a transformative integrative experimentally
# informed digital twin technology". No tagger, so a modifier is a word with one of
# these endings, and "and", "or" or a comma ends the run. Three in a row is ordinary
# ("novel statistical and computational"); the four-word runs read so far were all
# unreadable.
_MODIFIER_ENDINGS = ("ive", "ical", "ally", "ously", "ional", "ized", "ised", "ated",
                     "ware", "fast", "field", "scale", "based", "driven", "informed",
                     "enabled", "specific", "ary", "ous", "ic", "al")
_STACK_MIN = 4


def _has_stacked_modifiers(collapsed: str) -> bool:
    run = 0
    for raw in collapsed.split(" "):
        word = raw.strip(_EDGE_PUNCT).casefold()
        ends_run = raw.endswith((",", ";", ":")) or word in ("and", "or", "of", "to", "in")
        if len(word) > 4 and word.endswith(_MODIFIER_ENDINGS) and not ends_run:
            run += 1
            if run >= _STACK_MIN:
                return True
        else:
            run = 0
    return False


# -- does the sentence name a topic? ------------------------------------------

# A sentence can state the work and name nothing: "The research team will develop
# prototypes and evaluate them in real-world settings." What is left once function
# words, words for the award itself, generic verbs and generic nouns are taken out is
# what the student can decide by. Hand-written lists (2026-09-29, by the AI model that
# did the repair), biased towards calling a word generic: a word wrongly called generic
# costs a sentence, a word wrongly called a topic shows an empty one.
_FUNCTION_WORDS = frozenset("""
a an the this these that those of in on at to for from by with within without into onto
over under between among across through throughout during after before and or but nor so
as than then also both each either neither not no is are was were be been being has have
had do does did will would shall should can could may might must we our us it its their
they them which who whom whose what when where why how via per about up out off more most
less least very such new novel other another same own well here there all any some many
several various multiple one two three four five six seven eight nine ten first second
third if while whether toward towards against upon along around real
""".split())
_AWARD_WORDS = frozenset("""
project projects proposal proposals study studies research work application award program
programme investigation investigations team teams investigator investigators researcher
researchers goal goals objective objectives aim aims purpose overall primary main central
proposed present current planned long-term effort efforts plan plans
""".split())
_GENERIC_NOUNS = frozenset("""
approach approaches method methods methodology methodologies tool tools technique
techniques technology technologies framework frameworks model models prototype prototypes
analytics suite suites system systems platform platforms strategy strategies solution
solutions capability capabilities hypothesis hypotheses question questions problem
problems challenge challenges issue issues aspect aspects way ways set sets range variety
number series kind kinds type types level levels setting settings world real-world state
art results result data information knowledge understanding insight insights foundation
basis step steps area areas field fields process processes mechanism mechanisms role
roles factor factors feature features property properties context contexts scenario
scenarios application applications advance advances innovation innovations impact impacts
""".split())
_GENERIC_VERB_STEMS = (
    "develop", "investigat", "examin", "explor", "determin", "identif", "characteri",
    "establish", "creat", "build", "design", "evaluat", "assess", "address", "focus",
    "seek", "propos", "utili", "employ", "appl", "conduct", "perform", "understand",
    "provid", "support", "enabl", "advanc", "improv", "test", "use", "using", "study",
    "studi", "integrat", "combin", "leverag", "demonstrat", "implement", "validat",
)
# How many topic words a sentence needs. Four was tried first and took out "This
# proposal will develop a novel system to study aging of the brain in a dish.", which
# has three and is exactly the sentence a student can decide by.
MIN_TOPIC_WORDS = 3
# A sentence repeats the title when it adds fewer than MIN_NEW_WORDS topic words to it
# AND at least TITLE_SHARE of its own topic words are the title's. The second half is
# there because the first alone removed 69 of 474 shown sentences, and many of those
# were the best on the deck: a plain restatement of a jargon title ("Our goal is to
# devise new methods to promote heart repair." under "Hippo-YAP signaling in cardiac
# regenerative repair") adds few words and shares few.
MIN_NEW_WORDS = 4
TITLE_SHARE = 0.6
_TOPIC_SPLIT_RE = re.compile(r"[\s/]+")


def _topic_key(word: str) -> str:
    """The form two words are compared in: lower case, plural and the commonest
    endings off, at most seven letters. "modeling" and "models", "statistical" and
    "statistics", "reconstruction-aware" and "Reconstruction-Aware" come out equal."""
    w = word.casefold()
    for tail in ("'s", "’s"):
        if w.endswith(tail):
            w = w[:-2]
    for tail in ("ies", "es", "s", "ing", "ed", "al", "ic"):
        if w.endswith(tail) and len(w) - len(tail) >= 4:
            w = w[: -len(tail)]
            break
    return w[:7]


def _topic_words(collapsed: str) -> List[str]:
    """Keys (_topic_key) of the words that name something, in order, without duplicates."""
    out: List[str] = []
    for raw in _TOPIC_SPLIT_RE.split(collapsed):
        token = raw.strip(_EDGE_PUNCT + "-–—")
        for part in ([token] if token.casefold() in _GENERIC_NOUNS else re.split(r"[-–—]", token)):
            part = part.strip(_EDGE_PUNCT)
            low = part.casefold()
            if len(low) < 2 or not any(c.isalpha() for c in low):
                continue
            if low in _FUNCTION_WORDS or low in _AWARD_WORDS or low in _GENERIC_NOUNS:
                continue
            if low.endswith("ly") and len(low) > 4:
                continue
            if any(low.startswith(v) for v in _GENERIC_VERB_STEMS):
                continue
            key = _topic_key(low)
            if key not in out:
                out.append(key)
    return out

CUE_NONE, CUE_OUTCOME, CUE_WORK = 0, 1, 2


def _starts_with_any(word: str, stems) -> bool:
    return any(word.startswith(s) for s in stems)


def _predicate_strength(rest: str, *, from_goal: bool, training_award: bool) -> int:
    """Strength of what follows the subject. `rest` starts after the subject."""
    tokens = [t.strip(_EDGE_PUNCT).casefold() for t in rest.split()[:9]]
    tokens = [t for t in tokens if t]
    i = 0
    intent = from_goal
    auxiliary = False
    while i < len(tokens):
        tok = tokens[i]
        if tok in _CUE_STATUS:
            return CUE_NONE
        if tok in _CUE_SKIP or (tok.endswith("ly") and len(tok) > 4):
            auxiliary = auxiliary or tok in ("will", "would", "shall", "is", "are")
            i += 1
            continue
        # "describes and seeks to define": the second verb is the one that counts.
        if i + 2 < len(tokens) and tokens[i + 1] == "and" and tokens[i + 2] in _CUE_INTENT:
            i += 2
            continue
        if tok in _CUE_INTENT and not intent:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if nxt == "to" or tok.startswith("propos") or tok in ("designed", "intended"):
                intent = True
                i += 1
                continue
        break
    if i >= len(tokens):
        return CUE_NONE
    verb = tokens[i]
    # "We uncovered a previously unknown mode of cell competition ...": simple past
    # after the subject is what was found before the award, not what it will do.
    if verb.endswith("ed") and not intent and not auxiliary:
        return CUE_NONE
    if intent:
        if tokens[i - 1] != "to" and not from_goal:
            # "We propose investigating ...", "We propose a framework ...": the object
            # of "propose" is the work whatever its first word is.
            return CUE_OUTCOME if _starts_with_any(verb, _OUTCOME_VERBS_AFTER_INTENT) else CUE_WORK
        if training_award and _starts_with_any(verb, _TRAINING_VERBS):
            return CUE_WORK
        if _starts_with_any(verb, _OUTCOME_VERBS_AFTER_INTENT):
            return CUE_OUTCOME
        return CUE_WORK
    if training_award and _starts_with_any(verb, _TRAINING_VERBS):
        return CUE_WORK
    if _starts_with_any(verb, _WORK_VERBS):
        return CUE_WORK
    if _starts_with_any(verb, _OUTCOME_VERBS):
        return CUE_OUTCOME
    return CUE_NONE


def cue_strength(sentence: str, *, training_award: bool = False) -> int:
    """CUE_WORK (2): the sentence says what the award does or studies.
    CUE_OUTCOME (1): it says only what the award is hoped to bring about.
    CUE_NONE (0): neither. Background, however accurate, is CUE_NONE.
    """
    if not isinstance(sentence, str):
        return CUE_NONE
    collapsed = _collapse(sentence)
    if _is_housekeeping(collapsed):
        return CUE_NONE
    best = CUE_NONE
    goal = _GOAL_RE.match(collapsed)
    if goal:
        best = _predicate_strength(collapsed[goal.end():], from_goal=True,
                                   training_award=training_award)
        # "The goal is to cut the traditional 10-year crop breeding cycle in half.":
        # whose goal, and of what, was said in the sentence before. With "of this
        # project" or "Our" the sentence names its own subject.
        if best == CUE_WORK and not _GOAL_OWNED_RE.match(goal.group(0)):
            best = CUE_OUTCOME
    else:
        for m in _AWARD_SUBJECT_RE.finditer(collapsed):
            before = collapsed[:m.start()]
            if before.strip() and not _CUE_INTRO_RE.fullmatch(before.strip() + " "):
                continue
            best = max(best, _predicate_strength(collapsed[m.end():], from_goal=False,
                                                 training_award=training_award))
            break
    if best == CUE_WORK and _OUTCOME_ONLY_RE.search(collapsed):
        best = CUE_OUTCOME
    return best


def has_purpose_cue(sentence: str, *, training_award: bool = False) -> bool:
    """True when the sentence says what the award sets out to do, in its own words."""
    return cue_strength(sentence, training_award=training_award) == CUE_WORK


def _repeats_title(collapsed: str, title: Optional[str]) -> bool:
    """The sentence is the title over again, or the title inside "This project will
    ...". It would put the same words on the card twice, directly under each other,
    and it helps least where help is needed: under a title that is jargon.

    Until the repair this compared the START of the sentence with the title, which only
    caught a sentence that opens with it. It now counts the topic words the sentence
    adds to the title (_topic_words, compared by _topic_key): see MIN_NEW_WORDS and
    TITLE_SHARE.
    "This research project aims to investigate statistical challenges in quantum
    learning." under "Statistical Problems in Quantum Learning" adds none.
    """
    t = normalise_text(title).rstrip(".")
    if len(t) < 12:
        return False
    if normalise_text(collapsed).startswith(t):
        return True
    in_title = set(_topic_words(_collapse(title)))
    if not in_title:
        return False
    topic = _topic_words(collapsed)
    if not topic:
        return False
    new = [w for w in topic if w not in in_title]
    return len(new) < MIN_NEW_WORDS and (len(topic) - len(new)) >= TITLE_SHARE * len(topic)


# Whether a sentence that states only a hoped-for outcome may be shown when no sentence
# in the scan states the work. In the labelled sample these were the 12 "weak" ones:
# they do name the subject ("how viruses evolve", "immunotherapy-associated kidney
# injury") and they do not say what anyone will do. Off: the owner's test is whether a
# student can tell what the lab does, and a labelled AI one-liner can fill the gap.
SHOW_OUTCOME_ONLY = False


def select_agency_sentence(text: str, *, title: Optional[str] = None,
                           activity_code: Optional[str] = None) -> Optional[dict]:
    """{"text", "start", "end", "cue": bool, "strength": int} with
    text == text_in[start:end], or None.

    Among the first SCAN_SENTENCES sentences after the label, of those that qualify
    (disqualified() is None) and state the work (cue_strength == CUE_WORK): the first
    one without a hype word, else the first one. Nothing else is shown.

    The addendum's "if none has a cue, the first qualifying sentence is used" and its
    later narrowing to a sentence sharing a title word are both gone. Measured on 150
    shown sentences, 84 had come through that door and 58 of them were field
    background: true of the field, silent about the award.

    `title` removes a sentence that repeats it, and with `activity_code` decides
    whether this is a training award (is_training_award), the one case where "trains
    students in ..." is the work and not the broader-impacts paragraph.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    training = is_training_award(activity_code, title)
    spans = sentence_spans(text, strip_label(text))[:SCAN_SENTENCES]
    with_hype = None
    outcome_only = None
    for a, b in spans:
        sentence = text[a:b]
        if disqualified(sentence, training_award=training) is not None:
            continue
        collapsed = _collapse(sentence)
        if title and _repeats_title(collapsed, title):
            continue
        strength = cue_strength(sentence, training_award=training)
        if strength == CUE_NONE:
            continue
        found = {"text": sentence, "start": a, "end": b, "cue": strength == CUE_WORK,
                 "strength": strength}
        if strength == CUE_WORK:
            if not _HYPE_RE.search(collapsed):
                return found
            if with_hype is None:
                with_hype = found
        elif outcome_only is None:
            outcome_only = found
    if with_hype is not None:
        return with_hype
    return outcome_only if SHOW_OUTCOME_ONLY else None


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
    return select_agency_sentence(text, title=(row or {}).get("grant_title"),
                                  activity_code=(row or {}).get("activity_code"))


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
        found = select_agency_sentence(agency_text["text"], title=row.get("grant_title"),
                                       activity_code=row.get("activity_code"))
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


def rejection_counts(text: str, *, title: Optional[str] = None,
                     activity_code: Optional[str] = None) -> Dict[str, int]:
    """Reason -> count over the scanned sentences. For the measuring scripts, so the
    share without a sentence can be explained and not only counted. A sentence that
    passes every test and does not state the work counts as "no_work_statement"
    ("outcome_only" when it states a hoped-for outcome)."""
    counts: Dict[str, int] = {}
    if not isinstance(text, str):
        return counts
    training = is_training_award(activity_code, title)
    for a, b in sentence_spans(text, strip_label(text))[:SCAN_SENTENCES]:
        reason = disqualified(text[a:b], training_award=training)
        if reason is None:
            strength = cue_strength(text[a:b], training_award=training)
            reason = {CUE_WORK: "qualifies", CUE_OUTCOME: "outcome_only"}.get(
                strength, "no_work_statement")
        counts[reason] = counts.get(reason, 0) + 1
    return counts
