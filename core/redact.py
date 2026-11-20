"""Identifier patterns, used wherever a query leaves the process.

An embedding or rerank **API** moves the privacy boundary: the caller's words
now leave the machine on every search. This module holds the regex patterns that
scrub identifiers from a query before that happens, and nothing else.

**Queries only. Never documents.** A document's numbers can be the answer itself
(a department's phone number is what a `refuse` is looking for), so scrubbing
documents would delete content rather than protect anyone.

A regex list cannot catch names. That residual risk is why the project treats
redaction as data minimisation, not as a guarantee.
"""
import collections
import re

Redaction = collections.namedtuple("Redaction", "text kinds")

# Ordered, and the order is the design: these patterns overlap, so the specific
# ones have to consume their digits before the generic run at the bottom does.
PATTERNS = [
    # 981010-1234567. Before every other digit rule -- 13 digits with a hyphen
    # also match the phone pattern and the generic one.
    ("주민등록번호", re.compile(r"\d{6}\s*[-~–]\s*[1-4]\d{6}")),
    # 123-45-67890. Distinctive 3-2-5 grouping; bare 10 digits fall to 식별번호.
    ("사업자등록번호", re.compile(r"\d{3}\s*-\s*\d{2}\s*-\s*\d{5}")),
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    # 010-1234-5678, 01012345678, 02-123-4567, 0212345678.
    ("전화번호", re.compile(r"(?:01\d|0\d{1,2})[-.\s]?\d{3,4}[-.\s]?\d{4}")),
    # Keyword-anchored: neither has a shape a regex can recognise on its own.
    # Anything unanchored still falls to 식별번호 below.
    ("자격증번호", re.compile(r"(?<=자격증)[^\d\n]{0,6}[\dA-Za-z][\dA-Za-z-]{7,}")),
    ("계좌번호", re.compile(r"(?<=계좌)[^\d\n]{0,6}\d[\d-]{7,}")),
    # Everything left carrying ten or more digits, single hyphens allowed between
    # them. Ten is the floor because the numbers that legitimately appear in
    # queries -- amounts, dates -- carry eight digits or fewer.
    ("식별번호", re.compile(r"\d(?:-?\d){9,}")),
]


def scrub(text):
    """Returns (scrubbed text, the kinds that fired).

    The kinds are kept because a silent redactor and a broken one look identical
    from the outside; callers count them so a run can prove it scrubbed.
    """
    kinds = []
    for kind, pattern in PATTERNS:
        text, hits = pattern.subn(f"[{kind}]", text)
        if hits:
            kinds.append(kind)
    return Redaction(text, tuple(kinds))
