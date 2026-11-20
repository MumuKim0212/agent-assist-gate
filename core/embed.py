"""Where the embedding vectors come from, and the only place document text leaves.

`retrieval.embedding_model` carries the provider, so the config value names the
seam rather than assuming one:

    embedding_model: null                        # bm25 -- no encoder at all
    embedding_model: google:gemini-embedding-001 # remote API
    embedding_model: local:<checkpoint>          # a sentence-transformers model

Three properties this shape is here to keep.

**The provider is swappable without a redesign.** Thresholds are quantiles of a
measured distribution, so changing model or provider costs a refit rather than a
redesign, and the eval set never has to be relabelled.

**The model is pinned, by the spec string.** A re-run on an unchanged index must
reproduce identical numbers. A provider that silently upgrades a model behind an
alias breaks that quietly, so anything remote names an explicit model version,
never a floating alias, and `fingerprint` is what a run records.

**Nothing un-scrubbed leaves the process.** A remote provider redacts the
**query** through `core.redact` before it goes out. It does not redact the
documents: a document's numbers can be the answer itself.
"""
import json
import os
import urllib.error
import urllib.request

from core import env as env_module
from core import redact

GOOGLE_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/"
                   "models/{model}:batchEmbedContents")
GOOGLE_KEY_ENV = "GOOGLE_API_KEY"
# The API's own query/document distinction. Asymmetric embedding: a question and
# the passage that answers it are not the same kind of text, and the provider
# wants to be told which is which.
TASK = {"query": "RETRIEVAL_QUERY", "document": "RETRIEVAL_DOCUMENT"}
BATCH = 100


def encoder(spec):
    """`spec` -> an encoder. None means the caller does not need one."""
    if not spec:
        return None
    provider, _, name = spec.partition(":")
    if not name:                      # bare checkpoint name = local
        provider, name = "local", provider
    if provider == "local":
        return LocalEncoder(name)
    if provider == "google":
        return GoogleEncoder(name)
    raise ValueError(f"unknown embedding provider {provider!r} in {spec!r} -- "
                     "expected 'local:<checkpoint>' or 'google:<model>'")


class LocalEncoder:
    """A `sentence-transformers` checkpoint on this machine. Nothing leaves."""

    remote = False

    def __init__(self, name):
        from sentence_transformers import SentenceTransformer

        self.name = name
        self.fingerprint = f"local:{name}"
        self.model = SentenceTransformer(name)

    def encode(self, texts, kind="document"):
        return self.model.encode(list(texts), normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False)


class RemoteEncoder:
    """Shared behaviour for anything that sends text off this machine.

    Subclasses implement `_post`. This class owns the part that must not be
    re-decided per provider: a query is scrubbed before it goes out, documents
    are not, and the counts are kept so a run can show redaction was live.
    """

    remote = True

    def __init__(self, name):
        self.name = name
        self.scrubbed = 0
        self.kinds = {}

    def prepare(self, texts, kind):
        if kind != "query":
            return list(texts)
        out = []
        for text in texts:
            cleaned, fired = redact.scrub(text)
            if fired:
                self.scrubbed += 1
                for k in fired:
                    self.kinds[k] = self.kinds.get(k, 0) + 1
            out.append(cleaned)
        return out

    def encode(self, texts, kind="document"):
        import numpy

        if kind not in TASK:
            raise ValueError(f"kind must be one of {sorted(TASK)}, not {kind!r}")
        prepared = self.prepare(texts, kind)
        vectors = []
        for start in range(0, len(prepared), BATCH):
            vectors.extend(self._post(prepared[start:start + BATCH], kind))
        matrix = numpy.asarray(vectors, dtype="float32")
        norms = numpy.linalg.norm(matrix, axis=1, keepdims=True)
        # Normalise here rather than trusting the provider to: cosine is what
        # `thresholds` are expressed on, and a provider that returns unnormalised
        # vectors would put the gate on a different scale without saying so.
        return matrix / numpy.where(norms == 0, 1, norms)


class GoogleEncoder(RemoteEncoder):
    """Google Generative Language API, over the standard library.

    No SDK on purpose: the one call this needs is a POST of JSON, and an SDK
    would put a dependency with its own release cadence on the serving path.

    The key comes from the `GOOGLE_API_KEY` environment variable and is never
    read from `config.yaml`: config is committed and a key must not be. A
    gitignored `.env` at the repo root is read into the environment on first use
    (`core/env.py`); an already-exported variable wins over it.
    """

    def __init__(self, name, key=None, transport=None):
        super().__init__(name)
        self.fingerprint = f"google:{name}"
        if key is None:
            env_module.load()          # a gitignored .env, if there is one
        self.key = key if key is not None else os.environ.get(GOOGLE_KEY_ENV)
        self.transport = transport or self._https

    def _https(self, url, payload):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(
                f"{self.fingerprint} returned HTTP {error.code}: {detail}") from error

    def _post(self, texts, kind):
        if not self.key:
            raise RuntimeError(
                f"{GOOGLE_KEY_ENV} is not set, so {self.fingerprint} cannot encode. "
                "Set it in the environment; it does not belong in config.yaml.")
        model = f"models/{self.name}"
        payload = {"requests": [
            {"model": model, "content": {"parts": [{"text": text}]},
             "taskType": TASK[kind]}
            for text in texts]}
        url = GOOGLE_ENDPOINT.format(model=self.name) + f"?key={self.key}"
        body = self.transport(url, payload)
        embeddings = body.get("embeddings")
        if embeddings is None or len(embeddings) != len(texts):
            raise RuntimeError(
                f"{self.fingerprint} returned {len(embeddings or [])} vectors for "
                f"{len(texts)} texts -- the response shape is not what this expects")
        return [e["values"] for e in embeddings]
