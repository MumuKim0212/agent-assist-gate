"""Each precedence rule, against hit lists constructed by hand.

Constructed on purpose: under BM25 the thresholds are in score units and a live
query rarely lands in a given band, so a rule is verified by building the hits
that should trigger it, never by hoping a search does.
"""
import copy

import pytest

from core.decide import Hit, decide

CFG = {
    "retrieval": {"rerank": False},
    "thresholds": {"top1_high": 10.0, "top1_low": 5.0, "margin": 1.0},
    "attributes": {"document_tags": True, "query_extraction": False},
    "gray_zone": {"evidence_check": False},
}


def doc(doc_id, attributes=None, answer="본문", status="ok", images=None):
    return {"id": doc_id, "question": f"Q {doc_id}", "answer": answer, "kind": "qa",
            "status": status, "attributes": attributes or {}, "images": images or []}


def hit(d, score):
    return Hit(d["id"], score, d)


def test_no_hits_refuses():
    assert decide("q", [], CFG).reason == "0_no_hits"


def test_below_low_refuses():
    d = doc("a")
    assert decide("q", [hit(d, 4.9)], CFG).reason == "1_low_score"


def test_gray_zone_refuses_while_unchecked():
    d = doc("a")
    decision = decide("q", [hit(d, 7.0)], CFG)
    assert (decision.action, decision.reason) == ("refuse", "2_gray_unchecked")


def test_gray_zone_with_check_enabled_needs_a_checker():
    cfg = copy.deepcopy(CFG)
    cfg["gray_zone"]["evidence_check"] = True
    with pytest.raises(RuntimeError):
        decide("q", [hit(doc("a"), 7.0)], cfg)


def test_gray_zone_check_decides():
    cfg = copy.deepcopy(CFG)
    cfg["gray_zone"]["evidence_check"] = True
    h = [hit(doc("a"), 7.0)]
    assert decide("q", h, cfg, lambda q, d: False).reason == "2_evidence_check_failed"
    assert decide("q", h, cfg, lambda q, d: True).reason == "2_evidence_checked+6_answer"


def test_competing_documents_that_differ_clarify():
    a = doc("a", {"대상": "회원사"})
    b = doc("b", {"대상": "비회원사"})
    decision = decide("q", [hit(a, 12.0), hit(b, 11.5)], CFG)
    assert (decision.action, decision.reason) == ("clarify", "4_competing_conditions")
    assert {d["id"] for d in decision.docs} == {"a", "b"}


def test_competing_documents_that_agree_do_not_clarify():
    a = doc("a", {"대상": "회원사"})
    b = doc("b", {"대상": "회원사"})
    assert decide("q", [hit(a, 12.0), hit(b, 11.5)], CFG).action == "answer"


def test_a_clear_winner_answers_even_if_the_runner_up_differs():
    a = doc("a", {"대상": "회원사"})
    b = doc("b", {"대상": "비회원사"})
    decision = decide("q", [hit(a, 15.0), hit(b, 11.0)], CFG)
    assert (decision.action, decision.reason) == ("answer", "6_answer")


def test_needs_review_is_served_with_a_badge():
    decision = decide("q", [hit(doc("a", status="needs_review"), 15.0)], CFG)
    assert (decision.action, decision.reason) == ("answer_flagged", "5_needs_review")


def test_a_document_with_nothing_to_serve_is_not_an_answer():
    decision = decide("q", [hit(doc("a", answer="   "), 15.0)], CFG)
    assert (decision.action, decision.reason) == ("refuse", "5_nothing_to_serve")


def test_hits_are_sorted_unless_a_rerank_ordered_them():
    low, high = doc("low"), doc("high")
    unsorted = [hit(low, 6.0), hit(high, 16.0)]
    assert decide("q", unsorted, CFG).docs[0]["id"] == "high"
    cfg = copy.deepcopy(CFG)
    cfg["retrieval"]["rerank"] = True
    # the rerank put `low` first; the gate must read top1 off it as given
    assert decide("q", unsorted, cfg).reason == "2_gray_unchecked"
