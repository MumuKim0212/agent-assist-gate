"""HTML for the agent's screen: a search box, a ranked list, and a document.

This is the demo's counterpart of the real tool's main screen, which is a ranked
list with **no gate**: what an agent sees is the ranking itself, a full document
one click away, and nothing that decides for them. The gate is a separate page
(`serve/gate_demo.py`, `/answer`) because that is how the real tool is laid out.

Server-rendered, no JavaScript. A click on a result is a navigation and a
"여기 없음" press is a form POST. The keyboard layer is here too: Tab from the
search box reaches the first result, Enter opens it, Alt+1..N opens the Nth
result, and every screen carries the shortcut line that says so.

Two render rules are per-document, not per-page:

- A `needs_review` document never appears without its badge -- in the list as well
  as on the document page. An agent relays what they see on a live call.
- A document with nothing to serve shows its question and a notice, never an empty
  entry. The list does not hide it (hiding would be a gate); it labels it.

What the demo leaves out, because the synthetic corpus has nothing to show or
nothing should be stored: document images, the "이거 틀림" report, and the event
log behind the weekly numbers. "여기 없음" is pressable and records nothing.
"""
import contextvars
import html
import urllib.parse

from core import index
from serve import departments

# The documents this browser opened recently, as (id, title), newest first. Set by
# the server at the start of each request so `page()` can draw the sidebar without
# every screen passing them down.
RECENT = contextvars.ContextVar("recent_docs", default=())

REVIEW_REASONS = {
    "unresolved_conflict": "원본 자료 간 값이 충돌 — 확인 필요",
    "answer_only_in_image": "답변이 이미지 안에만 있음",
    "answer_missing": "답변 내용이 없음",
    "transcribed_from_image": "이미지에서 수동 전사 — 확인 대기",
}

STYLE = """
:root { color-scheme: light; --ink: #17212b; --muted: #64717d; --accent: #1d4e5a }
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
aside a.nav { display: block; padding: .55rem .7rem; border-radius: 8px; color: #5e6d79;
              font-size: .85rem; text-decoration: none }
aside a.nav:hover { background: #dfe8eb }
aside a.nav.sel { background: #d6e5e7; color: #1d525d; font-weight: 700 }
.aside-label { font: 10px Consolas, monospace; letter-spacing: .12em; color: #85929d;
               margin: 1.4rem .7rem .4rem }
ul.recent { list-style: none; margin: 0; padding: 0 }
ul.recent a { display: block; padding: .25rem .7rem; font-size: .78rem; color: #4c5b66;
              text-decoration: none; overflow: hidden; text-overflow: ellipsis;
              white-space: nowrap }
ul.recent a:hover { text-decoration: underline }
.recent-empty { margin: 0 .7rem; font-size: .75rem; color: #8c98a2 }
.guide { margin: 1.4rem .3rem 0; background: #f3f6f7; border: 1px solid #dce4e7;
         border-radius: 10px; padding: .7rem; font-size: .72rem; line-height: 1.6;
         color: #71808b }
.guide b { display: block; font-size: .78rem; color: #344858 }
@media (max-width: 850px) {
  .layout { grid-template-columns: 1fr; grid-template-areas: "main" "side" }
  main { padding: 1.2rem 1rem 2rem }
  aside { border-right: 0; border-top: 1px solid #dce3e7 }
}

main h1 { font-size: 1.35rem; letter-spacing: -.02em; margin: 0 0 .6rem }
h1.hero { font-size: 1.5rem; letter-spacing: -.03em; margin: 0 0 .3rem }
p.sub { color: #83909a; font-size: .85rem; margin: 0 0 1rem }
.demo-note { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 8px;
             padding: .6rem .9rem; font-size: .85rem; margin: 1.2rem 0 }
.demo-note a { color: #0969da }
.examples { margin: 0 0 1.2rem; font-size: .85rem; color: #59636e }
.examples a { display: inline-block; margin: .15rem .5rem .15rem 0; color: #0969da }
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
            padding: .9rem 1rem; text-decoration: none }
ol.hits a:hover, ol.hits a:focus-visible { border-color: #93b7bd;
            box-shadow: 0 0 0 2px #d4e5e7; outline: 0 }
ol.hits a:hover .title { text-decoration: underline }
ol.hits a[aria-current] { border-color: var(--accent); box-shadow: 0 0 0 2px #cfe3e6 }
.rankbox { display: grid; place-items: center; background: #edf2f3; border-radius: 7px;
           height: 2rem; color: #536b75; font: .8rem Consolas, monospace }
.title { font-size: 1.05rem; font-weight: 600; color: #203646 }
.snippet { color: #697984; margin-top: .2rem; font-size: .9rem }
.meta { font: .75rem Consolas, monospace; color: #9aa5ab; margin-top: .3rem }
.note { margin-top: 1.2rem; font-size: .78rem; color: #8c98a2 }

/* needs_review: the badge a document never appears without. */
.badge { display: inline-block; margin: .3rem .3rem .1rem 0; padding: .1rem .55rem;
         border: 1px solid #c77; background: #fdecec; color: #a33;
         border-radius: 999px; font-size: .8rem; font-weight: 600 }
.reasons { color: #a33; font-size: .85rem }
.answer { white-space: pre-wrap; margin: 1rem 0 }
table.cells { border-collapse: collapse; margin: 1rem 0; font-size: .9rem }
table.cells td { border: 1px solid #bbb; padding: .25rem .5rem; vertical-align: top }
table.cells td.ref { color: #888; font-family: Consolas, monospace; white-space: nowrap }
.notice { border-left: 3px solid #a33; padding: .4rem .7rem; margin: 1rem 0; color: #a33 }
.none { margin-top: 2rem }
form.none button { border: 1px dashed #c4d0d5; background: transparent; color: #536b75;
                   padding: .55rem .9rem; border-radius: 7px; font-size: .85rem;
                   cursor: pointer }
.empty { color: #666; margin-top: 2rem }
.keys { margin-top: .6rem; padding-top: .6rem; border-top: 1px solid #dfe5e8;
        font-size: .8rem; color: #777 }
kbd { font-family: Consolas, monospace; border: 1px solid #bbb; border-radius: 3px;
      padding: 0 .25rem; font-size: .95em }
table.dept { border-collapse: collapse; width: 100%; background: #fff;
             border: 1px solid #e1e6e9; font-size: .9rem }
table.dept th { text-align: left; background: #edf2f3; color: #536b75;
                font-size: .78rem; padding: .45rem .7rem }
table.dept td { border-top: 1px solid #eef1f3; padding: .55rem .7rem; vertical-align: top }
table.dept td.team { font-weight: 700; white-space: nowrap; width: 9rem }
table.dept ul { margin: 0; padding-left: 1.1rem }

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
.docbody .answer { margin: 0 }
.docbody table:first-child { margin-top: 0 }
.body { white-space: pre-wrap; margin: .4rem 0 }
.docfoot { padding: .8rem 1.5rem 1.1rem; background: #f6f8f9; border-top: 1px solid #dfe5e8;
           border-radius: 0 0 10px 10px; font-size: .85rem; line-height: 1.5 }
.why { color: #59636e; font-size: .88rem }
table { border-collapse: collapse; font-size: .85rem; margin-top: .4rem }
td, th { border: 1px solid #d0d7de; padding: .2rem .6rem; text-align: left }
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

/* The gate demo (serve/gate_demo.py): the action the gate chose. */
.action { display: inline-block; color: #fff; border-radius: 999px; padding: .1rem .75rem;
          font-size: .88rem; font-weight: 600 }
"""


def esc(text):
    return html.escape(str(text), quote=True)


def _quote(value):
    return urllib.parse.quote(value, safe="")


# -- the shell -----------------------------------------------------------------------------

def header():
    return ("<header class='top'><span class='brandmark'>A</span>"
            "<span class='brand'>상담 지원</span><span class='sep'></span>"
            "<span class='ws'>지식 검색 · 데모</span></header>")


def sidebar(nav):
    """Navigation, the documents this browser opened lately, and a one-line guide.

    The recent list is a cookie of document ids (serve/app.py), never queries.
    The third link is the demo's own: the real tool keeps its gate on a separate
    route that is not in the menu, but this repository exists to show the gate.
    """
    def link(key, href, label):
        current = " aria-current='page'" if key == nav else ""
        return (f"<a class='nav{' sel' if key == nav else ''}' href='{href}'"
                f"{current}>{label}</a>")

    recent = RECENT.get()
    if recent:
        items = "".join(
            f"<li><a href='/doc?id={esc(_quote(doc_id))}' title='{esc(title)}'>{esc(title)}</a></li>"
            for doc_id, title in recent)
        recent_html = f"<ul class='recent'>{items}</ul>"
    else:
        recent_html = "<p class='recent-empty'>아직 열어 본 문서가 없습니다.</p>"
    return ("<aside aria-label='메뉴'>"
            f"{link('search', '/', '근거 검색')}"
            f"{link('departments', '/departments', '담당 부서 안내')}"
            f"{link('gate', '/answer', '게이트 데모')}"
            "<div class='aside-label'>최근 확인 문서</div>"
            f"{recent_html}"
            "<div class='guide'><b>출처부터 확인하세요</b>검색 결과는 참고 문서 순위입니다. "
            "원문과 검토 표시를 확인한 뒤 안내하세요.</div></aside>")


def page(title, body, nav="search"):
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{STYLE}</style></head>"
            f"<body>{header()}<div class='layout'><main>{body}</main>{sidebar(nav)}"
            "</div></body></html>")


def search_form(query="", action="/search", focus=True):
    """`focus` is off on the pages that exist to be **read** -- a document. Autofocus
    there would leave the caret in the input, and then Space and PageDown type
    instead of scrolling. `accesskey=s` reaches the box on those pages instead."""
    return (f"<form class='search' action='{esc(action)}' method='get'>"
            f"<input name='q' value='{esc(query)}' accesskey='s'"
            f"{' autofocus' if focus else ''} "
            "placeholder='찾을 내용을 입력하세요' autocomplete='off'>"
            "<button tabindex='-1'>검색</button></form>")


def keys(*pairs):
    """The shortcut line, rendered on every screen. Tab and Enter are plain focus
    movement (the submit button is out of the tab order so that one Tab from the box
    reaches the first result); accesskey is the shortcut on top -- Alt in Chrome and
    Edge, Alt+Shift in Firefox."""
    shown = " · ".join(f"<kbd>{esc(key)}</kbd> {esc(label)}" for key, label in pairs)
    return f"<div class='keys'>{shown}</div>"


# -- documents -----------------------------------------------------------------------------

def title_of(doc):
    return doc["question"].strip() or doc["sheet"]


def badge(doc):
    """`status` is already in the data; this is the render rule."""
    if doc.get("status") != "needs_review":
        return ""
    reasons = " · ".join(esc(REVIEW_REASONS.get(reason, reason))
                         for reason in doc.get("review_reasons") or [])
    return f"<div class='badge'>확인 필요</div><div class='reasons'>{reasons}</div>"


def snippet(doc, query="", limit=180):
    """A window around the first word of the query that appears in the document, not
    the first 180 characters of it. Several records start with the same site chrome,
    so a head-of-document snippet renders different results as identical lines."""
    text = " ".join(index.body(doc).split())
    if not text:
        return "(내용 없음 — 질문만 있는 문서)"
    start = 0
    for word in query.split():
        found = text.find(word)
        if found >= 0:
            start = max(0, found - limit // 4)
            break
    window = text[start:start + limit]
    return ("…" if start else "") + window + ("…" if start + limit < len(text) else "")


def document_content(doc, heading="h1"):
    """The document itself, as three regions: `head` (title and badge), `body` (the
    answer or a table) and `meta` (the id line). One function for the full page and
    for the pane beside the list, so the render rules hold on both."""
    head = [f"<{heading}>{esc(title_of(doc))}</{heading}>", badge(doc)]
    parts = []
    if not index.servable(doc):
        parts.append("<p class='notice'>이 문서에는 제공할 내용이 없습니다. "
                     "질문만 등록된 상태입니다.</p>")
    elif doc.get("cells"):
        # A table record's content is its `cells`; `answer` is the page's chrome.
        if doc["answer"].strip():
            parts.append(f"<div class='answer'>{esc(doc['answer'])}</div>")
        rows = "".join(
            f"<tr><td class='ref'>{esc(ref)}</td><td>{esc(value)}</td></tr>"
            for ref, _, value in (cell.partition("=") for cell in doc["cells"]))
        parts.append(f"<table class='cells'>{rows}</table>")
    else:
        parts.append(f"<div class='answer'>{esc(doc['answer'])}</div>")
    meta = f"<div class='meta'>{esc(doc['id'])} · {esc(doc['sheet'])} · {doc['kind']}</div>"
    return head, parts, meta


def detail_pane(doc, close):
    """The document opened from the list. Wide windows show it to the right of the
    list; narrow ones show it as a modal over the list (CSS decides). `close` is the
    list's own URL without the document, so closing is a navigation like everything
    else here. The close link is first in the pane and takes Alt+B."""
    head, body, meta = document_content(doc, heading="h2")
    return (f"<a class='backdrop' href='{esc(close)}' tabindex='-1' aria-hidden='true'></a>"
            f"<section class='detail' tabindex='-1' autofocus aria-label='{esc(title_of(doc))}'>"
            "<header class='dochead'>"
            f"<div class='closebar'><a accesskey='b' href='{esc(close)}'>✕ 닫기</a></div>"
            f"<div class='doctitle'>{''.join(head)}</div></header>"
            f"<div class='docbody'>{''.join(body)}</div>"
            f"<footer class='docfoot'>{meta}</footer></section>")


def document_page(doc, back, query=""):
    head, body, meta = document_content(doc)
    parts = head + body + [meta]
    parts.append(f"<p class='none'><a accesskey='b' href='{esc(back)}'>← 검색 결과로</a></p>")
    parts.append(keys(("Alt+B", "검색 결과로"), ("Alt+S", "새 검색")))
    # The search box is here so that the next question does not cost a trip back, and
    # it is NOT focused: this page is read and scrolled.
    return page(title_of(doc), search_form(focus=False) + "".join(parts))


# -- the screens ---------------------------------------------------------------------------

def search_page(examples=()):
    """The home screen. `examples` are (label, question) pairs: the real tool has
    none, but a demo needs somewhere to start."""
    note = ("<div class='demo-note'><b>이 화면은 데모입니다.</b> 가상 기관(누리직업능력개발협회)의 가상 문서 "
            f"{len(index.load_docs())}개로 돌아가며 실제 자료는 들어 있지 않습니다. 결과는 방법이 돌아간다는 "
            "표시일 뿐 성능 평가가 아닙니다. 직접 입력한 질문에는 순위만 보이고, 게이트가 같은 질문을 "
            "어떻게 판단하는지는 <a href='/answer'>게이트 데모</a>에서 볼 수 있습니다. "
            "'여기 없음'은 눌러도 아무것도 기록하지 않습니다.</div>")
    links = ""
    if examples:
        links = ("<p class='examples'>예시 질문: "
                 + "".join(f"<a href='/search?q={_quote(q)}'>{esc(q)}</a>" for _, q in examples)
                 + "</p>")
    return page("상담 검색",
                "<h1 class='hero'>무엇을 확인할까요?</h1>"
                "<p class='sub'>질문이나 통화 중 들은 핵심어를 입력하세요.</p>"
                + search_form() + keys(("Alt+S", "검색어")) + links + note)


def results_page(query, hits, pressed_none=False, doc=None):
    """The ranked list, and with `doc` the opened document beside or over it. A result
    links to `/search?...&doc=...&rank=...`, the same list rendered again with that
    document open; the opened result is marked `aria-current`, which says which one is
    open and not that it is the best one."""
    back = _quote(query)
    opened = doc["id"] if doc is not None else None
    current = " aria-current='true'"
    if hits:
        # The rank doubles as the shortcut: Alt+2 opens the second result.
        rows = "".join(
            f"<li><a accesskey='{rank}' "
            f"href='/search?q={back}&amp;doc={esc(_quote(hit.doc_id))}&amp;rank={rank}'"
            f"{current if hit.doc_id == opened else ''}>"
            f"<span class='rankbox'>{rank}</span><div>"
            f"<div class='title'>{esc(title_of(hit.doc))}</div>"
            f"{badge(hit.doc)}"
            f"<div class='snippet'>{esc(snippet(hit.doc, query))}</div>"
            f"<div class='meta'>{esc(hit.doc_id)} · {hit.doc['kind']}"
            f" · {hit.score:.2f}</div></div></a></li>"
            for rank, hit in enumerate(hits, start=1))
        body = (f"<div class='reshead'><h2>검색 결과</h2>"
                f"<span class='count'>{len(hits)} DOCUMENTS</span></div>"
                f"<ol class='hits'>{rows}</ol>")
    else:
        body = "<p class='empty'>검색 결과가 없습니다.</p>"
    if pressed_none:
        footer = "<p class='none'>‘여기 없음’을 눌렀습니다. 이 데모는 아무것도 기록하지 않습니다.</p>"
    else:
        footer = ("<form class='none' action='/not_here' method='post'>"
                  f"<input type='hidden' name='q' value='{esc(query)}'>"
                  "<button accesskey='n'>여기 없음</button></form>")
    if hits:
        pairs = [("Tab", "결과 이동"), ("Enter", "열기"),
                 ("Alt+1~%d" % len(hits), "바로 열기"), ("Alt+S", "검색어"),
                 ("Alt+N", "여기 없음")]
        if doc is not None:
            pairs.append(("Alt+B", "문서 닫기"))
        hint = keys(*pairs)
    else:
        hint = keys(("Alt+S", "검색어"), ("Alt+N", "여기 없음"))
    note = "<p class='note'>순위는 참고용입니다 · 답변 전 원문 확인</p>" if hits else ""
    form = search_form(query, focus=doc is None)
    listing = f"<div class='list'>{form}{body}{footer}{note}{hint}</div>"
    if doc is None:
        pane, split = "", "split"
    else:
        pane, split = detail_pane(doc, f"/search?q={back}"), "split open"
    return page(f"{query} — 상담 검색", f"<div class='{split}'>{listing}{pane}</div>")


def departments_page(doc, query=""):
    """Every team in the routing table and the topics each one owns, filterable. The
    table is the same record `refuse` reads, parsed the same way, so this page and a
    refusal can never name different teams."""
    form = ("<form class='search' action='/departments' method='get'>"
            f"<input name='q' value='{esc(query)}' accesskey='s' autofocus "
            "placeholder='주제나 팀 이름으로 찾기' autocomplete='off'>"
            "<button tabindex='-1'>찾기</button></form>")
    head = ("<h1 class='hero'>담당 부서 안내</h1>"
            "<p class='sub'>문서에 답이 없는 질문을 어느 팀으로 넘기는지 주제별로 정리한 표입니다.</p>")
    if doc is None:
        body, source = "<p class='empty'>부서표를 찾을 수 없습니다.</p>", ""
    else:
        teams = departments.search(departments.table(doc), query)
        if teams:
            rows = "".join(
                f"<tr><td class='team'>{esc(team)}</td><td><ul>"
                + "".join(f"<li>{esc(topic)}</li>" for topic in topics)
                + "</ul></td></tr>"
                for team, topics in teams.items())
            body = ("<div class='reshead'><h2>팀별 담당 주제</h2>"
                    f"<span class='count'>{len(teams)} TEAMS</span></div>"
                    f"<table class='dept'><tr><th>팀</th><th>담당 주제</th></tr>{rows}</table>")
        else:
            body = "<p class='empty'>일치하는 팀이 없습니다. 다른 낱말로 찾아 보세요.</p>"
        source = (f"<p class='note'>원문: <a href='/doc?id={esc(_quote(doc['id']))}'>"
                  "부서이관건 문서</a></p>")
    return page("담당 부서 안내", head + form + body + source + keys(("Alt+S", "검색어")),
                nav="departments")
