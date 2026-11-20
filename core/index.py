"""knowledge/docs.jsonl -> a searchable index.

A few hundred documents at most, so every stage looks at every document: the BM25
statistics are plain dicts and the embeddings are one numpy array scanned by
brute force. No vector database, no ANN index -- they solve approximate search at
a scale this project does not have.

Which method, which match target, and which embedding model are configuration
(`config.yaml`), so changing them is a config change rather than an edit here.
"""
import collections
import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "knowledge" / "docs.jsonl"

NGRAM = 2       # character bigrams -- the dependency-free Korean default.
K1 = 1.5
B = 0.75
# `retrieval.method: hybrid` fuses by Reciprocal Rank Fusion -- by rank, because
# BM25 is unbounded above and cosine is not. 60 is the constant of the original
# RRF paper, not a fitted value.
RRF_K = 60


def load_docs(path=None):
    with (path or DOCS).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def body(doc):
    """The searchable content of a document.

    `table` records keep their content in `cells` ("F3=교육운영팀"), not in
    `answer`, which holds only the page's navigation chrome. Indexing `answer`
    alone would make every table document unreachable. Cell references are
    dropped; only the values are text.
    """
    text = doc["answer"]
    if doc.get("cells"):
        values = [c.split("=", 1)[1] for c in doc["cells"] if "=" in c]
        text = "\n".join([text.strip(), *values]).strip()
    return text


def servable(doc):
    """Is there anything to put in front of an agent at all? A record with
    neither text nor an image would put an empty badge on the screen and score
    as a correct answer."""
    return bool(body(doc).strip() or doc.get("images"))


def parent_id(doc_or_id):
    """The document id a hit should be scored against. Gold is document ids; this
    is the single place that maps a hit to one (it is the identity until a
    configuration splits documents into chunks)."""
    if isinstance(doc_or_id, dict):
        return doc_or_id.get("parent_id") or doc_or_id["id"]
    return doc_or_id


def indexed_text(doc, match_target):
    """What the query is matched against. Most documents are Q&A pairs, so
    matching the stored *question* is a real option, not a workaround.
    page/table documents have no question, so they fall back to their body.

    `both` puts the stored question above the body -- the usual FAQ form."""
    if match_target == "question":
        return doc["question"].strip() or body(doc)
    if match_target == "both":
        return "\n".join(t for t in (doc["question"].strip(), body(doc).strip()) if t)
    return body(doc).strip() or doc["question"]


def tokens(text):
    """Character n-grams. Korean without a morphological analyser: crude, but it
    has no install story and no tokeniser to keep in sync between callers."""
    squeezed = "".join(text.split())
    return [squeezed[i:i + NGRAM] for i in range(len(squeezed) - NGRAM + 1)]


class BM25Index:
    """Okapi BM25. Scores are unbounded above, which is why thresholds are
    quantiles of a measured distribution rather than absolute cut points."""

    def __init__(self, docs, match_target):
        self.docs = docs
        self.postings = collections.defaultdict(dict)
        self.lengths = []
        for position, doc in enumerate(docs):
            counts = collections.Counter(tokens(indexed_text(doc, match_target)))
            self.lengths.append(sum(counts.values()) or 1)
            for term, count in counts.items():
                self.postings[term][position] = count
        self.average_length = sum(self.lengths) / len(self.lengths)
        self.idf = {
            term: math.log(1 + (len(docs) - len(where) + 0.5) / (len(where) + 0.5))
            for term, where in self.postings.items()
        }

    def scores(self, query):
        """{position: score} for every document sharing a term with the query."""
        scores = collections.defaultdict(float)
        for term in tokens(query):
            where = self.postings.get(term)
            if not where:
                continue
            idf = self.idf[term]
            for position, count in where.items():
                norm = 1 - B + B * self.lengths[position] / self.average_length
                scores[position] += idf * count * (K1 + 1) / (count + K1 * norm)
        return scores

    def search(self, query, k):
        ranked = sorted(self.scores(query).items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [(self.docs[p]["id"], score, self.docs[p]) for p, score in ranked]


class EmbeddingIndex:
    """Brute-force cosine over the document vectors -- exact, and microseconds.

    The encoder comes from `core.embed`, which is where the local/remote choice
    and the query scrubbing live. This class only knows that it is handed
    something with `.encode(texts, kind)`.
    """

    def __init__(self, docs, match_target, model_name, encoder=None):
        import numpy

        from core import embed

        self.numpy = numpy
        self.docs = docs
        self.encoder = encoder or embed.encoder(model_name)
        self.matrix = self.encoder.encode(
            [indexed_text(doc, match_target) for doc in docs], kind="document")

    def scores(self, query):
        """Cosine against every document, by position."""
        return self.matrix @ self.encoder.encode([query], kind="query")[0]

    def search(self, query, k):
        scores = self.scores(query)
        top = self.numpy.argsort(-scores)[:k]
        return [(self.docs[p]["id"], float(scores[p]), self.docs[p]) for p in top]


def rrf(rankings, k=RRF_K):
    """Reciprocal Rank Fusion: {position: sum of 1 / (k + rank)} over the
    rankings, rank counted from 1. A document absent from a ranking adds 0."""
    fused = collections.defaultdict(float)
    for ranking in rankings:
        for rank, position in enumerate(ranking, 1):
            fused[position] += 1.0 / (k + rank)
    return fused


class HybridIndex:
    """Embedding and BM25 over the same documents, fused by RRF.

    The score a hit carries is the fused one, so `top1` and `margin` are on the
    RRF scale (at most 2 / 61 for two lists). Thresholds fitted on another
    scale mean nothing here.
    """

    def __init__(self, docs, match_target, model_name, encoder=None):
        self.docs = docs
        self.embedding = EmbeddingIndex(docs, match_target, model_name, encoder=encoder)
        self.bm25 = BM25Index(docs, match_target)

    def search(self, query, k):
        dense = self.embedding.scores(query)
        dense_rank = sorted(range(len(self.docs)), key=lambda p: (-float(dense[p]), p))
        sparse = self.bm25.scores(query)
        sparse_rank = sorted(sparse, key=lambda p: (-sparse[p], p))
        fused = rrf([dense_rank, sparse_rank])
        ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [(self.docs[p]["id"], score, self.docs[p]) for p, score in ranked]


def build(config, docs=None):
    docs = docs if docs is not None else load_docs()
    settings = config["retrieval"]
    method, target = settings["method"], settings["match_target"]
    if method == "bm25":
        return BM25Index(docs, target)
    if method in ("embedding", "hybrid") and not settings["embedding_model"]:
        raise RuntimeError(f"retrieval.method is {method} but retrieval.embedding_model is null")
    if method == "embedding":
        return EmbeddingIndex(docs, target, settings["embedding_model"])
    if method == "hybrid":
        return HybridIndex(docs, target, settings["embedding_model"])
    raise RuntimeError(f"retrieval.method {method!r} is not built")
