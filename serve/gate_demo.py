"""The gate demo, at `/answer`: click a prepared question, see what the gate does with it.

This is the page that shows the four actions (`answer`, `answer_flagged`, `clarify`,
`refuse`). It is NOT the tool's main screen: the main screen is the ungated ranked
list in `serve/render.py`. In the real tool the gate is a separate route as well,
because its cut points have not been certified (see CASE-STUDY.md, 4.8 and 6).

Nothing is generated: every line of document text shown is stored text, and the page
shows what the gate saw (scores, thresholds, the rule that fired) so the decision can
be read, not trusted.

Layout. A question renders the search box and the ranked candidates on the left and
the gate's decision on the right; on a narrow window the right side is a modal over
the list. Clicking a candidate opens that document in the same place. All of it is
one server-rendered page with different query parameters:

    /answer?q=<question>               the list and the gate's decision
    /answer?q=<question>&doc=<id>      the list and one candidate document
    /answer?q=<question>&list=1        the list only (what "close" goes back to)

The example questions were chosen to show each *behaviour* the gate has -- they are
not a sample of how well it works, and the page says so. `tests/test_app.py` checks
that each example still does what its label claims, so an example cannot quietly
drift out of date after the thresholds are refitted.
"""
from core import attributes, index, retrieve
from core.decide import CONFIG, decide
from serve import departments, render
from serve.render import _quote, esc, title_of

# (label, question, the action it is expected to produce, what it shows)
EXAMPLES = [
    ("답변", "경력증명서 발급 수수료가 있나요", "answer",
     "점수가 충분하고 경쟁 문서가 없으면 저장된 답을 그대로 보여 줍니다."),
    ("확인 필요 배지", "교재는 교육비에 포함인가요", "answer_flagged",
     "내용 확인이 끝나지 않은 문서는 배지와 함께 보여 주고, 사실로 단정하지 않게 합니다."),
    ("되묻기", "교육이수카드 발급 수수료 알려주세요", "clarify",
     "비슷한 문서들이 대상·등급·행위에서 갈리면 답하지 않고 민원인에게 되물을 질문을 보여 줍니다."),
    ("거절 + 담당 부서", "회비 감면을 받을 수 있는 조건이 있나요", "refuse",
     "문서에 답이 없으면 담당 부서 표에서 주제가 하나의 팀에만 맞을 때 그 팀을 안내합니다."),
    ("거절: 이웃 문서만 있음", "연회비가 얼마인가요", "refuse",
     "회비 납부 방법 문서는 있지만 금액은 없습니다. 이웃 문서를 답으로 내지 않는 것이 핵심입니다."),
    ("거절: 영역 밖", "삼성전자 주가 알려주세요", "refuse",
     "업무와 무관한 질문에는 답하지 않습니다."),
    ("점수가 애매해서 거절", "교육비 환불 규정이 어떻게 되나요", "refuse",
     "맞는 문서가 1위인데도 점수가 회색지대에 있어 거절합니다. 근거 검사가 없는 이 데모의 한계이며, 답이 "
     "있는데 거절하는 것은 허용 가능한 오류(상담원이 직접 찾으면 됨)로 취급합니다."),
    ("답이 있는데 거절", "교육 접수를 취소하고 싶어요", "refuse",
     "답이 있는 질문을 거절한 예입니다. 거절은 안전한 쪽의 오류이지만 상담원에게는 불편합니다."),
]

LABEL = {"answer": "답변", "answer_flagged": "답변 · 확인 필요", "clarify": "되묻기", "refuse": "거절"}
COLOR = {"answer": "#1a7f37", "answer_flagged": "#9a6700", "clarify": "#0969da", "refuse": "#cf222e"}


def _routing_doc():
    for doc in index.load_docs():
        if doc["id"] == departments.ROUTING_ID:
            return doc
    return None


def _docs_by_id():
    return {d["id"]: d for d in index.load_docs()}


# -- the gate's decision ---------------------------------------------------------------

def decision_view(query):
    """(hits, decision, badge, body): everything the decision pane shows."""
    hits = retrieve.retrieve(query)
    decision = decide(query, hits, CONFIG)
    badge = (f"<span class='action' style='background:{COLOR[decision.action]}'>"
             f"{esc(LABEL[decision.action])}</span>")
    out = []
    if decision.action in ("answer", "answer_flagged"):
        top = decision.docs[0]
        if top.get("question"):
            out.append(f"<p><b>Q.</b> {esc(top['question'])}</p>")
        out.append("".join(render.document_content(top)[1]))
        if decision.action == "answer_flagged":
            out.append("<p class='why'>※ 이 문서는 내용 확인이 끝나지 않았습니다. "
                       "사실로 단정해 전달하지 마세요.</p>")
        others = [d["id"] for d in decision.docs[1:]]
        if others:
            out.append(f"<p class='why'>함께 볼 문서: {esc(', '.join(others))}</p>")
    elif decision.action == "clarify":
        out.append("<p>어느 쪽인지 민원인에게 먼저 물어보세요.</p><ul>")
        for doc in decision.docs:
            tags = ", ".join(f"{k}={v}" for k, v in attributes.of(doc).items()) or "-"
            out.append(f"<li>{esc(doc.get('question') or doc['id'])} "
                       f"<span class='why'>[{esc(tags)}]</span></li>")
        out.append("</ul>")
    else:
        routing = _routing_doc()
        team = departments.lookup(query, routing) if routing else None
        if team:
            out.append(f"<p><b>담당 부서: {esc(team)}</b></p>")
        elif decision.reason.startswith("2_gray"):
            out.append("<p>검색 점수가 애매해서 자동으로 답하지 않습니다. 직접 찾아보세요.</p>")
        else:
            out.append("<p>이 질문은 문서에 없습니다. 담당 부서를 특정하지 못했습니다.</p>")
        if hits:
            out.append(f"<p class='why'>가장 비슷한 문서: {esc(hits[0].doc_id)} "
                       "(답이 아니라 이웃 문서일 수 있습니다)</p>")
    return hits, decision, badge, "".join(out)


def seen_html(hits, decision):
    """What the gate saw: the rule, the two scores it reads, the thresholds, the hits."""
    gate = CONFIG["thresholds"]
    rows = "".join(f"<tr><td>{n}</td><td>{esc(h.doc_id)}</td><td>{h.score:.2f}</td></tr>"
                   for n, h in enumerate(hits, 1))
    top1 = hits[0].score if hits else 0.0
    margin_text = f"{hits[0].score - hits[1].score:.2f}" if len(hits) > 1 else "-"
    return (
        "<details><summary>게이트가 본 것</summary>"
        f"<p class='why'>발동한 규칙: <code>{esc(decision.reason)}</code><br>"
        f"1위 점수 {top1:.2f} · 1위와 2위의 차이 {margin_text}<br>"
        f"기준: 거절 &lt; {gate['top1_low']} ≤ 회색지대 &lt; {gate['top1_high']} ≤ 확신 "
        f"(경쟁 판정 폭 {gate['margin']})<br>"
        "점수는 BM25 단위이고, 기준은 이 가상 코퍼스의 tune 문항에서 맞춘 값입니다.</p>"
        f"<table><tr><th>#</th><th>문서</th><th>점수</th></tr>{rows}</table></details>")


def result_html(query):
    """The decision as one block: question, action, what is shown, what the gate saw."""
    hits, decision, badge, body = decision_view(query)
    return (f"<div class='card'><p><b>질문</b> {esc(query)}</p>{badge}{body}"
            f"{seen_html(hits, decision)}</div>")


# -- the page ----------------------------------------------------------------------------

def home():
    chips = "".join(
        f"<a class='chip' href='/answer?q={_quote(q)}'><b>{esc(label)}</b><br>{esc(q)}"
        f"<small>{esc(shows)}</small></a>"
        for label, q, _, shows in EXAMPLES)
    return ("<h1 class='hero'>게이트 데모</h1>"
            "<p class='sub'>예시 질문을 눌러 보거나 직접 입력해 보세요. 게이트가 답변·되묻기·거절 중 "
            "무엇을 제시하는지 보여 줍니다.</p>"
            "<div class='demo-note'><b>이 화면은 데모입니다.</b> 상담원이 실제로 쓰는 화면은 게이트 없는 "
            "<a href='/'>순위 목록</a>이고, 게이트는 인증 기준을 통과하지 못해 적용하지 않았습니다"
            "(CASE-STUDY.md 4.8). 아래 예시는 시스템이 하는 <b>행동의 종류</b>를 보이려고 고른 것이며 "
            "성능 평가가 아닙니다. 가상 문서로 돌아가며, 직접 입력한 질문에는 거절이 많이 나옵니다.</div>"
            f"<div class='chips'>{chips}</div>"
            f"{render.search_form(action='/answer', focus=True)}")


def candidates(query, hits, opened_id):
    current = " aria-current='true'"
    rows = "".join(
        f"<li><a href='/answer?q={_quote(query)}&amp;doc={_quote(h.doc_id)}'"
        f"{current if h.doc_id == opened_id else ''}>"
        f"<span class='rankbox'>{n}</span><div><div class='title'>{esc(title_of(h.doc))}</div>"
        f"{render.badge(h.doc)}"
        f"<div class='snippet'>{esc(render.snippet(h.doc, query))}</div>"
        f"<div class='meta'>{esc(h.doc_id)} · {h.doc['kind']} · {h.score:.2f}</div></div></a></li>"
        for n, h in enumerate(hits, 1))
    if not hits:
        return "<p class='why'>후보 문서가 없습니다.</p>"
    return (f"<div class='reshead'><h2>후보 문서</h2><span class='count'>{len(hits)} DOCUMENTS</span></div>"
            f"<ol class='hits'>{rows}</ol>"
            "<p class='note'>후보는 답이 아닙니다 · 게이트의 판단을 확인하세요</p>")


def pane(title_html, body_html, foot_html, close_url):
    close = esc(close_url)
    return (f"<a class='backdrop' href='{close}' tabindex='-1' aria-hidden='true'></a>"
            "<section class='detail' tabindex='-1' autofocus aria-label='문서'>"
            "<header class='dochead'>"
            f"<div class='closebar'><a accesskey='b' href='{close}'>✕ 닫기</a></div>"
            f"<div class='doctitle'>{title_html}</div></header>"
            f"<div class='docbody'>{body_html}</div>"
            f"<footer class='docfoot'>{foot_html}</footer></section>")


def page(query="", doc_id=None, list_only=False):
    if not query.strip():
        return render.page("게이트 데모", home(), nav="gate")
    query = query.strip()
    hits, decision, badge, body = decision_view(query)
    docs = _docs_by_id()
    opened = docs.get(doc_id) if doc_id else None
    close_url = f"/answer?q={_quote(query)}&list=1"
    if list_only:
        right, split, focus = "", "split", True
    elif opened is not None:
        served = decision.action in ("answer", "answer_flagged")
        verdict = (f"이 문서는 후보입니다. 게이트의 판단은 <b>{esc(LABEL[decision.action])}</b>입니다."
                   if not served or decision.docs[0]["id"] != opened["id"] else
                   "이 문서가 게이트가 낸 답입니다.")
        head, parts, meta = render.document_content(opened, heading="h2")
        right = pane("".join(head), "".join(parts),
                     f"<p class='why'>{verdict}</p>"
                     f"<p class='why'><a href='/answer?q={_quote(query)}'>← 게이트의 판단 보기</a></p>"
                     f"{meta}",
                     close_url)
        split, focus = "split open", False
    else:
        right = pane(f"<h2>게이트의 판단</h2>{badge}"
                     f"<p class='why'>질문: {esc(query)}</p>", body,
                     seen_html(hits, decision), close_url)
        split, focus = "split open", False
    listing = (f"<div class='list'>{render.search_form(query, action='/answer', focus=focus)}"
               f"{candidates(query, hits, opened['id'] if opened else None)}</div>")
    return render.page(f"{query} — 게이트 데모",
                       f"<div class='{split}'>{listing}{right}</div>", nav="gate")
