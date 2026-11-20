"""The synthetic corpus and eval set are internally consistent.

These tests check structure, never a score: a score on this data says nothing
about retrieval quality, because one author wrote both halves.
"""
import collections
import json

from core import attributes, index
from eval import items

DOCS = index.load_docs()
BY_ID = {d["id"]: d for d in DOCS}
ROWS = [json.loads(l) for l in items.MANIFEST.read_text(encoding="utf-8").splitlines()
        if l.strip()]
FIELDS = {"id", "source", "sheet", "kind", "question", "answer", "images", "answer_is_image",
          "status", "review_reasons", "attributes", "image_capture_date"}


def test_ids_are_unique_and_records_have_the_contract_fields():
    assert len(BY_ID) == len(DOCS)
    for d in DOCS:
        assert FIELDS <= set(d), d["id"]
        assert d["kind"] in ("qa", "page", "table", "script")
        assert d["status"] in ("ok", "needs_review")


def test_qa_records_have_a_question_and_an_answer():
    for d in DOCS:
        if d["kind"] == "qa":
            assert d["question"].strip() and d["answer"].strip(), d["id"]


def test_tables_keep_their_content_in_cells():
    tables = [d for d in DOCS if d["kind"] == "table"]
    assert tables and all(d["cells"] for d in tables)


def test_attribute_values_are_in_the_vocabulary():
    for d in DOCS:
        for attribute, value in d["attributes"].items():
            assert value in attributes.VOCABULARY[attribute], (d["id"], attribute, value)


def test_the_needs_review_document_exists_so_the_badge_path_is_exercised():
    assert any(d["status"] == "needs_review" for d in DOCS)


def test_every_gold_id_is_in_the_corpus():
    for r in ROWS:
        for g in r["gold_ids"]:
            assert g in BY_ID, (r["item_id"], g)


def test_buckets_and_gold_shapes():
    for r in ROWS:
        assert r["bucket"] in ("answerable", "no-answer", "ambiguous")
        assert r["split"] in ("tune", "holdout")
        assert r["phrasing"].strip()
        if r["bucket"] == "no-answer":
            assert r["gold_ids"] == []
        else:
            assert r["gold_ids"]
        if r["bucket"] == "ambiguous":
            assert len(r["gold_ids"]) >= 2


def test_contrastive_pairs_are_pairs():
    pairs = collections.defaultdict(list)
    for r in ROWS:
        if r["stratum"] == "contrastive":
            pairs[r["pair_id"]].append(r)
    assert pairs and all(len(v) == 2 for v in pairs.values())
    for members in pairs.values():
        assert members[0]["gold_ids"] != members[1]["gold_ids"]


def test_every_bucket_has_tune_and_holdout_items():
    for bucket in ("answerable", "no-answer", "ambiguous"):
        splits = {r["split"] for r in ROWS if r["bucket"] == bucket}
        assert splits == {"tune", "holdout"}, bucket


def test_ids_are_unique_in_the_manifest():
    assert len({r["item_id"] for r in ROWS}) == len(ROWS)


def test_no_question_copies_a_stored_question():
    """The eval questions are written in the caller's words, not the document's."""
    stored = {d["question"].strip() for d in DOCS if d["question"].strip()}
    for r in ROWS:
        assert r["phrasing"].strip() not in stored, r["item_id"]
