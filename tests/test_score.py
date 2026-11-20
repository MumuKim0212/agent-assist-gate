"""The scorer's arithmetic and its two-pass shape. Structure, never a score."""
import copy
import math

import pytest

from core.decide import CONFIG
from eval import score


def test_clopper_pearson_matches_the_closed_form_at_the_edges():
    # k = 0 of n: the one-sided 95% upper bound is 1 - 0.05 ** (1 / n)
    for n in (5, 20, 60):
        assert score.clopper_pearson_upper(0, n) == pytest.approx(1 - 0.05 ** (1 / n), abs=1e-6)
    # k = n of n: the lower bound is 0.05 ** (1 / n)
    assert score.clopper_pearson_lower(20, 20) == pytest.approx(0.05 ** (1 / 20), abs=1e-6)
    assert score.clopper_pearson_lower(0, 10) == 0.0
    assert score.clopper_pearson_upper(10, 10) == 1.0
    assert score.clopper_pearson_lower(0, 0) is None


def test_the_bounds_bracket_the_point_estimate():
    for k, n in ((3, 10), (9, 60), (36, 50)):
        assert score.clopper_pearson_lower(k, n) < k / n < score.clopper_pearson_upper(k, n)


def test_mcnemar_is_exact_and_symmetric():
    a = [{"item_id": str(i), "selective_correct": True} for i in range(10)]
    b = [{"item_id": str(i), "selective_correct": i >= 8} for i in range(10)]
    result = score.mcnemar(a, b)
    assert (result["a_only"], result["b_only"]) == (8, 0)
    assert result["p_value"] == pytest.approx(2 * 0.5 ** 8, rel=1e-6)
    assert score.mcnemar(a, a)["p_value"] == 1.0


def test_a_contrastive_pair_needs_both_members():
    rows = [{"stratum": "contrastive", "pair_id": "p", "top1_in_gold": True},
            {"stratum": "contrastive", "pair_id": "p", "top1_in_gold": False},
            {"stratum": "contrastive", "pair_id": "q", "top1_in_gold": True},
            {"stratum": "contrastive", "pair_id": "q", "top1_in_gold": True}]
    result = score.contrastive_pairs(rows)
    assert (result["pairs"], result["correct"]) == (2, 1)


def test_every_item_gets_one_row_and_a_rule_name():
    cfg = copy.deepcopy(CONFIG)
    rows = score.load_items("all")
    per = score.run(rows, cfg)
    assert [r["item_id"] for r in per] == [r["item_id"] for r in rows]
    assert all(r["rule"] and r["action"] in
               ("answer", "answer_flagged", "clarify", "refuse") for r in per)


def test_metrics_come_from_the_rows_alone():
    cfg = copy.deepcopy(CONFIG)
    per = score.run(score.load_items("all"), cfg)
    metrics = score.score(per)
    assert {"answerable", "no-answer", "ambiguous"} <= set(metrics)
    cov = metrics["answerable"]["answer_coverage"]
    assert 0.0 <= cov <= 1.0
    assert metrics["answerable"]["answer_coverage_lower"] <= cov
    assert math.isclose(sum(metrics["rules"].values()), len(per))


def test_a_rerun_is_byte_identical():
    cfg = copy.deepcopy(CONFIG)
    rows = score.load_items("holdout")
    first = score.run(rows, cfg)
    second = score.run(rows, cfg)
    assert first == second


def test_the_holdout_and_tune_splits_do_not_overlap():
    tune = {r["item_id"] for r in score.load_items("tune")}
    holdout = {r["item_id"] for r in score.load_items("holdout")}
    assert tune and holdout and not tune & holdout
