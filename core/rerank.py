"""LLM rerank of a first-stage pool.

One call per query: the model sees the question and a numbered pool of
documents, and returns the numbers of the ones that answer it, best first.
Nothing it writes is shown to anyone -- the product still generates no answer
text, it only reorders documents that already exist.

### Three properties

**A failed call is not a ranking.** A transport error is counted and reported as
status `error`, never silently replaced by the pool order. An evaluation should
refuse a run that has any, because most of what it measured would then be the
unreranked pool. An unparseable reply or an out-of-range number is counted too;
the pool order fills only the places the reply left empty.

**Verdicts are cached** per (model, prompt, query, pool ids and content hashes),
because generative models at temperature 0 still do not reproduce across fresh
calls.

**The query is scrubbed; the documents are not** (`core/redact.py`).
"""
import collections
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from core import env as env_module
from core import index, redact

GOOGLE_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/"
                   "models/{model}:generateContent")
GOOGLE_KEY_ENV = "GOOGLE_API_KEY"
PROMPT_VERSION = "v1"
PICK = 5

Ranking = collections.namedtuple("Ranking", "order status raw ms")

# The instructions are frozen before any item is reranked; a new wording is v2.
INSTRUCTIONS = """당신은 민원센터 상담원을 돕는 검색 보조자다.
[질문]에 답하는 데 필요한 문서를 [후보] 중에서 고른다. 답을 쓰지는 않는다.

- 질문에 실제로 답하는 문서를 고른다. 같은 주제인지는 기준이 아니다.
- 질문과 낱말만 겹칠 뿐 다른 대상, 다른 자격·등급, 다른 절차 단계를 다루는 문서는 뒤로 보낸다.
- 질문이 여러 가지를 물으면 각 부분에 답하는 문서가 빠지지 않게 고른다.
- 같은 내용을 반복하는 후보는 하나만 앞에 둔다.

가장 필요한 순서대로 후보 번호 {k}개를 고른다. 출력은 아래 JSON 하나만 쓴다.
{{"ranked": [후보 번호 {k}개]}}"""


def content_hash(doc):
    return hashlib.sha256(index.body(doc).encode("utf-8")).hexdigest()[:16]


def render(pool):
    """The numbered pool the model reads: stored question, then body."""
    blocks = []
    for n, doc in enumerate(pool, 1):
        question = doc.get("question", "").strip()
        text = index.body(doc).strip() or "(본문 없음)"
        blocks.append(f"[{n}]\n" + (f"질문: {question}\n답변: {text}" if question else text))
    return "\n\n".join(blocks)


def parse(text, n, k=PICK):
    """(0-based pool order, status). Valid unique numbers in reply order, then
    the pool order for whatever is left. Status is 'ok', 'partial' (some
    numbers missing or invalid) or 'unparsed' (no list at all)."""
    numbers = None
    match = re.search(r"\{.*\}", text or "", re.S)
    if match:
        try:
            numbers = json.loads(match.group()).get("ranked")
        except (ValueError, AttributeError):
            numbers = None
    if not isinstance(numbers, list):
        return list(range(n)), "unparsed"
    picked = []
    for x in numbers:
        if isinstance(x, int) and 1 <= x <= n and x - 1 not in picked:
            picked.append(x - 1)
    status = "ok" if len(picked) >= min(k, n) else "partial"
    return picked + [i for i in range(n) if i not in picked], status


class GoogleRerank:
    """Gemini over the standard library, temperature 0, JSON out."""

    def __init__(self, model, key=None, transport=None, timeout=20, cache=None):
        self.model = model
        self.fingerprint = f"google:{model}#rerank-{PROMPT_VERSION}"
        if key is None:
            env_module.load()
        self.key = key if key is not None else os.environ.get(GOOGLE_KEY_ENV)
        self.transport = transport or self._https
        self.timeout = timeout
        self.cache = cache if cache is not None else {}
        self.counts = collections.Counter()

    def _https(self, url, payload):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def key_for(self, query, pool):
        ids = "|".join(f"{d['id']}:{content_hash(d)}" for d in pool)
        return hashlib.sha256(f"{self.fingerprint}\n{query}\n{ids}".encode("utf-8")).hexdigest()

    def payload(self, query, pool):
        question, _ = redact.scrub(query)
        return {
            "systemInstruction": {"parts": [{"text": INSTRUCTIONS.format(k=min(PICK, len(pool)))}]},
            "contents": [{"role": "user", "parts": [
                {"text": f"[질문]\n{question}\n\n[후보]\n{render(pool)}"}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 256,
                                 "responseMimeType": "application/json"},
        }

    def rank(self, query, pool):
        """A Ranking of the pool. Cached rankings keep the latency of the call
        that produced them; status 'error' means no call succeeded."""
        cache_key = self.key_for(query, pool)
        if cache_key in self.cache:
            hit = self.cache[cache_key]
            self.counts["cached"] += 1
            return Ranking(hit["order"], hit["status"], hit["raw"], hit["ms"])
        if not self.key:
            raise RuntimeError(f"{GOOGLE_KEY_ENV} is not set, so {self.fingerprint} "
                               "cannot rerank. It does not belong in config.yaml.")
        url = GOOGLE_ENDPOINT.format(model=self.model) + f"?key={self.key}"
        started = time.perf_counter()
        try:
            body = self.transport(url, self.payload(query, pool))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            self.counts["error"] += 1
            return Ranking(list(range(len(pool))), "error", type(error).__name__,
                           (time.perf_counter() - started) * 1000)
        ms = (time.perf_counter() - started) * 1000
        candidate = (body.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in
                       candidate.get("content", {}).get("parts", []))
        order, status = parse(text, len(pool))
        self.counts[status] += 1
        self.cache[cache_key] = {"order": order, "status": status, "raw": text.strip()[:80],
                                 "ms": round(ms, 1)}
        return Ranking(order, status, text.strip()[:80], ms)
