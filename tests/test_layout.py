"""The gate demo's two-pane layout and the shared page shell: structure and the rules
it relies on. (The main screen, the ranked list, is in test_main_screen.py.)"""
import re
import urllib.parse

from serve import gate_demo, render

QUERY = "경력증명서 발급 수수료가 있나요"          # the gate answers this one
REFUSED = "회비 감면을 받을 수 있는 조건이 있나요"  # ... and refuses this one


def body_of(page):
    """The document body. The stylesheet is in <head> and talks about these tags."""
    return page.split("</head>", 1)[1]


def first_candidate_id():
    return gate_demo.decision_view(QUERY)[0][0].doc_id


# -- home ---------------------------------------------------------------------------------

def test_home_shows_the_banner_the_examples_and_a_focused_search_box():
    body = body_of(gate_demo.page())
    assert "성능 평가가 아닙니다" in body
    assert body.count("class='chip'") == len(gate_demo.EXAMPLES)
    assert "autofocus" in body and "class='detail'" not in body


def test_every_example_chip_links_to_the_gate_page_for_that_question():
    body = body_of(gate_demo.page())
    for _, question, _, _ in gate_demo.EXAMPLES:
        assert f"/answer?q={urllib.parse.quote(question, safe='')}" in body


def test_the_sidebar_has_the_three_screens_and_the_recent_documents_list():
    side = body_of(gate_demo.page()).split("<aside", 1)[1]
    for label in ("근거 검색", "담당 부서 안내", "게이트 데모", "최근 확인 문서"):
        assert label in side
    assert "aria-current='page'" in side.split("게이트 데모", 1)[0].rsplit("<a", 1)[1]


# -- a question: list on the left, the gate's decision on the right --------------------------

def test_a_question_renders_the_list_and_the_decision_pane():
    body = body_of(gate_demo.page(QUERY))
    assert "split open" in body and "class='detail'" in body
    assert "게이트의 판단" in body and "6_answer" in body
    assert body.count("class='rankbox'") == 5                 # the five candidates


def test_the_pane_has_a_header_a_body_and_a_footer_in_order():
    body = body_of(gate_demo.page(QUERY))
    assert body.index("class='dochead'") < body.index("class='docbody'") < body.index("class='docfoot'")


def test_the_decision_badge_is_in_the_header_and_what_the_gate_saw_is_in_the_footer():
    body = body_of(gate_demo.page(QUERY))
    head = body.split("class='dochead'", 1)[1].split("class='docbody'", 1)[0]
    foot = body.split("class='docfoot'", 1)[1]
    assert gate_demo.LABEL["answer"] in head
    assert "게이트가 본 것" in foot and "6_answer" in foot


def test_a_refusal_names_the_department_in_the_pane_body():
    body = body_of(gate_demo.page(REFUSED))
    pane_body = body.split("class='docbody'", 1)[1].split("class='docfoot'", 1)[0]
    assert "담당 부서: 회원관리팀" in pane_body


def test_the_list_notes_that_candidates_are_not_the_answer():
    assert "후보는 답이 아닙니다" in body_of(gate_demo.page(REFUSED))


# -- a candidate opens in the same place -------------------------------------------------------------

def test_a_candidate_links_to_the_same_page_with_that_document_open():
    body = body_of(gate_demo.page(REFUSED))
    href = re.search(r"<a href='(/answer\?q=[^']+&amp;doc=[^']+)'", body).group(1)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(href.replace("&amp;", "&")).query)
    assert query["q"] == [REFUSED] and query["doc"]


def test_opening_a_candidate_shows_its_text_and_says_it_is_not_the_answer_when_refused():
    doc_id = gate_demo.decision_view(REFUSED)[0][0].doc_id
    body = body_of(gate_demo.page(REFUSED, doc_id=doc_id))
    assert "이 문서는 후보입니다" in body and "게이트의 판단은" in body
    assert "aria-current='true'" in body and body.count("aria-current='true'") == 1
    assert "← 게이트의 판단 보기" in body


def test_the_document_the_gate_served_is_labelled_as_the_answer():
    body = body_of(gate_demo.page(QUERY, doc_id=first_candidate_id()))
    assert "이 문서가 게이트가 낸 답입니다" in body


def test_an_unknown_document_id_falls_back_to_the_decision():
    body = body_of(gate_demo.page(QUERY, doc_id="faq:no-such-doc"))
    assert "게이트의 판단" in body


def test_list_only_is_what_close_goes_back_to():
    body = body_of(gate_demo.page(QUERY))
    close = re.search(r"<a accesskey='b' href='([^']+)'", body).group(1)
    assert close.endswith("&amp;list=1") and "doc=" not in close
    closed = body_of(gate_demo.page(QUERY, list_only=True))
    assert "class='detail'" not in closed and "split open" not in closed and "autofocus" in closed


# -- keyboard, markup and escaping ----------------------------------------------------------------------

def test_focus_goes_to_the_pane_not_the_search_box_while_it_is_open():
    body = body_of(gate_demo.page(QUERY))
    assert body.count("autofocus") == 1
    assert re.search(r"<section class='detail' tabindex='-1' autofocus", body)


def test_document_order_is_list_then_pane_then_sidebar():
    body = body_of(gate_demo.page(QUERY))
    assert body.index("<main>") < body.index("class='list'") < body.index("class='detail'") \
        < body.index("<aside")


def test_the_backdrop_is_a_link_that_is_not_a_tab_stop():
    body = body_of(gate_demo.page(QUERY))
    assert re.search(r"<a class='backdrop' href='[^']+' tabindex='-1'", body)


def test_no_script_anywhere():
    pages = (gate_demo.page(), gate_demo.page(QUERY),
             gate_demo.page(QUERY, doc_id=first_candidate_id()))
    for html_ in pages:
        assert "<script" not in html_.lower()


def test_the_query_and_the_document_id_are_escaped():
    evil = "<img src=x onerror=alert(1)>"
    for page in (gate_demo.page(evil), gate_demo.page(QUERY, doc_id=evil)):
        assert "<img src=x" not in page


# -- the two layouts -----------------------------------------------------------------------------------------

def test_wide_and_narrow_meet_at_one_width_with_no_gap_or_overlap():
    wide = re.search(r"@media \(min-width: (\d+)px\)", render.STYLE)
    narrow = re.search(r"@media \(max-width: (\d+)px\) \{\s*\.backdrop", render.STYLE)
    assert wide and narrow and int(narrow.group(1)) + 1 == int(wide.group(1))


def test_the_pane_has_a_border_and_the_wide_pane_fits_the_window():
    frame = re.search(r"\.detail \{([^}]*)\}", render.STYLE).group(1)
    assert "border: 2px solid" in frame
    wide = render.STYLE.split("@media (min-width: 1100px)", 1)[1].split("@media", 1)[0]
    assert "max-height: calc(100vh - 6.5rem)" in wide


def test_the_modal_is_pure_css_and_as_tall_as_its_content():
    narrow = render.STYLE.split("@media (max-width: 1099px)", 1)[1]
    assert "position: fixed" in narrow and "max-height: 90vh" in narrow and ".backdrop" in narrow


def test_a_table_document_is_drawn_as_its_cells():
    """The routing table keeps its content in `cells`; a flat list of values would
    hide which team owns which topic."""
    body = body_of(gate_demo.page(REFUSED, doc_id="manual:부서이관건"))
    assert "<table class='cells'>" in body
    assert "<td class='ref'>F3</td><td>회원관리팀</td>" in body
