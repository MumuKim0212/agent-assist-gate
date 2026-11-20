import numpy

from core import index


def d(doc_id, question, answer, kind="qa", cells=None):
    rec = {"id": doc_id, "question": question, "answer": answer, "kind": kind,
           "status": "ok", "attributes": {}, "images": []}
    if cells is not None:
        rec["cells"] = cells
    return rec


DOCS = [d("a", "사진 규격", "증명사진 3.5×4.5cm 1장"),
        d("b", "환불 규정", "개강 7일 전까지 전액 환불"),
        d("t", "", "조직도", kind="table", cells=["F3=교육운영팀", "H3=강사 지원 문의"])]


def test_body_reads_table_cells_not_just_the_chrome():
    assert "강사 지원 문의" in index.body(DOCS[2])
    assert "F3" not in index.body(DOCS[2])


def test_servable():
    assert index.servable(DOCS[0])
    assert not index.servable(d("x", "q", "  "))
    assert index.servable(dict(d("x", "q", ""), images=["a.png"]))


def test_bm25_finds_the_document_that_shares_the_words():
    idx = index.BM25Index(DOCS, "answer")
    assert idx.search("환불은 개강 일주일 전", 3)[0][0] == "b"
    assert idx.search("강사 지원", 3)[0][0] == "t"


def test_bm25_scores_nothing_when_no_term_is_shared():
    assert index.BM25Index(DOCS, "answer").search("zzzz", 3) == []


def test_match_target_changes_what_is_indexed():
    doc = d("a", "사진 규격", "본문 내용")
    assert index.indexed_text(doc, "answer") == "본문 내용"
    assert index.indexed_text(doc, "question") == "사진 규격"
    assert index.indexed_text(doc, "both") == "사진 규격\n본문 내용"
    assert index.indexed_text(d("t", "", "본문"), "question") == "본문"


class FakeEncoder:
    """Deterministic: one axis per topic, so cosine is exact."""

    def encode(self, texts, kind="document"):
        out = []
        for t in texts:
            v = numpy.zeros(3)
            v[0 if "사진" in t else 1 if "환불" in t else 2] = 1.0
            out.append(v)
        return numpy.array(out)


def test_embedding_index_ranks_by_cosine():
    idx = index.EmbeddingIndex(DOCS, "both", None, encoder=FakeEncoder())
    top = idx.search("사진 문의", 2)
    assert top[0][0] == "a" and abs(top[0][1] - 1.0) < 1e-9


def test_hybrid_fuses_ranks_and_scores_on_the_rrf_scale():
    idx = index.HybridIndex(DOCS, "both", None, encoder=FakeEncoder())
    best = idx.search("환불 규정", 3)[0]
    assert best[0] == "b" and best[1] <= 2 / (index.RRF_K + 1)


def test_rrf_rewards_agreement():
    fused = index.rrf([[0, 1], [0, 2]])
    assert fused[0] > fused[1] and fused[0] > fused[2]
