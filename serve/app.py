"""A one-page demo: click a prepared question, see what the gate does with it.

    python -m serve.app                 # http://127.0.0.1:8000
    python -m serve.app --port 8080

Standard library only, and no JavaScript. Nothing is generated: every line of
document text shown is stored text, and the page shows what the gate saw (scores,
thresholds, the rule that fired) so the decision can be read, not trusted.

Layout. A question renders the search box and the ranked candidates on the left and
the gate's decision on the right; on a narrow window the right side is a modal over
the list. Clicking a candidate opens that document in the same place. All of it is
one server-rendered page with different query parameters, so there is nothing to
script:

    /?q=<question>               the list and the gate's decision
    /?q=<question>&doc=<id>      the list and one candidate document
    /?q=<question>&list=1        the list only (what "close" goes back to)

The example questions were chosen to show each *behaviour* the gate has -- they
are not a sample of how well it works, and the page says so. `tests/test_app.py`
checks that each example still does what its label claims, so an example cannot
quietly drift out of date after the thresholds are refitted.
"""
import argparse
import html
import http.server
import urllib.parse

from core import attributes, index, retrieve
from core.decide import CONFIG, decide
from serve import departments

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

CSS = """
:root { color-scheme: light; --ink: #17212b; --accent: #1d4e5a }
* { box-sizing: border-box }
body { margin: 0; background: #eef1f4; color: var(--ink);
       font: 15px/1.6 "Malgun Gothic", "Segoe UI", system-ui, sans-serif }
a { color: inherit }

/* The main column comes BEFORE the sidebar in the HTML and the grid moves the
   sidebar left, so Tab from the search box reaches the candidates, not a menu. */
header.top { height: 52px; background: #142535; color: #e6eef3; display: flex;
             align-items: center; gap: .8rem; padding: 0 1.5rem; font-size: .85rem }
.brandmark { display: grid; place-items: center; width: 26px; height: 26px;
             border: 1px solid #89a5ae; border-radius: 7px; color: #b9d4d7; font-size: .8rem }
.brand { font-weight: 700 }
header.top .sep { height: 18px; border-left: 1px solid #ffffff30 }
header.top .ws { color: #abc0ca; font-size: .78rem }
.layout { display: grid; grid-template-columns: 220px minmax(0, 1fr);
          grid-template-areas: "side main"; max-width: 1500px; margin: 0 auto;
          background: #f4f6f8; min-height: calc(100vh - 52px) }
main { grid-area: main; padding: 1.8rem 2.2rem 4rem; min-width: 0 }
aside { grid-area: side; background: #e9eef1; border-right: 1px solid #dce3e7;
        padding: 1.4rem .9rem }
aside a.nav { display: block; padding: .5rem .7rem; border-radius: 8px; color: #5e6d79;
              font-size: .85rem; text-decoration: none }
aside a.nav:hover { background: #dfe8eb }
aside a.nav.sel { background: #d6e5e7; color: #1d525d; font-weight: 700 }
aside a.ex { display: block; padding: .3rem .7rem; font-size: .78rem; color: #4c5b66;
             text-decoration: none }
aside a.ex:hover { text-decoration: underline }
.aside-label { font: 10px Consolas, monospace; letter-spacing: .12em; color: #85929d;
               margin: 1.4rem .7rem .4rem }
.guide { margin: 1.4rem .3rem 0; background: #f3f6f7; border: 1px solid #dce4e7;
         border-radius: 10px; padding: .7rem; font-size: .72rem; line-height: 1.6;
         color: #71808b }
.guide b { display: block; font-size: .78rem; color: #344858 }
@media (max-width: 850px) {
  .layout { grid-template-columns: 1fr; grid-template-areas: "main" "side" }
  main { padding: 1.2rem 1rem 2rem }
  aside { border-right: 0; border-top: 1px solid #dce3e7 }
}

h1.hero { font-size: 1.5rem; letter-spacing: -.03em; margin: 0 0 .3rem }
p.sub { color: #83909a; font-size: .85rem; margin: 0 0 1rem }
.demo-note { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 8px;
             padding: .6rem .9rem; font-size: .88rem; margin: 0 0 1.2rem }
.chips { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
         gap: .6rem; margin: 0 0 1.4rem }
.chip { display: block; border: 1px solid #d0d7de; border-radius: 9px;
        padding: .6rem .8rem; text-decoration: none; background: #fff; font-size: .9rem }
.chip:hover { border-color: #0969da; background: #ddf4ff }
.chip b { color: #203646 }
.chip small { display: block; color: #59636e; margin-top: .2rem; font-size: .76rem;
              line-height: 1.45 }
form.search { display: flex; align-items: center; gap: .6rem; background: #fff;
              border: 1px solid #cbd6dc; border-radius: 9px;
              padding: .3rem .4rem .3rem 1rem; margin-bottom: 1.2rem;
              box-shadow: 0 2px 8px #2c48540a }
form.search::before { content: "⌕"; color: #728894; font-size: 1.2rem }
form.search:focus-within { border-color: #7fa9b1; box-shadow: 0 0 0 3px #d4e5e7 }
form.search input { flex: 1; border: 0; outline: 0; background: transparent;
                    padding: .5rem 0; font-size: 1.05rem; color: var(--ink); min-width: 0 }
form.search button { padding: .55rem 1.1rem; border: 0; border-radius: 7px;
                     background: var(--accent); color: #fff; font-size: .85rem;
                     font-weight: 600; cursor: pointer }
.reshead { display: flex; justify-content: space-between; align-items: baseline;
           margin: 0 0 .5rem }
.reshead h2 { font-size: .9rem; margin: 0 }
.count { font: .7rem Consolas, monospace; color: #88959e }
ol.hits { list-style: none; margin: 0; padding: 0 }
ol.hits li { margin: .5rem 0 }
ol.hits a { display: grid; grid-template-columns: 2.2rem minmax(0, 1fr); gap: .9rem;
            background: #fff; border: 1px solid #e1e6e9; border-radius: 9px;
            padding: .8rem 1rem; text-decoration: none }
ol.hits a:hover, ol.hits a:focus-visible { border-color: #93b7bd;
            box-shadow: 0 0 0 2px #d4e5e7; outline: 0 }
ol.hits a[aria-current] { border-color: var(--accent); box-shadow: 0 0 0 2px #cfe3e6 }
.rankbox { display: grid; place-items: center; background: #edf2f3; border-radius: 7px;
           height: 2rem; color: #536b75; font: .8rem Consolas, monospace }
.title { font-size: 1rem; font-weight: 600; color: #203646 }
.snippet { color: #697984; margin-top: .15rem; font-size: .88rem }
.meta { font: .75rem Consolas, monospace; color: #9aa5ab; margin-top: .3rem }
.note { margin-top: 1rem; font-size: .78rem; color: #8c98a2 }
.badge { display: inline-block; color: #fff; border-radius: 999px; padding: .1rem .75rem;
         font-size: .88rem; font-weight: 600 }

/* The right side. Wide: a sticky pane next to the list. Narrow: a modal over it,
   closed by a link (the backdrop is one too). CSS only. */
main > * { max-width: 56rem }
main > .split { max-width: none }
.split > .list { max-width: 56rem }
.backdrop { display: none }
.closebar { margin: 0; order: 2; flex: none }
.closebar a { display: inline-block; padding: .3rem .7rem; border: 1px solid #cbd6dc;
              border-radius: 7px; background: #f4f6f8; text-decoration: none;
              font-size: .85rem; color: #536b75 }
.detail { background: #fff; border: 2px solid #9db2bb; border-radius: 12px;
          box-shadow: 0 6px 22px #1d2d3a1f; padding: 0 }
.detail:focus { outline: 0 }
.dochead { position: sticky; top: 0; z-index: 1; display: flex; align-items: flex-start;
           justify-content: space-between; gap: 1rem; padding: 1rem 1.3rem;
           background: #e6eff2; border-bottom: 2px solid #9db2bb;
           border-radius: 10px 10px 0 0 }
.doctitle { order: 1; flex: 1; min-width: 0; border-left: 5px solid var(--accent);
            padding-left: .9rem }
.detail h2 { font-size: 1.15rem; line-height: 1.45; letter-spacing: -.02em; margin: 0 0 .3rem;
             color: #10303b }
.docbody { padding: 1.3rem 1.5rem 1.5rem; font-size: 1rem; line-height: 1.85 }
.docbody p { margin: 0 0 .8rem }
.body { white-space: pre-wrap; margin: .4rem 0 }
.docfoot { padding: .8rem 1.5rem 1.1rem; background: #f6f8f9; border-top: 1px solid #dfe5e8;
           border-radius: 0 0 10px 10px; font-size: .85rem; line-height: 1.5 }
.why { color: #59636e; font-size: .88rem }
table { border-collapse: collapse; font-size: .85rem; margin-top: .4rem }
td, th { border: 1px solid #d0d7de; padding: .2rem .6rem; text-align: left }
table.cells td.ref { color: #8c98a2; font: .75rem Consolas, monospace; white-space: nowrap }
details { margin: 0 }
summary { cursor: pointer; font-size: .85rem; color: #0969da }
@media (min-width: 1100px) {
  .split.open { display: grid; grid-template-columns: minmax(300px, 2fr) minmax(0, 3fr);
                gap: 1.4rem; align-items: start }
  .split.open > .list { max-width: none; min-width: 0 }
  /* starts level with the search box and ends inside the window, so focusing it
     does not scroll the page and hide the top bar */
  .detail { position: sticky; top: 1rem; max-height: calc(100vh - 6.5rem); overflow: auto }
}
@media (max-width: 1099px) {
  .backdrop { display: block; position: fixed; inset: 0; background: #0f1b2666; z-index: 19 }
  .detail { position: fixed; z-index: 20; top: 5vh; max-height: 90vh; left: 50%;
            transform: translateX(-50%); width: min(56rem, 92vw); overflow: auto;
            box-shadow: 0 20px 60px #0f1b2655 }
}
"""


def esc(text):
    return html.escape(str(text), quote=True)


def _q(value):
    return urllib.parse.quote(value, safe="")


def _routing_doc():
    for doc in index.load_docs():
        if doc["id"] == departments.ROUTING_ID:
            return doc
    return None


def _docs_by_id():
    return {d["id"]: d for d in index.load_docs()}


def title_of(doc):
    return doc["question"].strip() or doc["sheet"]


def doc_body_html(doc):
    """A table record keeps its content in `cells` ("F3=교육운영팀"), so it is drawn as
    the table it is; everything else is its stored text."""
    if doc.get("cells"):
        rows = "".join(f"<tr><td class='ref'>{esc(ref)}</td><td>{esc(value)}</td></tr>"
                       for ref, _, value in (c.partition("=") for c in doc["cells"]))
        chrome = f"<p class='why'>{esc(doc['answer'])}</p>" if doc["answer"].strip() else ""
        return f"{chrome}<table class='cells'>{rows}</table>"
    return f"<div class='body'>{esc(index.body(doc))}</div>"


def snippet(doc, limit=90):
    text = " ".join(index.body(doc).split())
    return text[:limit] + ("…" if len(text) > limit else "")


# -- the gate's decision ---------------------------------------------------------------

def decision_view(query):
    """(hits, decision, badge, body, seen): everything the decision pane shows."""
    hits = retrieve.retrieve(query)
    decision = decide(query, hits, CONFIG)
    badge = (f"<span class='badge' style='background:{COLOR[decision.action]}'>"
             f"{esc(LABEL[decision.action])}</span>")
    out = []
    if decision.action in ("answer", "answer_flagged"):
        top = decision.docs[0]
        if top.get("question"):
            out.append(f"<p><b>Q.</b> {esc(top['question'])}</p>")
        out.append(doc_body_html(top))
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

def sidebar():
    labels = "".join(f"<a class='ex' href='/?q={_q(q)}'>{esc(label)}</a>"
                     for label, q, _, _ in EXAMPLES)
    return ("<aside aria-label='메뉴'>"
            "<a class='nav sel' href='/' aria-current='page'>질문하기</a>"
            f"<div class='aside-label'>예시 질문</div>{labels}"
            "<div class='guide'><b>출처부터 확인하세요</b>이 화면의 결과는 참고용입니다. "
            "원문과 검토 표시를 확인한 뒤 안내하세요.</div></aside>")


def search_form(query="", focus=True):
    return ("<form class='search' action='/' method='get'>"
            f"<input type='text' name='q' value='{esc(query)}' placeholder='직접 질문해 보세요'"
            f"{' autofocus' if focus else ''} autocomplete='off'>"
            "<button type='submit' tabindex='-1'>질문</button></form>")


def shell(content):
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>상담원 보조 검색 - 데모</title><style>{CSS}</style></head><body>"
        "<header class='top'><span class='brandmark'>A</span><span class='brand'>상담 지원</span>"
        "<span class='sep'></span><span class='ws'>데모</span></header>"
        f"<div class='layout'><main>{content}</main>{sidebar()}</div></body></html>")


def home():
    chips = "".join(
        f"<a class='chip' href='/?q={_q(q)}'><b>{esc(label)}</b><br>{esc(q)}"
        f"<small>{esc(shows)}</small></a>"
        for label, q, _, shows in EXAMPLES)
    return ("<h1 class='hero'>무엇을 확인할까요?</h1>"
            "<p class='sub'>예시 질문을 눌러 보거나 직접 입력해 보세요.</p>"
            "<div class='demo-note'><b>이 화면은 데모입니다.</b> 가상 기관(누리직업능력개발협회)의 가상 문서 "
            "53개로 돌아가며, 실제 자료는 들어 있지 않습니다. 아래 예시는 시스템이 하는 <b>행동의 "
            "종류</b>를 보이려고 고른 것이며 성능 평가가 아닙니다. 직접 입력한 질문에는 거절이 많이 "
            "나옵니다.</div>"
            f"<div class='chips'>{chips}</div>{search_form(focus=True)}")


def candidates(query, hits, opened_id):
    current = " aria-current='true'"
    rows = "".join(
        f"<li><a href='/?q={_q(query)}&amp;doc={_q(h.doc_id)}'"
        f"{current if h.doc_id == opened_id else ''}>"
        f"<span class='rankbox'>{n}</span><div><div class='title'>{esc(title_of(h.doc))}</div>"
        f"<div class='snippet'>{esc(snippet(h.doc))}</div>"
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
        return shell(home())
    query = query.strip()
    hits, decision, badge, body = decision_view(query)
    docs = _docs_by_id()
    opened = docs.get(doc_id) if doc_id else None
    close_url = f"/?q={_q(query)}&list=1"
    if list_only:
        right, split, focus = "", "split", True
    elif opened is not None:
        served = decision.action in ("answer", "answer_flagged")
        verdict = (f"이 문서는 후보입니다. 게이트의 판단은 <b>{esc(LABEL[decision.action])}</b>입니다."
                   if not served or decision.docs[0]["id"] != opened["id"] else
                   "이 문서가 게이트가 낸 답입니다.")
        right = pane(f"<h2>{esc(title_of(opened))}</h2>",
                     doc_body_html(opened),
                     f"<p class='why'>{verdict}</p>"
                     f"<p class='why'><a href='/?q={_q(query)}'>← 게이트의 판단 보기</a></p>"
                     f"<div class='meta'>{esc(opened['id'])} · {opened['kind']}</div>",
                     close_url)
        split, focus = "split open", False
    else:
        right = pane(f"<h2>게이트의 판단</h2>{badge}"
                     f"<p class='why'>질문: {esc(query)}</p>", body,
                     seen_html(hits, decision), close_url)
        split, focus = "split open", False
    listing = (f"<div class='list'>{search_form(query, focus=focus)}"
               f"{candidates(query, hits, opened['id'] if opened else None)}</div>")
    return shell(f"<div class='{split}'>{listing}{right}</div>")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/":
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)

        def one(name):
            return params.get(name, [""])[0]

        data = page(one("q")[:300], one("doc") or None, bool(one("list"))).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # no query text in logs
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    retrieve.warmup()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"http://{args.host}:{args.port}/   (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
