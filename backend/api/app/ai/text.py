"""Plain-text helpers: matching quotes to sources, search terms, and near-duplicate questions.

Everything here is deterministic, so the checks it backs can be trusted more than the model whose
output they check.
"""

import re
import unicodedata

# Typographic variants a model (or a PDF) may use for the same characters.
_EQUIVALENTS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        "­": "",
        "​": "",
    }
)
# A word broken across lines in a PDF: "photo-\nsynthesis".
_HYPHENATED = re.compile(r"(\w)-[ \t]*\n\s*(\w)")
_SPACE = re.compile(r"\s+")
_ELLIPSIS = re.compile(r"\.\.\.+|…|\[\s*\.\.\.\s*\]")
_WORD = re.compile(r"\w+")

# A quote must be at least this long to count as evidence: a word or two matches anywhere.
MIN_QUOTE_WORDS = 3
MIN_QUOTE_CHARS = 15

STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if in into is it
    its itself just me more most my myself no nor not now of off on once only or other our ours
    ourselves out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very was we were
    what when where which while who whom why will with would you your yours yourself yourselves
    shall may might must one ones upon within without""".split()
)


def normalize(text: str) -> str:
    """Text as compared: same characters for typographic variants, case and spacing ignored."""
    text = unicodedata.normalize("NFKC", text).translate(_EQUIVALENTS)
    text = _HYPHENATED.sub(r"\1\2", text)
    return _SPACE.sub(" ", text).strip().casefold()


def words(text: str) -> list[str]:
    """The words of `text` as compared, so punctuation, case and spacing don't matter."""
    return _WORD.findall(normalize(text))


def quote_found(quote: str, source: str) -> bool:
    """Whether `quote` appears word for word in `source` (ignoring punctuation, case, spacing and
    typographic variants). A quote may leave words out with "..." if every part is at least
    three words long and the parts appear in order."""
    parts = [words(p) for p in _ELLIPSIS.split(quote)]
    parts = [p for p in parts if p]
    if not parts:
        return False
    if sum(len(p) for p in parts) < MIN_QUOTE_WORDS:
        return False
    if sum(len(w) + 1 for p in parts for w in p) < MIN_QUOTE_CHARS:
        return False
    if len(parts) > 1 and any(len(p) < MIN_QUOTE_WORDS for p in parts):
        return False
    haystack = " " + " ".join(words(source)) + " "
    start = 0
    for part in parts:
        needle = " " + " ".join(part) + " "
        found = haystack.find(needle, start)
        if found < 0:
            return False
        start = found + len(needle) - 1
    return True


def stem_word(word: str) -> str:
    """A light stemmer, so "cells" finds "cell" and "dividing" finds "divide"."""
    if len(word) <= 4 or word.isdigit():
        return word
    for suffix, replacement in (
        ("ies", "y"),
        ("sses", "ss"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "s" and word.endswith("ss"):
                return word
            word = word[: len(word) - len(suffix)] + replacement
            break
    # "divide" and "dividing" both become "divid".
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def terms(text: str) -> list[str]:
    """Search terms in `text`: words, lower-cased and stemmed, without common words."""
    return [
        stem_word(w)
        for w in _WORD.findall(normalize(text))
        if w not in STOPWORDS and (len(w) > 1 or w.isdigit())
    ]


def similarity(a: str, b: str) -> float:
    """How alike two questions' wording is, from 0 to 1 (shared terms over all terms)."""
    left, right = set(terms(a)), set(terms(b))
    if not left or not right:
        return 1.0 if normalize(a) == normalize(b) else 0.0
    return len(left & right) / len(left | right)


# Stems this alike are the same question, near enough for a teacher to want only one.
DUPLICATE_SIMILARITY = 0.8


def same_question(a: str, b: str) -> bool:
    return normalize(a) == normalize(b) or similarity(a, b) >= DUPLICATE_SIMILARITY
