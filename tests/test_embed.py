import numpy
import pytest

from core import embed


def fake_transport(sent):
    def transport(url, payload):
        sent.append(payload)
        return {"embeddings": [{"values": [3.0, 4.0]} for _ in payload["requests"]]}
    return transport


def test_a_query_is_scrubbed_before_it_leaves_and_a_document_is_not():
    sent = []
    enc = embed.GoogleEncoder("m", key="k", transport=fake_transport(sent))
    enc.encode(["전화는 010-1234-5678"], kind="query")
    enc.encode(["대표전화 02-000-0000"], kind="document")
    query_text = sent[0]["requests"][0]["content"]["parts"][0]["text"]
    doc_text = sent[1]["requests"][0]["content"]["parts"][0]["text"]
    assert "1234" not in query_text and "[전화번호]" in query_text
    assert doc_text == "대표전화 02-000-0000"
    assert enc.scrubbed == 1 and enc.kinds == {"전화번호": 1}


def test_vectors_are_normalised_by_us_not_the_provider():
    enc = embed.GoogleEncoder("m", key="k", transport=fake_transport([]))
    v = enc.encode(["x"], kind="document")
    assert numpy.allclose(numpy.linalg.norm(v, axis=1), 1.0)


def test_task_type_follows_kind():
    sent = []
    enc = embed.GoogleEncoder("m", key="k", transport=fake_transport(sent))
    enc.encode(["x"], kind="query")
    enc.encode(["x"], kind="document")
    assert [p["requests"][0]["taskType"] for p in sent] == ["RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT"]


def test_no_key_means_no_call(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(embed.env_module, "load", lambda *a, **k: ())
    enc = embed.GoogleEncoder("m", transport=lambda *a: pytest.fail("must not call"))
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        enc.encode(["x"], kind="query")


def test_wrong_vector_count_is_an_error_not_a_silent_truncation():
    enc = embed.GoogleEncoder("m", key="k", transport=lambda u, p: {"embeddings": []})
    with pytest.raises(RuntimeError):
        enc.encode(["x"], kind="document")


def test_spec_parsing():
    assert embed.encoder(None) is None
    with pytest.raises(ValueError):
        embed.encoder("openai:whatever")
