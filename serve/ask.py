"""Ask the gate one question from the command line.

    python -m serve.ask "교육이수카드를 처음 발급받고 싶어요"
    python -m serve.ask                       # interactive: one question per line

Prints the action the gate chose, the rule that fired, and what would be put in
front of the agent: the document(s) for `answer`, the competing documents and
what separates them for `clarify`, an owning department (if the routing table
clearly owns the topic) for `refuse`. Nothing is generated: every line shown is
stored text.
"""
import sys

from core import attributes, index, retrieve
from core.decide import CONFIG, decide
from serve import departments

LABEL = {"answer": "답변", "answer_flagged": "답변 (확인 필요 배지)",
         "clarify": "되묻기", "refuse": "거절"}


def routing_doc():
    for doc in index.load_docs():
        if doc["id"] == departments.ROUTING_ID:
            return doc
    return None


def render(query, hits, decision, routing=None):
    lines = [f"질문: {query}", f"행동: {LABEL[decision.action]}  [{decision.reason}]"]
    if decision.action in ("answer", "answer_flagged"):
        top = decision.docs[0]
        lines.append(f"  {top['id']}")
        if top.get("question"):
            lines.append(f"  Q. {top['question']}")
        lines += ["  " + l for l in index.body(top).splitlines()]
        if decision.action == "answer_flagged":
            lines.append("  ※ 이 문서는 내용 확인이 끝나지 않았습니다. 사실로 단정해 전달하지 마세요.")
        for other in decision.docs[1:]:
            lines.append(f"  (함께 볼 문서) {other['id']}")
    elif decision.action == "clarify":
        lines.append("  어느 쪽인지 먼저 물어보세요:")
        for doc in decision.docs:
            tags = ", ".join(f"{k}={v}" for k, v in attributes.of(doc).items()) or "-"
            lines.append(f"  - {doc.get('question') or doc['id']}  [{tags}]")
    else:
        team = departments.lookup(query, routing) if routing else None
        if team:
            lines.append(f"  담당 부서: {team}")
        elif decision.reason.startswith("2_gray"):
            lines.append("  검색 점수가 애매해서 자동으로 답하지 않습니다. 직접 찾아보세요.")
        else:
            lines.append("  이 질문은 문서에 없습니다. 담당 부서를 특정하지 못했습니다.")
        if hits:
            lines.append(f"  (참고: 가장 비슷한 문서는 {hits[0].doc_id}, 점수 {hits[0].score:.2f}"
                         f" -- 답이 아니라 이웃 문서일 수 있습니다)")
    return "\n".join(lines)


def ask(query, config=None):
    config = config or CONFIG
    hits = retrieve.retrieve(query, config=config)
    decision = decide(query, hits, config)
    return hits, decision


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    routing = routing_doc()
    retrieve.warmup()
    queries = [" ".join(argv)] if argv else None
    if queries:
        for q in queries:
            hits, decision = ask(q)
            print(render(q, hits, decision, routing))
        return 0
    print("질문을 한 줄씩 입력하세요 (빈 줄이면 종료).")
    while True:
        try:
            q = input("> ").strip()
        except EOFError:
            break
        if not q:
            break
        hits, decision = ask(q)
        print(render(q, hits, decision, routing))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
