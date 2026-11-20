"""The scorer. One row per item, then metrics read off those rows.

`docs/evaluation-method.md` is the specification and this module is meant to be
read next to it. Three things about the shape, all of them consequences of that document:

**Scoring is two passes, not one.** `run()` produces `per_example.jsonl` -- one
row per eval item, carrying the query, the hits, the action, and *which
precedence rule produced it*. `score()` then computes every metric from that
file alone. Keeping them apart is what makes the paired test possible: two
configurations are two files over the same question set, so they can be compared
item by item rather than summary by summary.

**Gold means something different in each bucket, so there is no single scoring
path** -- the answerable bucket asks whether the served top 1 was right, the
no-answer bucket asks whether anything was served at all, and the ambiguous
bucket asks what fraction of the competing set reached the screen. Every metric
below says which bucket it belongs to.

**Two of the four actions count as an answer** (`answer`, `answer_flagged`) and
two do not (`clarify`, `refuse`). That branch is `SERVES`, defined once, because
every metric turns on it.

    python -m eval.score                      # holdout -- the headline numbers
    python -m eval.score --split tune         # in-sample, labelled as such
    python -m eval.score --split all
    python -m eval.score --config other.yaml --out eval/out/embedding
    python -m eval.score --compare a.jsonl b.jsonl      # paired, McNemar

What this does not do: pick an operating point, or say whether a number is good
enough. The bars (coverage floor, risk ceiling) are declared in
`core/config.yaml` and `docs/evaluation-method.md`, and they are read against
these numbers rather than written into them.
"""
import argparse
import collections
import hashlib
import json
import math
import pathlib
import sys

import yaml

from core import decide as decide_module
from core import index, retrieve
from eval import items

OUT = pathlib.Path(__file__).resolve().parent / "out"
SERVES = ("answer", "answer_flagged")
ALPHA = 0.05
SMALL_STRATUM = 25  # a metric read on this many holdout items or fewer does not gate


# --------------------------------------------------------------------------
# the eval set


def load_items(split=None):
    """Manifest rows joined to their question text, phrased items only.

    In this demo the question text is stored in the manifest itself (`phrasing`);
    an `items` file can supply it instead when the questions must stay out of the
    repository.
    """
    rows = [json.loads(l) for l in
            items.MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    text = items.phrasing()
    out = []
    for r in rows:
        if split and split != "all" and r["split"] != split:
            continue
        r = dict(r)
        r["query"] = r.get("phrasing") or text.get(r["item_id"], "")
        if r["query"].strip():
            out.append(r)
    return out


def load_config(path=None):
    path = pathlib.Path(path) if path else (index.ROOT / "core" / "config.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# the evidence-check cache seam


def content_hash(doc):
    return hashlib.sha256((index.body(doc) or "").encode("utf-8")).hexdigest()[:16]


class EvidenceCache:
    """Memoises a gray-zone evidence check per (query, doc_id, content hash).

    A re-run on an unchanged index must give identical numbers, and the evidence
    check is the one model stage the decision path may contain. The **content**
    hash rather than the id alone is the part that is easy to get wrong: a
    document's answer can be replaced under an unchanged id when a policy
    changes, so a key of (query, doc_id) would serve a verdict about text that
    no longer exists.

    The check is off in this demo (`gray_zone.evidence_check: false`), so
    `decide()` never calls through. The seam exists so that switching it on does
    not also change how the scorer behaves.
    """

    def __init__(self, check):
        self.check = check
        self.cache = {}
        self.calls = 0

    def key(self, query, doc):
        return (query, doc["id"], content_hash(doc))

    def __call__(self, query, doc):
        k = self.key(query, doc)
        if k not in self.cache:
            self.calls += 1
            self.cache[k] = self.check(query, doc)
        return self.cache[k]


# --------------------------------------------------------------------------
# pre-flight -- the two checks docs/evaluation-method.md requires before anything is run


def preflight(rows, cfg, hits_by_item=None):
    """`k` against the largest gold set, and the margin window's Coverage ceiling.

    Both come from the same paragraph in `docs/evaluation-method.md`: an item whose gold is
    four documents cannot exceed Coverage@3 however good retrieval is, and
    cannot be complete if the margin window admits only two of them. The first
    is a hard check -- a `k` below the largest gold set makes Coverage@served
    unreadable rather than low. The second is reported as a **ceiling on the
    metric**, never as a system result.
    """
    largest = max((len(r["gold_ids"]) for r in rows if r["gold_ids"]), default=0)
    k = cfg["retrieval"]["k"]
    out = {"largest_gold_set": largest, "k": k, "k_ok": k >= largest}

    if hits_by_item:
        # The ceiling is a property of the WINDOW, not of retrieval: how many
        # documents the margin admits at all, against how many gold the item
        # has. Counting gold inside the window instead would just be
        # Coverage@served computed twice, and would blame retrieval for a limit
        # the operating point imposes (docs/evaluation-method.md).
        margin = cfg["thresholds"]["margin"]
        widths, ceilings = [], []
        for r in rows:
            if r["bucket"] != "ambiguous" or not r["gold_ids"]:
                continue
            hits = hits_by_item[r["item_id"]]
            width = sum(1 for h in hits if hits[0].score - h.score <= margin) if hits else 0
            widths.append(width)
            ceilings.append(min(1.0, width / len(r["gold_ids"])))
        out["window_width"] = mean(widths)
        out["coverage_ceiling"] = mean(ceilings)
        out["coverage_ceiling_n"] = len(ceilings)
    return out


# --------------------------------------------------------------------------
# pass one -- one row per item


def hits_for(rows, cfg):
    """Retrieval, once. Pre-flight and scoring read the same hits, so a report
    can never describe a different run from the one it checked."""
    return {r["item_id"]: retrieve.retrieve(r["query"], cfg["retrieval"]["k"], cfg)
            for r in rows}


def run(rows, cfg, hits_by_item=None, evidence_check=None):
    """Decide over the hits and record. No metric is computed here."""
    from core import attributes

    hits_by_item = hits_by_item if hits_by_item is not None else hits_for(rows, cfg)

    check = None
    if cfg["gray_zone"]["evidence_check"]:
        if evidence_check is None:
            raise RuntimeError(
                "gray_zone.evidence_check is enabled but no evidence_check was supplied")
        check = evidence_check if isinstance(evidence_check, EvidenceCache) \
            else EvidenceCache(evidence_check)

    out = []
    for r in rows:
        hits = hits_by_item[r["item_id"]]
        decision = decide_module.decide(r["query"], hits, cfg, check)
        # A hit is scored on its parent document: a chunk is a retrieval unit,
        # a document is what gold names.
        hit_ids = [index.parent_id(h.doc) for h in hits]
        served_ids = [index.parent_id(d) for d in decision.docs]
        gold = set(r["gold_ids"])
        row = {
            "item_id": r["item_id"], "bucket": r["bucket"], "stratum": r["stratum"],
            "split": r["split"], "pair_id": r.get("pair_id"), "query": r["query"],
            "gold_ids": r["gold_ids"], "gold_needs_review": r.get("gold_needs_review", False),
            "hit_ids": hit_ids, "hit_scores": [round(h.score, 6) for h in hits],
            "top1": round(hits[0].score, 6) if hits else None,
            "margin": round(hits[0].score - hits[1].score, 6) if len(hits) > 1 else None,
            "top1_attributes": attributes.of(hits[0].doc) if hits else {},
            # rule 3 (query-side extraction) is off in this demo, so this is empty
            "query_attributes": {},
            "action": decision.action, "rule": decision.reason,
            "served_ids": served_ids,
            "serves": decision.action in SERVES,
        }
        row.update(correctness(row, gold))
        out.append(row)
    return out


def correctness(row, gold):
    """The per-bucket correctness fields. Each one names the metric it feeds."""
    hit_ids, served, bucket = row["hit_ids"], row["serves"], row["bucket"]
    top1_id = hit_ids[0] if hit_ids else None
    fields = {}

    if bucket == "answerable":
        fields["top1_in_gold"] = top1_id in gold if top1_id else False
        fields["recall_at_k"] = bool(gold & set(hit_ids))
        rank = next((n for n, h in enumerate(hit_ids, 1) if h in gold), None)
        fields["reciprocal_rank"] = 1.0 / rank if rank else 0.0
        # selective accuracy's numerator: served AND the served top 1 was gold
        fields["selective_correct"] = served and fields["top1_in_gold"]
        fields["false_refusal"] = row["action"] == "refuse"
        # a correct answer demoted to a question. Which rule did it is in `rule`,
        # so an extraction fault (3) can be told from a tag one (4).
        fields["false_demotion"] = row["action"] == "clarify" and fields["top1_in_gold"]
        # the badge is the whole mitigation, so putting it on the wrong document
        # -- or leaving it off the right one -- is a scored error, both ways
        fields["flag_correct"] = (not served) or (
            (row["action"] == "answer_flagged") == bool(row["gold_needs_review"]))
    elif bucket == "no-answer":
        fields["false_answer"] = served          # critical
        fields["false_clarify"] = row["action"] == "clarify"   # acceptable
    elif bucket == "ambiguous":
        fields["clarified"] = row["action"] == "clarify"
        fields["false_answer"] = served          # critical: one branch, ambiguity hidden
        # Coverage@served is computed on what the agent sees, never on top k.
        # Coverage@k sits beside it as the retrieval diagnostic: the gap between
        # them is what the margin window cost, and is not retrieval's fault.
        fields["coverage_at_served"] = (
            len(gold & set(row["served_ids"])) / len(gold) if gold else None)
        fields["coverage_at_k"] = (
            len(gold & set(hit_ids)) / len(gold) if gold else None)
    return fields


# --------------------------------------------------------------------------
# pass two -- metrics, read off the rows and nothing else


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def rate(rows, field):
    rows = [r for r in rows if r.get(field) is not None]
    return (sum(1 for r in rows if r[field]) / len(rows), sum(1 for r in rows if r[field]),
            len(rows)) if rows else (None, 0, 0)


def score(rows):
    """Every metric in docs/evaluation-method.md, per bucket, from the per-example rows."""
    out = collections.OrderedDict()
    by_bucket = collections.defaultdict(list)
    for r in rows:
        by_bucket[r["bucket"]].append(r)

    ans = by_bucket["answerable"]
    if ans:
        served = [r for r in ans if r["serves"]]
        cov, cov_k, cov_n = rate(ans, "serves")
        out["answerable"] = {
            "n": len(ans),
            # never one without the other
            "answer_coverage": cov,
            "answer_coverage_lower": clopper_pearson_lower(cov_k, cov_n),
            "selective_accuracy": (sum(1 for r in served if r["top1_in_gold"]) / len(served)
                                   if served else None),
            "selective_accuracy_n": len(served),
            "recall_at_k": rate(ans, "recall_at_k")[0],
            "mrr": mean([r["reciprocal_rank"] for r in ans]),
            "false_refusal": rate(ans, "false_refusal")[0],
            "false_demotion": rate(ans, "false_demotion")[0],
            "flag_accuracy": rate(ans, "flag_correct")[0],
            "contrastive_pairs": contrastive_pairs(ans),
            "by_stratum": {s: {"n": len(rs), "selective_accuracy":
                               (sum(1 for r in rs if r["selective_correct"]) /
                                sum(1 for r in rs if r["serves"])
                                if any(r["serves"] for r in rs) else None),
                               "answer_coverage": rate(rs, "serves")[0]}
                           for s, rs in group(ans, "stratum").items()},
        }

    noa = by_bucket["no-answer"]
    if noa:
        # near-miss and far are never pooled: a pooled rate improves by adding
        # far items, which is the wrong incentive (docs/evaluation-method.md)
        out["no-answer"] = {"n": len(noa), "by_stratum": {}}
        for stratum, rs in group(noa, "stratum").items():
            fa, fa_k, fa_n = rate(rs, "false_answer")
            out["no-answer"]["by_stratum"][stratum] = {
                "n": len(rs),
                "false_answer": fa,
                "false_answer_upper": clopper_pearson_upper(fa_k, fa_n),
                "false_clarify": rate(rs, "false_clarify")[0],
            }

    amb = by_bucket["ambiguous"]
    if amb:
        fa, fa_k, fa_n = rate(amb, "false_answer")
        clarified = [r for r in amb if r["clarified"]]
        out["ambiguous"] = {
            "n": len(amb),
            "clarify_accuracy": rate(amb, "clarified")[0],
            "false_answer": fa,
            "false_answer_upper": clopper_pearson_upper(fa_k, fa_n),
            "coverage_at_k": mean([r["coverage_at_k"] for r in amb]),
            "coverage_at_served": mean([r["coverage_at_served"] for r in amb]),
            "coverage_at_served_when_clarified": mean(
                [r["coverage_at_served"] for r in clarified]),
            "by_stratum": {s: {"n": len(rs), "clarify_accuracy": rate(rs, "clarified")[0],
                               "false_answer": rate(rs, "false_answer")[0]}
                           for s, rs in group(amb, "stratum").items()},
        }

    out["rules"] = dict(collections.Counter(r["rule"] for r in rows))
    return out


def group(rows, field):
    out = collections.OrderedDict()
    for r in rows:
        out.setdefault(r[field], []).append(r)
    return out


def contrastive_pairs(rows):
    """A pair counts only if **both** members retrieve their own gold.

    Getting one right by always preferring the same attribute value is not a
    pass -- that is the near-duplicate confusion the attribute layer exists for, and scoring the
    two items separately would hide it.
    """
    pairs = group([r for r in rows if r["stratum"] == "contrastive" and r["pair_id"]],
                  "pair_id")
    whole = [p for p in pairs.values() if len(p) == 2]
    if not whole:
        return {"pairs": 0, "accuracy": None}
    ok = sum(1 for p in whole if all(r["top1_in_gold"] for r in p))
    return {"pairs": len(whole), "correct": ok, "accuracy": ok / len(whole),
            "split_pairs": len(pairs) - len(whole)}


# --------------------------------------------------------------------------
# bounds and the paired test


def _binom_tail_ge(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p). Exact, and n is at most 310 here."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def _bisect(f, target, rising=True, lo=0.0, hi=1.0, steps=60):
    """Solve f(p) = target on [0, 1].

    `rising` is not decoration: the lower bound solves an increasing function of
    p and the upper bound a decreasing one, and running the increasing branch
    over the decreasing function converges on an endpoint instead of the root --
    which reads as a bound of 0%, silently, on exactly the metric a risk ceiling is certified against.
    """
    for _ in range(steps):
        mid = (lo + hi) / 2
        below = f(mid) < target
        if below == rising:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson_lower(k, n, alpha=ALPHA):
    """One-sided 95% LOWER bound -- what a coverage floor is certified against.

    An operating point clears the coverage floor when the lower bound does, not
    when the point estimate does. A point estimate of 72% does not clear 70%.
    """
    if n == 0:
        return None
    if k == 0:
        return 0.0
    # P(X >= k | p) rises with p; the bound is where it reaches alpha
    return _bisect(lambda p: _binom_tail_ge(k, n, p), alpha, rising=True)


def clopper_pearson_upper(k, n, alpha=ALPHA):
    """One-sided 95% UPPER bound -- what a risk ceiling is certified against."""
    if n == 0:
        return None
    if k == n:
        return 1.0
    # P(X <= k | p) falls with p; the bound is where it reaches alpha
    return _bisect(lambda p: 1 - _binom_tail_ge(k + 1, n, p), alpha, rising=False)


def mcnemar(rows_a, rows_b, field="selective_correct"):
    """Paired comparison of two runs over the same items.

    Exact McNemar on the discordant pairs. Paired because the two runs answer
    the *same* questions, which is what makes a difference this small readable
    at all -- bucket-level bounds cannot resolve it (docs/evaluation-method.md).
    """
    a = {r["item_id"]: r for r in rows_a}
    b = {r["item_id"]: r for r in rows_b}
    shared = [i for i in a if i in b
              and a[i].get(field) is not None and b[i].get(field) is not None]
    only_a = sum(1 for i in shared if a[i][field] and not b[i][field])
    only_b = sum(1 for i in shared if b[i][field] and not a[i][field])
    n = only_a + only_b
    if n == 0:
        p = 1.0
    else:
        k = min(only_a, only_b)
        p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"field": field, "n_compared": len(shared), "a_only": only_a, "b_only": only_b,
            "p_value": p,
            "effect_pp": (only_a - only_b) / len(shared) * 100 if shared else None}


# --------------------------------------------------------------------------
# reporting


def pct(v):
    return "   n/a" if v is None else f"{100 * v:5.1f}%"


def report(metrics, split, pre=None, stream=sys.stdout):
    def say(line=""):
        print(line, file=stream)

    if split == "holdout":
        say("HOLDOUT -- the headline numbers")
    else:
        say(f"{split.upper()} -- in-sample, not a headline number")
    say()

    if pre:
        ok = "ok" if pre["k_ok"] else "TOO SMALL"
        say(f"pre-flight: k={pre['k']} against the largest gold set "
            f"{pre['largest_gold_set']} -- {ok}")
        if not pre["k_ok"]:
            say("  Coverage@served is unreadable, not low: no k this small can hold "
                "the gold set")
        if pre.get("coverage_ceiling") is not None:
            say(f"  margin window holds {pre['window_width']:.1f} documents on average, "
                f"so Coverage@served cannot exceed {pct(pre['coverage_ceiling'])} on the "
                f"ambiguous bucket")
            say("  that is a ceiling imposed by the operating point, not a system result "
                "(docs/evaluation-method.md)")
        say()

    a = metrics.get("answerable")
    if a:
        say(f"ANSWERABLE  n={a['n']}")
        say(f"  answer coverage      {pct(a['answer_coverage'])}"
            f"   (95% lower bound {pct(a['answer_coverage_lower'])})   floor 70% / target 85%")
        say(f"  selective accuracy   {pct(a['selective_accuracy'])}"
            f"   over the {a['selective_accuracy_n']} items it served"
            "   <- never read without coverage")
        say(f"  Recall@k {pct(a['recall_at_k'])}   MRR {a['mrr']:.3f}"
            "      retrieval diagnostics, not the product metric")
        say(f"  false refusal {pct(a['false_refusal'])}   "
            f"false demotion {pct(a['false_demotion'])}   "
            f"badge accuracy {pct(a['flag_accuracy'])}")
        cp = a["contrastive_pairs"]
        say(f"  contrastive pairs    {cp.get('correct', 0)}/{cp['pairs']} "
            f"({pct(cp['accuracy'])}) -- both members must get their own gold")
        for s, v in a["by_stratum"].items():
            note = "  (<=25 holdout items: reported, does not gate)" \
                if split == "holdout" and v["n"] <= SMALL_STRATUM else ""
            say(f"    {s:<14} n={v['n']:<4} coverage {pct(v['answer_coverage'])}"
                f"   selective {pct(v['selective_accuracy'])}{note}")
        say()

    n = metrics.get("no-answer")
    if n:
        say(f"NO ANSWER  n={n['n']}   near-miss and far are never pooled")
        for s, v in n["by_stratum"].items():
            say(f"  {s:<11} n={v['n']:<4} false answer {pct(v['false_answer'])}"
                f"  (95% upper bound {pct(v['false_answer_upper'])})"
                f"   false clarify {pct(v['false_clarify'])}")
        say("  false answer is critical; false clarify is the acceptable failure")
        say()

    m = metrics.get("ambiguous")
    if m:
        say(f"AMBIGUOUS  n={m['n']}")
        say(f"  clarify accuracy     {pct(m['clarify_accuracy'])}")
        say(f"  false answer         {pct(m['false_answer'])}"
            f"   (95% upper bound {pct(m['false_answer_upper'])})   critical,"
            " never pooled with near-miss")
        say(f"  Coverage@served      {pct(m['coverage_at_served'])} over all items,"
            f" {pct(m['coverage_at_served_when_clarified'])} over the ones it clarified")
        say(f"  Coverage@k           {pct(m['coverage_at_k'])}"
            "   what retrieval found -- the gap to the line above is the margin"
            " window's cost, not retrieval's")
        for s, v in m["by_stratum"].items():
            note = "  (<=25 holdout items: reported, does not gate)" \
                if split == "holdout" and v["n"] <= SMALL_STRATUM else ""
            say(f"    {s:<18} n={v['n']:<3} clarify {pct(v['clarify_accuracy'])}"
                f"   false answer {pct(v['false_answer'])}{note}")
        say()

    say("rules fired: " + ", ".join(f"{k} {v}" for k, v in
                                    sorted(metrics["rules"].items())))


def main(argv=None):
    parser = argparse.ArgumentParser(description="score the eval set")
    parser.add_argument("--split", choices=["holdout", "tune", "all"], default="holdout")
    parser.add_argument("--config", help="a config.yaml to score instead of the shipped one")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"),
                        help="two per_example.jsonl files -- paired McNemar, no scoring")
    parser.add_argument("--field", default="selective_correct",
                        help="the boolean column --compare tests")
    args = parser.parse_args(argv)

    if args.compare:
        a, b = (read_rows(p) for p in args.compare)
        result = mcnemar(a, b, args.field)
        print(f"paired comparison on `{result['field']}` over {result['n_compared']} items")
        print(f"  A only {result['a_only']}   B only {result['b_only']}"
              f"   effect {result['effect_pp']:+.1f}pp   exact McNemar p = {result['p_value']:.4f}")
        print("  a difference of <=8-10pp is below the resolution of this set (docs/evaluation-method.md)")
        return 0

    cfg = load_config(args.config)
    rows = load_items(args.split)
    if not rows:
        print("no phrased items in that split")
        return 1
    hits = hits_for(rows, cfg)
    per_example = run(rows, cfg, hits)
    pre = preflight(rows, cfg, hits)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "per_example.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in per_example),
                    encoding="utf-8")

    print(f"config: method {cfg['retrieval']['method']}  "
          f"match_target {cfg['retrieval']['match_target']}  k {cfg['retrieval']['k']}  "
          f"chunking {cfg['retrieval'].get('chunking', 'none')}")
    print("DEMO DATA: a synthetic corpus and a synthetic eval set written by the same "
          "author. These numbers show that the method runs; they are not evidence "
          "about retrieval quality.")
    print()
    report(score(per_example), args.split, pre)
    print(f"\nper-example -> {path}")
    return 0


def read_rows(path):
    return [json.loads(l) for l in
            pathlib.Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


if __name__ == "__main__":
    sys.exit(main())
