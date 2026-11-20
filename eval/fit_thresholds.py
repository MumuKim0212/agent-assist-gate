"""Fit the gate's three cut points from the TUNE split, by a rule fixed in advance.

    python -m eval.fit_thresholds                  # print the fit
    python -m eval.fit_thresholds --write          # ... and write it into config.yaml
    python -m eval.fit_thresholds --config x.yaml  # fit another retrieval configuration

The rule (per bucket, never pooled -- a pooled quantile improves by adding easy
items, which is the wrong incentive):

    top1_low   = the 5th percentile of top-1 score over ANSWERABLE tune items.
                 Below it the gate refuses; at most ~5% of answerable questions
                 are given up (the acceptable error).
    top1_high  = the 95th percentile of top-1 score over NEAR-MISS tune items.
                 At or above it the gate answers; at most ~5% of near-miss
                 questions get through (the critical error).
    margin     = the 75th percentile of (top1 - top2) over AMBIGUOUS tune items.
                 Documents within `margin` of the top compete, and if they differ
                 in 등급 / 대상 / 행위 the gate asks instead of answering.

Between top1_low and top1_high is the gray zone. With no evidence check built,
the gate refuses there (an acceptable error), so a wide gray zone costs coverage.
That overlap -- answerable and near-miss questions scoring alike -- is the
central difficulty of this kind of gate, and it shows even on a toy corpus.

Only the tune split is read. The holdout is for `python -m eval.score`, once.
"""
import argparse
import pathlib
import re
import sys

import yaml

from eval import score


def quantile(values, q):
    """Linear-interpolated quantile, q in [0, 1]. No numpy."""
    xs = sorted(values)
    if not xs:
        raise ValueError("no values to take a quantile of")
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def fit(rows, hits):
    answerable = [hits[r["item_id"]] for r in rows if r["bucket"] == "answerable"]
    near_miss = [hits[r["item_id"]] for r in rows if r["stratum"] == "near-miss"]
    ambiguous = [hits[r["item_id"]] for r in rows if r["bucket"] == "ambiguous"]

    def top1(group):
        return [h[0].score for h in group if h]

    def margin(group):
        return [h[0].score - h[1].score for h in group if len(h) > 1]

    low = quantile(top1(answerable), 0.05)
    high = quantile(top1(near_miss), 0.95)
    gap = quantile(margin(ambiguous), 0.75)
    return {"top1_low": round(low, 4), "top1_high": round(high, 4), "margin": round(gap, 4),
            "n": {"answerable": len(answerable), "near-miss": len(near_miss),
                  "ambiguous": len(ambiguous)}}


def gray_share(rows, hits, low, high):
    scores = [hits[r["item_id"]][0].score for r in rows if hits[r["item_id"]]]
    return sum(1 for s in scores if low <= s < high) / len(scores) if scores else 0.0


def write(path, fitted):
    text = path.read_text(encoding="utf-8")
    for key in ("top1_high", "top1_low", "margin"):
        text, n = re.subn(rf"^(\s+{key}:\s*)[-0-9.eE+]+", rf"\g<1>{fitted[key]}", text,
                          count=1, flags=re.M)
        if n != 1:
            raise RuntimeError(f"could not find `{key}:` in {path}")
    path.write_text(text, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", help="a config.yaml to fit (default: core/config.yaml)")
    parser.add_argument("--write", action="store_true", help="write the fit into that config")
    args = parser.parse_args(argv)

    path = pathlib.Path(args.config) if args.config else \
        pathlib.Path(__file__).resolve().parent.parent / "core" / "config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = score.load_items("tune")
    hits = score.hits_for(rows, cfg)
    fitted = fit(rows, hits)

    n = fitted["n"]
    print(f"fit on the TUNE split: {n['answerable']} answerable, {n['near-miss']} near-miss, "
          f"{n['ambiguous']} ambiguous items")
    print(f"  top1_low  {fitted['top1_low']}")
    print(f"  top1_high {fitted['top1_high']}")
    print(f"  margin    {fitted['margin']}")
    if fitted["top1_low"] > fitted["top1_high"]:
        print("  note: top1_low > top1_high -- the answerable and near-miss distributions do "
              "not overlap on this sample, so there is no gray zone")
    share = gray_share(rows, hits, fitted["top1_low"], fitted["top1_high"])
    print(f"  gray-zone share of tune items: {100 * share:.1f}%  "
          f"(cap {100 * cfg['targets']['gray_zone_share_cap']:.0f}%)")
    if args.write:
        write(path, fitted)
        print(f"written -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
