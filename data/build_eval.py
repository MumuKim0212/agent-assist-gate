"""Writes eval/manifest.jsonl -- the demo's SYNTHETIC eval set (52 items).

Written ONCE, against the corpus in build_corpus.py, before any retrieval result
was looked at, and not edited afterwards. Do not tune it to move a number: the
author of these questions also wrote the documents they are answered from, which
is exactly the situation in which a score is flattering. Treat every figure the
scorer prints on this set as a demonstration that the method runs, never as
evidence that the system is good.

Buckets (the scorer's vocabulary):

  answerable   one or more gold documents answer it     (general / contrastive)
  no-answer    nothing in the corpus answers it          (near-miss / far)
  ambiguous    the answer depends on a condition the caller did not state;
               gold is the competing set                 (caller-condition / attribute-omitted)

Split: tune 40% / holdout 60%. Within each bucket the units are ordered by a hash
of their id and the first 40% go to tune, so every bucket has tune items. A unit
is a contrastive pair (both members stay together) or a single item. The split is
a function of the ids alone, never of any score.

    python data/build_eval.py      # -> eval/manifest.jsonl
"""
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "manifest.jsonl"
DOCS = ROOT / "knowledge" / "docs.jsonl"
TUNE_SHARE = 40  # percent

C = "faq:카드발급:Q"
E = "faq:교육신청:Q"
M = "faq:회원:Q"
D = "faq:증명서:Q"

# (stratum, query, gold ids, pair id)
ANSWERABLE = [
    ("general", "사진 파일은 어떤 크기로 올려야 하나요", [C + "10"], None),
    ("general", "카드 신청하고 며칠 뒤에 받을 수 있어요?", [C + "11"], None),
    ("general", "카드를 집으로 보내주시나요, 아니면 직접 가야 하나요", [C + "12"], None),
    ("general", "카드 만료되기 전에 뭘 해야 하는지 궁금합니다", [C + "9"], None),
    ("general", "교육 신청하고 결제 전인데 취소하고 싶어요", [E + "4"], None),
    ("general", "개강 이틀 전인데 환불이 되나요", [E + "5"], None),
    ("general", "가상계좌로 입금 안 하면 어떻게 되나요", [E + "6"], None),
    ("general", "교육 끝나고 수료증은 언제부터 뽑을 수 있나요", [E + "10"], None),
    ("general", "교육 중에 이틀 연속 못 갔는데 수료에 문제 없나요", [E + "11"], None),
    ("general", "온라인 강의 최종평가에서 떨어졌어요", [E + "8"], None),
    ("general", "아이디를 까먹었어요 어떻게 찾죠", [D + "4"], None),
    ("general", "영문으로 된 수료 증명서가 필요한데요", [D + "2"], None),
    ("general", "경력증명서 뽑는 데 돈이 드나요", [D + "1"], None),
    ("general", "저희 회사 대표가 바뀌었는데 어디에 알려야 하나요", [M + "2"], None),
    ("general", "회원사 전용으로 회원증명서를 뽑고 싶습니다", [M + "5"], None),
    ("general", "승급교육 들으면 바로 등급이 올라가나요", ["faq:승급교육:Q1", "faq:승급교육:Q3"], None),
    ("general", "교육장에 차를 가져가도 되나요", [E + "13"], None),
    ("general", "다음 달 교육 일정은 어디서 보나요", [E + "12", "manual:교육 일정 안내"], None),
    ("general", "휠체어를 쓰는데 교육을 들을 수 있을까요", [E + "16"], None),
    ("general", "카드 발급이 취소되는 경우도 있나요", ["faq:자격관리:Q1"], None),
    ("general", "교재는 따로 사야 하나요", [E + "14"], None),
    # contrastive: two documents on the same topic that differ in one attribute.
    # A pair counts only if BOTH members retrieve their own gold.
    ("contrastive", "비회원사 직원인데 교육이수카드를 처음 만들려면 뭐가 필요해요", [C + "2"], "pair:신규발급-대상"),
    ("contrastive", "저희 회사는 회원사인데 카드를 신규로 만들려고 합니다", [C + "1"], "pair:신규발급-대상"),
    ("contrastive", "초급은 이수했고 중급 교육을 접수하려는데 자격 조건이 있나요", [E + "2"], "pair:교육신청-등급"),
    ("contrastive", "고급 교육을 신청하려면 어떤 조건이 필요한지 궁금합니다", [E + "3"], "pair:교육신청-등급"),
    ("contrastive", "카드를 잃어버렸어요", [C + "7"], "pair:재발급-사유"),
    ("contrastive", "카드가 찢어졌는데 새로 받을 수 있나요", [C + "8"], "pair:재발급-사유"),
    ("contrastive", "고급에서 특급으로 올라가려면 심사를 받아야 하나요", [C + "6"], "pair:등급변경-등급"),
    ("contrastive", "중급에서 고급으로 올리려는데 경력이 몇 년 필요한가요", [C + "5"], "pair:등급변경-등급"),
]

NO_ANSWER = [
    # near-miss: a neighbouring document exists, the answer does not
    ("near-miss", "연회비 금액이 얼마인가요"),
    ("near-miss", "교육비를 나눠서 낼 수 있나요"),
    ("near-miss", "교육이수카드 유효기간을 연장 신청할 수 있나요"),
    ("near-miss", "수료증을 팩스로 받을 수 있나요"),
    ("near-miss", "등급을 낮추는 강등 신청도 가능한가요"),
    ("near-miss", "영문 경력증명서도 발급되나요"),
    ("near-miss", "특급 심사에서 떨어지면 재심사 수수료는 얼마인가요"),
    ("near-miss", "해외에서도 온라인 교육을 들을 수 있나요"),
    ("near-miss", "폐업했던 회원사가 다시 가입할 때 절차가 다른가요"),
    ("near-miss", "승급교육 수강료가 얼마인가요"),
    ("near-miss", "회비 감면을 받을 수 있는 조건이 있나요"),
    # far: nothing to do with the domain
    ("far", "오늘 점심 메뉴 추천해 주세요"),
    ("far", "내일 서울 날씨가 어떤가요"),
    ("far", "삼성전자 주가 좀 알려주세요"),
    ("far", "병원 예약은 어떻게 하나요"),
]

# gold = the competing set the caller has to choose between
AMBIGUOUS = [
    ("attribute-omitted", "교육이수카드를 처음 발급받고 싶어요", [C + "1", C + "2", C + "3"]),
    ("attribute-omitted", "카드 등급을 올리고 싶은데요", [C + "4", C + "5", C + "6"]),
    ("caller-condition", "교육을 신청하려고 하는데요", [E + "1", E + "2", E + "3"]),
    ("caller-condition", "카드 재발급을 받으려고요", [C + "7", C + "8"]),
    ("caller-condition", "회원사 정보를 신고하려고 하는데요", [M + "2", M + "3"]),
    ("caller-condition", "교육비가 얼마인가요", [E + "1", E + "2", E + "3"]),
    ("caller-condition", "카드 발급 수수료가 궁금합니다", [C + "1", C + "2", C + "3"]),
    ("caller-condition", "회원 가입은 어떻게 하나요", [M + "1", M + "7"]),
]


def digest(item_id):
    return hashlib.sha256(item_id.encode("utf-8")).hexdigest()


def assign_splits(rows):
    """Split v2: the unit is the pair when an item has a pair id, otherwise the
    item. v1 split by item and put the two members of three contrastive pairs on
    different sides, so the pair metric was unreadable on the holdout (0 whole
    pairs)."""
    for bucket in {r["bucket"] for r in rows}:
        units = {}
        for r in rows:
            if r["bucket"] == bucket:
                units.setdefault(r["pair_id"] or r["item_id"], []).append(r)
        ordered = sorted(units, key=digest)
        cut = round(len(ordered) * TUNE_SHARE / 100)
        for n, unit in enumerate(ordered):
            for r in units[unit]:
                r["split"] = "tune" if n < cut else "holdout"


def build():
    docs = {json.loads(l)["id"]: json.loads(l) for l in DOCS.read_text(encoding="utf-8").splitlines()
            if l.strip()}
    rows = []

    def add(bucket, stratum, number, query, gold, pair=None):
        for g in gold:
            assert g in docs, f"gold id {g!r} is not in the corpus"
        item_id = f"{stratum}:{number:03d}"
        rows.append({
            "item_id": item_id, "bucket": bucket, "stratum": stratum,
            "split": None, "pair_id": pair, "gold_ids": gold,
            "gold_needs_review": any(docs[g]["status"] == "needs_review" for g in gold),
            "phrasing_source": "authored", "phrasing": query,
        })

    counts = {}

    def number(stratum):
        counts[stratum] = counts.get(stratum, 0) + 1
        return counts[stratum]

    for stratum, query, gold, pair in ANSWERABLE:
        add("answerable", stratum, number(stratum), query, gold, pair)
    for stratum, query in NO_ANSWER:
        add("no-answer", stratum, number(stratum), query, [])
    for stratum, query, gold in AMBIGUOUS:
        add("ambiguous", stratum, number(stratum), query, gold)
    assign_splits(rows)
    return rows


def main():
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                   encoding="utf-8")
    by = {}
    for r in rows:
        by.setdefault((r["bucket"], r["split"]), 0)
        by[(r["bucket"], r["split"])] += 1
    print(f"{len(rows)} items -> {OUT}")
    for key in sorted(by):
        print(f"  {key[0]:<11} {key[1]:<8} {by[key]}")


if __name__ == "__main__":
    main()
