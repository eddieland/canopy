"""What a memory's text may hold, and how it is shown (DESIGN §28, Bounds); a draft's is held to the same (§29).

A note or a proposal is worker text that may reach later prompts, so it is checked in code when it is written, never
cut or cleaned: a refused entry is stored nowhere, and why is recorded with its run. A key is a slug. A text is plain
text, its lines broken by line feeds, without the characters that hide text from a person who reads it (control, format,
and separator characters, zero-width, bidi, and tag characters among them), and without anything that looks like a
secret.

What the journal holds may still have been written past these checks, by hand, so every surface shows a memory's text
through `visible` or `quoted`, with each such character named.
"""

from __future__ import annotations

import itertools
import math
import re
import unicodedata
from collections import Counter

# A key: lowercase words joined by single hyphens, at most 40 characters, as a branch's slug is (DESIGN §8).
KEY_RE = re.compile(r"(?=[a-z0-9-]{1,40}\Z)[a-z0-9]+(?:-[a-z0-9]+)*")
# Unicode's control, format, surrogate, private-use, unassigned, and line and paragraph separator categories. Format
# takes in the zero-width characters, the bidi controls, and the tag characters, each a way to hide text from a person
# that a model still reads.
HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# Known shapes of credentials: a private key, cloud and VCS tokens, chat and model API keys, a JWT, a bearer header,
# and a password or key assigned a value that is not a placeholder (`$VAR`, `<token>`, `{secret}`).
_SECRET_RES = tuple(
    re.compile(pattern)
    for pattern in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY",
        r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        r"\bgh[pousr]_[A-Za-z0-9]{30,}",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}",
        r"\bglpat-[A-Za-z0-9_-]{20,}",
        r"\bxox[abposr]-[A-Za-z0-9-]{10,}",
        r"\bxapp-[A-Za-z0-9-]{10,}",
        r"\bsk-[A-Za-z0-9_-]{20,}",
        r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}",
        r"\bAIza[0-9A-Za-z_-]{35}",
        r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}",
        r"(?i)\b(?:password|passwd|api[_-]?key|secret|token|access[_-]?key)\s*[:=]\s*(?![$<{])\S{6,}",
    )
)
# A word that may be a random token: at least 20 characters of a base64 or URL-safe alphabet.
_WORD_RE = re.compile(r"[A-Za-z0-9+/=_-]{20,}")
_HEX_RE = re.compile(r"[0-9a-fA-F]+")
# How often a random token changes between upper case, lower case, and digits from one character to the next, and how
# varied its characters are: identifiers in CamelCase change about once a word, and repeat their letters.
_MIN_CLASS_CHANGES = 0.45
_MIN_ENTROPY_BITS = 3.5


class TextRefused(ValueError):  # noqa: N818  (an outcome recorded with the run, not an error)
    """A memory's key or text is not one canopy stores. Its message is the harness's words, never the text."""


def check_key(value: object) -> str:
    """Return a memory's key, refusing one that is not a slug.

    Returns:
        The key as given.

    Raises:
        TextRefused: The key is not a string of lowercase words joined by hyphens, at most 40 characters.
    """
    if not isinstance(value, str) or KEY_RE.fullmatch(value) is None:
        raise TextRefused("its key is not lowercase words joined by hyphens, at most 40 characters")
    return value


def check_text(value: object, limit: int) -> str:
    """Return a memory's text, trimmed, refusing what canopy never stores (DESIGN §28, Bounds).

    Line feeds and tabs are allowed: a memory may break its lines, and a draft's reply (DESIGN §29) may hold paragraphs
    and code. Every other character `hidden_char` names is refused.

    Returns:
        The text without surrounding spaces.

    Raises:
        TextRefused: The text is not a string, is blank or over `limit` characters, holds a hidden character, or
            looks like a secret.
    """
    if not isinstance(value, str):
        raise TextRefused("its text is not a string")
    text = value.strip()
    if not text:
        raise TextRefused("its text is blank")
    if len(text) > limit:
        raise TextRefused(f"its text is {len(text)} characters, over {limit}")
    hidden = next((c for c in text if hidden_char(c) and c not in "\n\t"), None)
    if hidden is not None:
        raise TextRefused(f"its text holds {_name(hidden)}, a character that hides text")
    if looks_secret(text):
        raise TextRefused("its text looks like it holds a secret")
    return text


def hidden_char(c: str) -> bool:
    """Whether `c` is a character a memory's text may not hold: one of `HIDDEN_CATEGORIES`.

    Returns:
        True for a control, format, surrogate, private-use, unassigned, or line or paragraph separator character.
    """
    return unicodedata.category(c) in HIDDEN_CATEGORIES


def looks_secret(text: str) -> bool:
    """Whether `text` holds a known credential's shape, or a word that looks like a random token.

    A random token is a word of at least 20 characters mixing upper case, lower case, and digits, that changes between
    them often and repeats few characters. Hexadecimal words, such as commit ids, are never taken for one: notes name
    commits.

    Returns:
        True if any pattern matches, or any word looks random.
    """
    if any(r.search(text) for r in _SECRET_RES):
        return True
    return any(_random(word) for word in _WORD_RE.findall(text))


def normalized(text: str) -> str:
    """Return `text` as two memories are compared for a repeat: casefolded, its whitespace collapsed."""
    return " ".join(text.casefold().split())


def visible(text: str) -> str:
    """Return `text` with every hidden character named, `<U+200B>`, so a person sees all a model would read.

    Returns:
        `text`, each character of `HIDDEN_CATEGORIES` replaced by its code point in angle brackets.
    """
    return "".join(f"<U+{ord(c):04X}>" if hidden_char(c) else c for c in text)


def quoted(text: str, prefix: str) -> str:
    """Return `text` with `prefix` before each of its lines, its tabs kept, every other hidden character named.

    Line feeds and tabs are what `check_text` lets a text hold, so they show as written, as the web UI shows them.

    Returns:
        Each line of `text`, split at its line feeds alone, after `prefix`, each run between tabs through `visible`.
    """
    return "\n".join(prefix + "\t".join(map(visible, line.split("\t"))) for line in text.split("\n"))


def _random(word: str) -> bool:
    if _HEX_RE.fullmatch(word):
        return False
    if not (any(c.isupper() for c in word) and any(c.islower() for c in word) and any(c.isdigit() for c in word)):
        return False
    letters = [c for c in word if c.isalnum()]
    changes = sum(_char_class(a) != _char_class(b) for a, b in itertools.pairwise(letters))
    return changes / max(1, len(letters) - 1) >= _MIN_CLASS_CHANGES and _entropy(word) >= _MIN_ENTROPY_BITS


def _char_class(c: str) -> int:
    return 0 if c.isupper() else 1 if c.islower() else 2


def _entropy(word: str) -> float:
    # Shannon entropy in bits a character.
    n = len(word)
    return -sum(k / n * math.log2(k / n) for k in Counter(word).values())


def _name(c: str) -> str:
    try:
        return f"U+{ord(c):04X} ({unicodedata.name(c)})"
    except ValueError:
        return f"U+{ord(c):04X}"
