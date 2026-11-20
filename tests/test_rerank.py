import copy
import json

from core import rerank, retrieve
from core.decide import CONFIG


def docs(n):
    return [{"id": f"d{i}", "question": f"q{i}", "answer": f"본문 {i}", "kind": "qa",
             "status": "ok", "attributes": {}, "images": []} for i in range(n)]


def reply(numbers):
    text = json.dumps({"ranked": numbers})
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_parse_valid_partial_and_garbage():
    assert rerank.parse('{"ranked": [3, 1, 2, 5, 4]}', 5) == ([2, 0, 1, 4, 3], "ok")
    order, status = rerank.parse('{"ranked": [2, 2, 9]}', 4)
    assert order == [1, 0, 2, 3] and status == "partial"
    assert rerank.parse("모르겠습니다", 3) == ([0, 1, 2], "unparsed")


def test_a_call_is_cached_per_pool():
    calls = []

    def transport(url, payload):
        calls.append(1)
        return reply([2, 1])

    r = rerank.GoogleRerank("m", key="k", transport=transport)
    pool = docs(2)
    assert r.rank("질문", pool).order == [1, 0]
    assert r.rank("질문", pool).order == [1, 0]
    assert len(calls) == 1 and r.counts["cached"] == 1


def test_a_transport_error_is_counted_not_hidden():
    def boom(url, payload):
        raise OSError("down")

    r = rerank.GoogleRerank("m", key="k", transport=boom)
    ranking = r.rank("질문", docs(3))
    assert ranking.status == "error" and ranking.order == [0, 1, 2]
    assert r.counts["error"] == 1


def test_the_query_is_scrubbed_in_the_payload():
    r = rerank.GoogleRerank("m", key="k", transport=lambda u, p: reply([1]))
    payload = r.payload("연락처 010-1234-5678", docs(1))
    assert "1234" not in json.dumps(payload, ensure_ascii=False)


class StubIndex:
    def __init__(self, pool):
        self.pool = pool

    def search(self, query, k):
        return [(d["id"], 10.0 - i, d) for i, d in enumerate(self.pool)][:k]


def test_retrieve_with_rerank_keeps_first_stage_scores_in_the_new_order(monkeypatch):
    pool = docs(4)
    monkeypatch.setattr(retrieve, "get_index", lambda config=None: StubIndex(pool))
    cfg = copy.deepcopy(CONFIG)
    cfg["retrieval"].update(rerank=True, rerank_model="m", rerank_pool=4, k=3)
    r = rerank.GoogleRerank("m", key="k", transport=lambda u, p: reply([3, 1, 2, 4]))
    hits = retrieve.retrieve("질문", config=cfg, reranker=r)
    assert [h.doc_id for h in hits] == ["d2", "d0", "d1"]
    assert [h.score for h in hits] == [8.0, 10.0, 9.0]   # first-stage scores, kept


def test_retrieve_without_rerank_is_the_first_stage(monkeypatch):
    pool = docs(3)
    monkeypatch.setattr(retrieve, "get_index", lambda config=None: StubIndex(pool))
    cfg = copy.deepcopy(CONFIG)
    cfg["retrieval"]["rerank"] = False
    assert [h.doc_id for h in retrieve.retrieve("q", 2, cfg)] == ["d0", "d1"]
