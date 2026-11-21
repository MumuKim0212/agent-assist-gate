import pytest

from core import retrieve
from core.decide import CONFIG, decide
from serve import gate_demo


@pytest.mark.parametrize("label,query,expected,shows", gate_demo.EXAMPLES)
def test_each_example_still_does_what_its_label_claims(label, query, expected, shows):
    """The examples are chosen to show a behaviour. If thresholds are refitted and
    one stops showing it, this fails and the example has to be replaced -- it must
    not silently drift into a misleading label."""
    hits = retrieve.retrieve(query)
    assert decide(query, hits, CONFIG).action == expected


def test_every_action_the_gate_has_is_shown_by_some_example():
    assert {e[2] for e in gate_demo.EXAMPLES} == {"answer", "answer_flagged", "clarify", "refuse"}


def test_the_gate_page_says_it_is_a_demo_and_not_an_evaluation():
    text = gate_demo.page()
    assert "데모" in text and "성능 평가가 아닙니다" in text


def test_user_text_is_escaped():
    text = gate_demo.page('<script>alert(1)</script>"')
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_a_result_shows_what_the_gate_saw():
    text = gate_demo.result_html("경력증명서 발급 수수료가 있나요")
    assert "6_answer" in text and "게이트가 본 것" in text


def test_a_question_with_no_hits_still_renders():
    text = gate_demo.result_html("zzzz")
    assert "거절" in text
