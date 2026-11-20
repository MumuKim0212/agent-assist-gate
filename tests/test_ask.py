from core import index
from core.decide import Decision
from serve import ask


def doc(doc_id, question, answer, attributes=None):
    return {"id": doc_id, "question": question, "answer": answer, "kind": "qa",
            "status": "ok", "attributes": attributes or {}, "images": []}


def test_answer_shows_stored_text_only():
    d = doc("a", "사진 규격이 어떻게 되나요?", "3.5×4.5cm 1장")
    text = ask.render("사진", [], Decision("answer", [d], "6_answer"))
    assert "3.5×4.5cm 1장" in text and "행동: 답변" in text


def test_flagged_answers_carry_the_badge():
    d = doc("a", "교재?", "교육비에 포함")
    text = ask.render("q", [], Decision("answer_flagged", [d], "5_needs_review"))
    assert "확인이 끝나지 않았습니다" in text


def test_clarify_lists_what_separates_the_competing_documents():
    a = doc("a", "회원사 발급", "x", {"대상": "회원사"})
    b = doc("b", "비회원사 발급", "y", {"대상": "비회원사"})
    text = ask.render("q", [], Decision("clarify", [a, b], "4_competing_conditions"))
    assert "대상=회원사" in text and "대상=비회원사" in text


def test_refuse_names_the_department_when_the_table_owns_the_topic():
    routing = {"cells": ["E3=1", "F3=회원관리팀", "H3=회비 감면 문의"]}
    text = ask.render("회비 감면 받을 수 있나요", [], Decision("refuse", [], "1_low_score"), routing)
    assert "담당 부서: 회원관리팀" in text


def test_a_gray_zone_refusal_does_not_claim_the_question_is_not_covered():
    text = ask.render("q", [], Decision("refuse", [], "2_gray_unchecked"))
    assert "문서에 없습니다" not in text and "애매" in text


def test_the_routing_document_is_in_the_corpus():
    assert ask.routing_doc() is not None
    assert any(d["id"] == "manual:부서이관건" for d in index.load_docs())
