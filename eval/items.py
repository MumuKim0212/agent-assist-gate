"""Where the eval set lives.

The manifest (`eval/manifest.jsonl`) carries each item's id, bucket, stratum,
split and gold ids -- and, in this demo, its question text (`phrasing`). In a
deployment where the questions are personal or confidential data, the manifest
is committed without text and the questions sit in `knowledge/eval_items.jsonl`
out of tree; `phrasing()` is the seam that joins them.
"""
import json

from core import index

MANIFEST = index.ROOT / "eval" / "manifest.jsonl"
ITEMS = index.ROOT / "knowledge" / "eval_items.jsonl"


def phrasing():
    """{item_id: question text} from the out-of-tree items file, if there is one."""
    if not ITEMS.exists():
        return {}
    out = {}
    for line in ITEMS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["item_id"]] = row.get("phrasing") or row.get("question", "")
    return out
