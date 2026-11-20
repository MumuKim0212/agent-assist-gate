"""등급 / 대상 / 행위 -- the three structured attributes that decide the answer.

In this kind of call center many questions have nearly identical wording and
completely different answers: "초급 교육 신청" vs "중급 교육 신청", "회원사" vs
"비회원사", "신규 발급" vs "재발급". Embedding and BM25 scores stay high while the
wrong document is picked, and the top1/top2 margin does not help -- both
competing documents score high. Three attributes separate them.

Documents carry tags (`attributes` in docs.jsonl). A query's attributes are
extracted with a closed vocabulary, so the common path needs no model call.

The semantics that matter:

    query 중급  vs. document 초급           -> mismatch, demote to clarify
    query absent vs. document 초급          -> NOT a mismatch. Never demotes
    query 중급  vs. document not applicable -> NOT a mismatch

An attribute absent from the query means the caller did not say it. Treating
that as a mismatch demotes every under-specified question to clarify and
collapses answer coverage. Omission is caught one rule later instead, by the
competing documents differing among themselves -- see
`competing_attributes_differ()`.
"""

ATTRIBUTES = ("등급", "대상", "행위")

# Closed vocabularies. Empty is a valid state: extract() then finds nothing and
# "nothing stated" is a non-mismatch, so rule 3 simply never fires.
VOCABULARY = {
    "등급": {
        "초급": ("초급",),
        "중급": ("중급",),
        "고급": ("고급",),
        "특급": ("특급",),
    },
    "대상": {
        # 비회원사 CONTAINS 회원사, so surface length decides -- see extract().
        "회원사": ("회원사", "회원업체"),
        "비회원사": ("비회원사", "비회원업체", "비회원"),
        "개인회원": ("개인회원", "개인 회원"),
    },
    "행위": {
        "신규": ("신규", "처음 발급", "새로 발급", "최초 발급", "처음 만들"),
        # "으로 승급" and not bare 승급: 승급교육 is a training course that
        # changes nothing, while "중급으로 승급" is a grade change.
        "변경": ("등급변경", "등급 변경", "등급을 올리", "으로 승급"),
        "재발급": ("재발급", "재교부", "재발행"),
        "폐업": ("폐업",),
    },
}


def extract(query):
    """query -> {attribute: value} for the attributes the query actually states.

    Absent attributes are simply not in the returned dict -- never present with
    a None value, because 'absent' and 'stated as nothing' must not be
    confusable downstream.

    Two rules the surfaces above depend on:

    **The longest matching surface wins.** 비회원사 contains 회원사, so a
    shortest-first or dict-order match would read "저희는 비회원사입니다" as
    회원사 and demote against exactly the wrong documents.

    **Two different values of one attribute means the attribute is not stated.**
    "지금 초급인데 중급 가려면" names a transition, not a grade. Picking one would
    assert something the caller did not say and demote a correct answer on a guess.
    """
    found = {}
    for attribute, values in VOCABULARY.items():
        matches = [(len(surface), value) for value, surfaces in values.items()
                   for surface in surfaces if surface in query]
        if not matches:
            continue
        longest = max(length for length, _ in matches)
        winners = {value for length, value in matches if length == longest}
        if len(winners) == 1:
            found[attribute] = winners.pop()
    return found


def of(doc):
    """doc -> {attribute: value}. An attribute a document does not carry is
    'not applicable', which is a valid state and must not be demoted for."""
    return {k: v for k, v in (doc.get("attributes") or {}).items() if v}


def mismatch(query_attributes, doc):
    """True only when both sides state a value and the values differ."""
    theirs = of(doc)
    return any(attribute in theirs and theirs[attribute] != value
               for attribute, value in query_attributes.items())


def competing_attributes_differ(docs):
    """True when the competing documents disagree among themselves on some
    attribute -- 'the caller did not say which one, and it changes the answer'.

    This is what catches "교육이수카드 발급하려는데요": 회원사 / 비회원사 / 개인회원
    documents come back together, they differ from each other in 대상, and the
    right action is to ask -- with no query-side extraction involved at all.
    """
    tagged = [of(doc) for doc in docs]
    return any(len({t[attribute] for t in tagged if attribute in t}) > 1
               for attribute in ATTRIBUTES)
