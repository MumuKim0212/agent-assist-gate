"""The main screen: an ungated ranked list, a document, the routing table, and the routes
that serve them. The gate is a separate page (`/answer`, see test_layout.py)."""
import re
import urllib.parse

import pytest

from serve import app, render

FLAGGED_QUERY = "교재는 교육비에 포함인가요"     # a needs_review document is among its hits
FLAGGED_ID = "faq:교육신청:Q14"
QUERY = "경력증명서 발급 수수료가 있나요"


def get(target, cookie=""):
    status, headers, payload = app.dispatch("GET", target, cookie=cookie)
    return status, headers, payload.decode("utf-8")


def search(query, **extra):
    params = {"q": query, **extra}
    return get("/search?" + urllib.parse.urlencode(params))


def body_of(page):
    return page.split("</head>", 1)[1]


# -- the screen has no gate ---------------------------------------------------------------

def test_the_home_screen_is_a_search_box_a_shortcut_line_and_no_gate():
    status, _, page = get("/")
    body = body_of(page)
    assert status == 200
    assert "autofocus" in body and "<kbd>Alt+S</kbd>" in body
    assert "게이트의 판단" not in body and "class='detail'" not in body
    assert "성능 평가가 아닙니다" in body                     # the demo says what it is
    assert "href='/answer'" in body                           # ... and where the gate is


def test_a_search_shows_a_ranked_list_with_no_decision_in_it():
    status, _, page = search(QUERY)
    body = body_of(page)
    assert status == 200 and body.count("class='rankbox'") == 5
    for rule in ("6_answer", "1_low_score", "2_gray_unchecked", "게이트의 판단"):
        assert rule not in body
    assert "순위는 참고용입니다" in body


def test_an_empty_query_is_the_home_screen():
    status, _, page = search("   ")
    assert status == 200 and "무엇을 확인할까요?" in page and "class='rankbox'" not in page


# -- keyboard ----------------------------------------------------------------------------------

def test_each_result_has_the_rank_as_its_accesskey_and_the_line_says_so():
    body = body_of(search(QUERY)[2])
    for rank in range(1, 6):
        assert f"<a accesskey='{rank}' href='/search?q=" in body
    assert "<kbd>Alt+1~5</kbd>" in body and "<kbd>Alt+N</kbd>" in body


def test_the_search_box_has_accesskey_s_and_the_submit_button_is_out_of_the_tab_order():
    body = body_of(search(QUERY)[2])
    assert "accesskey='s'" in body and "<button tabindex='-1'>검색</button>" in body


# -- needs_review: never without its badge --------------------------------------------------------

def test_a_needs_review_document_has_its_badge_in_the_list():
    body = body_of(search(FLAGGED_QUERY)[2])
    assert FLAGGED_ID in body
    assert "<div class='badge'>확인 필요</div>" in body
    assert "원본 자료 간 값이 충돌" in body                  # with the reason


def test_it_has_the_badge_in_the_pane_and_on_the_document_page():
    pane = body_of(search(FLAGGED_QUERY, doc=FLAGGED_ID)[2])
    assert pane.split("class='detail'", 1)[1].count("<div class='badge'>확인 필요</div>") == 1
    page = body_of(get("/doc?id=" + urllib.parse.quote(FLAGGED_ID, safe=""))[2])
    assert "<div class='badge'>확인 필요</div>" in page


def test_a_document_without_the_flag_has_no_badge():
    doc = app.documents()["faq:카드발급:Q10"]
    assert render.badge(doc) == ""


# -- a result opens beside the list --------------------------------------------------------------

def test_a_result_opens_its_document_beside_the_list_and_marks_the_opened_one():
    body = body_of(search(QUERY, doc=FLAGGED_ID, rank="2")[2])
    assert "split open" in body and "class='detail'" in body
    assert body.count("aria-current='true'") <= 1
    assert re.search(r"<a accesskey='b' href='/search\?q=[^']+'>✕ 닫기</a>", body)


def test_an_unknown_document_opens_nothing():
    body = body_of(search(QUERY, doc="faq:no-such-doc")[2])
    assert "class='detail'" not in body and "split open" not in body


def test_the_document_page_links_back_to_the_search():
    page = get("/doc?id=" + urllib.parse.quote(FLAGGED_ID, safe="") +
               "&q=" + urllib.parse.quote(QUERY, safe=""))[2]
    assert "← 검색 결과로" in page and "/search?q=" in page
    assert get("/doc?id=" + urllib.parse.quote(FLAGGED_ID, safe=""))[2].count("href='/'") >= 1


def test_an_unknown_document_page_is_a_404():
    assert get("/doc?id=faq:no-such-doc")[0] == 404


# -- the snippet is a window around the query ------------------------------------------------------

def test_the_snippet_is_a_window_around_the_first_query_word_found():
    doc = {"answer": "가" * 300 + " 열쇠 " + "나" * 300, "cells": None}
    window = render.snippet(doc, "열쇠 분실", limit=180)
    assert "열쇠" in window and window.startswith("…") and window.endswith("…")
    assert len(window) <= 182


def test_without_a_matching_word_the_snippet_is_the_start_of_the_document():
    doc = {"answer": "처음 문장입니다. " * 40, "cells": None}
    assert render.snippet(doc, "없는낱말", limit=30).startswith("처음 문장입니다.")


def test_a_document_with_no_text_says_so():
    assert "내용 없음" in render.snippet({"answer": "", "cells": None}, "q")


# -- "여기 없음" ------------------------------------------------------------------------------------------

def test_the_none_button_is_a_post_form_that_carries_the_query():
    body = body_of(search(QUERY)[2])
    form = re.search(r"<form class='none' action='/not_here' method='post'>(.*?)</form>", body, re.S)
    assert form and "name='q'" in form.group(1) and "accesskey='n'" in form.group(1)


def test_pressing_it_redirects_with_303_and_records_nothing():
    status, headers, payload = app.dispatch(
        "POST", "/not_here", ("q=" + urllib.parse.quote(QUERY, safe="")).encode())
    location = dict(headers)["Location"]
    assert status == 303 and payload == b""
    params = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert params["q"] == [QUERY] and params["none"] == ["1"]
    assert not any(name.lower() == "set-cookie" for name, _ in headers)
    page = body_of(search(QUERY, none="1")[2])
    assert "기록하지 않습니다" in page and "action='/not_here'" not in page


def test_only_not_here_accepts_a_post():
    assert app.dispatch("POST", "/search", b"q=x")[0] == 404


# -- recent documents ------------------------------------------------------------------------------------------

def cookie_of(headers):
    value = dict(headers)["Set-Cookie"]
    return value.split(";", 1)[0]


def test_opening_a_document_remembers_its_id_and_nothing_else():
    _, headers, _ = search(QUERY, doc=FLAGGED_ID)
    cookie = cookie_of(headers)
    assert cookie.startswith("recent=") and urllib.parse.quote(QUERY, safe="") not in cookie
    attrs = dict(headers)["Set-Cookie"]
    assert "HttpOnly" in attrs and "SameSite=Lax" in attrs and "Path=/" in attrs


def test_the_sidebar_lists_what_was_opened_newest_first():
    _, h1, _ = get("/doc?id=" + urllib.parse.quote(FLAGGED_ID, safe=""))
    _, h2, _ = get("/doc?id=faq%3A%EC%B9%B4%EB%93%9C%EB%B0%9C%EA%B8%89%3AQ10", cookie=cookie_of(h1))
    status, _, page = get("/", cookie=cookie_of(h2))
    side = page.split("<aside", 1)[1]
    first = side.index("faq%3A%EC%B9%B4%EB%93%9C%EB%B0%9C%EA%B8%89%3AQ10")
    second = side.index(urllib.parse.quote(FLAGGED_ID, safe=""))
    assert status == 200 and first < second
    assert "아직 열어 본 문서가 없습니다" not in side


def test_a_tampered_cookie_cannot_put_text_on_the_screen():
    evil = "recent=" + urllib.parse.quote("<script>alert(1)</script>", safe="") + "|faq%3Ano-such"
    page = get("/", cookie=evil)[2]
    assert "<script>alert(1)" not in page and "아직 열어 본 문서가 없습니다" in page
    assert app.read_recent("recent=%%%garbage;;;") == []


def test_the_cookie_is_trimmed_from_the_old_end_and_never_exceeds_its_limit():
    ids = [f"faq:카드발급:Q{n}" for n in range(1, 40)]
    value = app.recent_cookie_value(ids)
    assert len(value) <= app.RECENT_COOKIE_MAX_CHARS
    assert urllib.parse.unquote(value.split("|")[0]) == ids[0]
    assert len(value.split("|")) <= app.RECENT_MAX


# -- the routing table page ---------------------------------------------------------------------------------------

def test_the_departments_page_lists_every_team_and_links_to_its_source():
    status, _, page = get("/departments")
    assert status == 200 and "회원관리팀" in page and "<table class='dept'>" in page
    assert "/doc?id=manual%3A%EB%B6%80%EC%84%9C" in page


def test_the_departments_filter_narrows_the_table():
    everything = get("/departments")[2].count("<td class='team'>")
    narrowed = get("/departments?q=" + urllib.parse.quote("회비", safe=""))[2].count("<td class='team'>")
    assert 0 < narrowed < everything


def test_a_filter_that_matches_nothing_says_so():
    page = get("/departments?q=" + urllib.parse.quote("없는낱말xyz", safe=""))[2]
    assert "일치하는 팀이 없습니다" in page


# -- routes and markup -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("target", ["/", "/search?q=" + urllib.parse.quote(QUERY, safe=""),
                                    "/departments", "/answer", "/answer?q=" + urllib.parse.quote(QUERY, safe="")])
def test_the_screens_render_without_a_script(target):
    status, headers, page = get(target)
    assert status == 200 and "<script" not in page.lower()
    assert dict(headers)["Content-Type"] == "text/html; charset=utf-8"


def test_the_gate_is_on_its_own_route():
    page = get("/answer?q=" + urllib.parse.quote(QUERY, safe=""))[2]
    assert "게이트의 판단" in page and "6_answer" in page


def test_an_unknown_route_is_a_404():
    assert get("/no-such-page")[0] == 404 and get("/image?path=x")[0] == 404


def test_the_query_is_escaped_everywhere_it_is_echoed():
    evil = "<img src=x onerror=alert(1)>"
    for target in ("/search?q=" + urllib.parse.quote(evil, safe=""),
                   "/departments?q=" + urllib.parse.quote(evil, safe=""),
                   "/search?q=" + urllib.parse.quote(evil, safe="") + "&none=1"):
        assert "<img src=x" not in get(target)[2]


def test_a_very_long_query_is_cut_not_rejected():
    assert search("가" * 5000)[0] == 200
