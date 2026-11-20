"""Read `.env` into the environment, so a key never has to live in the repo.

`core/embed.py` takes `GOOGLE_API_KEY` from the environment and refuses to take
it from `config.yaml`: config is committed, a credential must not be. A `.env`
beside the repo root -- gitignored, read here, never written -- is how the key
reaches the environment on a machine where nobody exports it by hand.

Deliberately not `python-dotenv`: this is twenty lines, and a credential path is
the last place to add a transitive dependency tree.

**An existing environment variable always wins.** A `.env` is a convenience for
a workstation; an exported variable is what a scheduled run will use, and a
loader that overrode it would make the two disagree silently.
"""
import os
import pathlib

PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"
_loaded = False


def parse(text):
    """`KEY=value` per line. `#` comments and blank lines ignored.

    Quotes are stripped because a key pasted out of a console often arrives
    wrapped in them, and a quoted key fails authentication in a way whose error
    message does not mention quotes.
    """
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load(path=None, environ=None, force=False):
    """Load once per process. Returns the names loaded, never the values."""
    global _loaded
    if _loaded and not force:
        return ()
    path = pathlib.Path(path) if path else PATH
    environ = os.environ if environ is None else environ
    _loaded = True
    if not path.exists():
        return ()
    loaded = []
    for key, value in parse(path.read_text(encoding="utf-8")).items():
        if key not in environ:
            environ[key] = value
            loaded.append(key)
    return tuple(loaded)
