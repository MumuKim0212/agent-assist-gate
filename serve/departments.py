"""`refuse` -> the owning department.

"Not covered" is a dead end; "this belongs to 회원관리팀" is an answer the agent can
act on. The routing table is one document, `manual:부서이관건`, and it is a
spreadsheet: E=NO / F=팀명 / H=세부내용 rows in the record's `cells`, which is why
this is a parse and a match rather than a field read.

Two rules shape everything below.

**Match the 세부내용 topics, never the team names.** A caller says "회비 감면",
never "회원관리팀".

**A wrong department is worse than none, because the caller gets transferred
twice.** So the matcher is deliberately conservative in two ways: every
identifying word of a topic must appear in the query, and exactly one team may
come out. Either rule failing returns None, and `refuse` then says "not covered"
with no department -- which is the honest answer and the one the caller can
recover from.
"""
import re

ROUTING_ID = "manual:부서이관건"

# Procedural filler in the 세부내용 column, not topics. Dropping them costs no
# precision and is what makes short topics matchable at all.
FILLER = {"관련", "문의", "및"}


def _rows(doc):
    """`cells` -> {row number: {column: value}}. Entries are "<col><row>=<value>"."""
    rows = {}
    for cell in doc.get("cells") or []:
        ref, _, value = cell.partition("=")
        match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
        if match:
            rows.setdefault(int(match.group(2)), {})[match.group(1)] = value
    return rows


def table(doc):
    """-> {팀명: [세부내용, ...]}, in sheet order.

    A team's first topic sits on the same row as its name and the rest follow on
    H-only rows, so the walk carries the current team forward. The header row is
    not a team because its NO ("NO") is not a number.
    """
    rows = _rows(doc)
    teams, current = {}, None
    for number in sorted(rows):
        row = rows[number]
        if row.get("F") and row.get("E", "").isdigit():
            current = row["F"].strip()
            teams.setdefault(current, [])
        if current and row.get("H"):
            teams[current].append(row["H"].strip())
    return teams


def topic_terms(topic):
    """A topic's identifying words: "1. 회비 감면 문의" -> ["회비", "감면"].

    One-character fragments are not evidence of anything.
    """
    topic = re.sub(r"^\s*\d+\s*[.)]\s*", "", topic)
    return [part for part in re.split(r"[^0-9A-Za-z가-힣]+", topic)
            if len(part) >= 2 and part not in FILLER]


def _matches(query, terms):
    """Conjunctive: all of the topic's words, or no match. This is what keeps a
    generic word from routing on its own. The query is squeezed rather than
    tokenised so that "회비 감 면" style spacing noise still matches -- Korean
    spacing is not reliable in typed text."""
    return bool(terms) and all(term.upper() in query for term in terms)


def lookup(query, doc):
    """query -> 팀명, or None when the table does not clearly own the question."""
    squeezed = "".join(query.split()).upper()
    found = {team for team, topics in table(doc).items()
             if any(_matches(squeezed, topic_terms(topic)) for topic in topics)}
    return found.pop() if len(found) == 1 else None
