"""query -> ranked hits. The half of the contract that both eval/ and serving
import; neither reimplements it.

    retrieve(query, k) -> list[Hit]

With `retrieval.rerank: true` the first-stage top `rerank_pool` documents are
re-ordered by an LLM (`core/rerank.py`). A hit keeps its **first-stage score**:
the gate reads `top1` off the document the rerank put first, and the score is
still on the first stage's scale, so thresholds fitted on that scale carry over.
"""
from core import index as index_module
from core.decide import CONFIG, Hit

_INDEX = None
_INDEX_KEY = None
_RERANKER = None


def get_index(config=None):
    """Built once and reused: a few dozen documents load in well under a second,
    so the only reason to cache is to keep it out of the per-query path."""
    global _INDEX, _INDEX_KEY
    config = config or CONFIG
    key = tuple(sorted(config["retrieval"].items(), key=lambda kv: kv[0]))
    if _INDEX is None or _INDEX_KEY != key:
        _INDEX, _INDEX_KEY = index_module.build(config), key
    return _INDEX


def warmup(config=None):
    """Call at startup. Without it the first query pays the whole index build,
    which under `method: embedding` means encoding every document."""
    get_index(config)


def get_reranker(config):
    global _RERANKER
    model = config["retrieval"].get("rerank_model")
    if not model:
        raise RuntimeError("retrieval.rerank is true but retrieval.rerank_model is null")
    if _RERANKER is None or _RERANKER.model != model:
        from core import rerank
        _RERANKER = rerank.GoogleRerank(model)
    return _RERANKER


def retrieve(query, k=None, config=None, reranker=None):
    config = config or CONFIG
    settings = config["retrieval"]
    k = k or settings["k"]
    if not settings.get("rerank"):
        return [Hit(*hit) for hit in get_index(config).search(query, k)]
    pool = [Hit(*hit) for hit in
            get_index(config).search(query, max(k, settings.get("rerank_pool", 15)))]
    if len(pool) < 2:
        return pool[:k]
    ranking = (reranker or get_reranker(config)).rank(query, [h.doc for h in pool])
    return [pool[i] for i in ranking.order][:k]
