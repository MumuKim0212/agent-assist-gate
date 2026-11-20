"""hits -> action. The gate, decided from retrieval state before anything is
written.

There are four actions: `answer`, `answer_flagged` (serve it with a "needs
verification" badge), `clarify` (ask the caller a question) and `refuse` (say it
is not covered, and point at the owning department). Nothing is generated.

The rule order below is the whole design and is not rearrangeable. `reason`
carries the rule that fired, which the scorer writes into per_example.jsonl so
that a correct `clarify` can be told apart from one that was right by accident.

Thresholds come from config.yaml and are never hardcoded here.
"""
import collections
import pathlib

import yaml

Hit = collections.namedtuple("Hit", "doc_id score doc")
Decision = collections.namedtuple("Decision", "action docs reason")

CONFIG_PATH = pathlib.Path(__file__).resolve().parent / "config.yaml"


def load_config(path=None):
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


CONFIG = load_config()


def decide(query, hits, config=None, evidence_check=None):
    """Returns (action, docs, reason).

    evidence_check is an optional callable (query, doc) -> bool used only inside
    the gray zone. If config enables the check and no callable is supplied this
    raises, rather than quietly skipping a safety stage.
    """
    from core import attributes, index

    config = config or CONFIG
    gate = config["thresholds"]

    if not hits:
        return Decision("refuse", [], "0_no_hits")

    # After a rerank the order is the rerank's, and `top1` / `margin` are read off
    # it as given: the reranked #1's own score, and #1 - #2, which may be
    # negative. Re-sorting here would undo the rerank before the gate saw it.
    if not config.get("retrieval", {}).get("rerank"):
        hits = sorted(hits, key=lambda h: h[1], reverse=True)
    top1 = hits[0]
    margin = top1[1] - hits[1][1] if len(hits) > 1 else float("inf")
    competing = [h for h in hits if top1[1] - h[1] <= gate["margin"]]
    prefix = ""

    # 1 -- nothing relevant. serve/ adds the owning department from the routing
    #      table; the gate only decides the action.
    if top1[1] < gate["top1_low"]:
        return Decision("refuse", [], "1_low_score")

    # 2 -- gray zone. A yes/no sufficiency judgement, never generation. While the
    #      check is unavailable the band takes the acceptable error (refusing a
    #      question that had an answer) rather than the critical one (serving a
    #      plausible wrong document); it never falls through toward `answer`.
    if top1[1] < gate["top1_high"]:
        if not config["gray_zone"]["evidence_check"]:
            return Decision("refuse", [], "2_gray_unchecked")
        if evidence_check is None:
            raise RuntimeError(
                "gray_zone.evidence_check is enabled but no evidence_check was supplied")
        if not evidence_check(query, top1[2]):
            return Decision("refuse", [], "2_evidence_check_failed")
        prefix = "2_evidence_checked+"

    # 3 -- the query states an attribute and the top document contradicts it.
    #      Query-side absence is not a mismatch and never reaches here.
    if config["attributes"]["query_extraction"]:
        if attributes.mismatch(attributes.extract(query), top1[2]):
            return Decision("clarify", [h[2] for h in competing],
                            prefix + "3_attribute_mismatch")

    # 4 -- the caller did not narrow it down and the competing documents
    #      differ among themselves. The caller can resolve this, so ask.
    #      Rules 3 and 4 have separate switches, so a weak query extractor can
    #      be turned off without taking `clarify` down with it.
    if config["attributes"]["document_tags"]:
        if margin < gate["margin"] and attributes.competing_attributes_differ(
                [h[2] for h in competing]):
            return Decision("clarify", [h[2] for h in competing],
                            prefix + "4_competing_conditions")

    # Rules 5 and 6 both serve the top document's own content, so they require
    # it to have some: a record with neither text nor an image is not an answer.
    if not index.servable(top1[2]):
        return Decision("refuse", [], prefix + "5_nothing_to_serve")

    # 5 -- our own data is not settled. Serve it, badge it, never as plain fact.
    if top1[2].get("status") == "needs_review":
        return Decision("answer_flagged", [h[2] for h in competing],
                        prefix + "5_needs_review")

    # 6 -- answer. A small margin here means two documents both answer, so the
    #      others ride along as additional sources rather than as a badge.
    return Decision("answer", [h[2] for h in competing], prefix + "6_answer")
