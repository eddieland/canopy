"""The outline of a repository's code a run's prompt starts with: a directory tree (DESIGN §46, ROADMAP M70 stage 1).

An agent starts a run knowing nothing of its repository but where it is. The outline is the tree git holds for it, from
`git ls-tree -r` and nothing else: no parser, no index, and no read of a working tree a run can write. The directories
the work is about are opened to their files, and the rest collapsed to a name and a count of the files under it,
outermost first, until the bound is reached; the outline says how many files it does not list.

What the work is about is found by words, matched against the words of each path's components and used only to rank,
never rendered: the ticket's, or the paths a branch already changed. With neither, or when none matches, the tree is
opened by size alone.

A path is the repository's text, which a contributor wrote (TRUST_MODEL T1): each is bounded, one that holds a
character that hides text is dropped, never rendered, and every line of the tree is quoted, so none passes for the
prompt's own.
"""

from __future__ import annotations

import heapq
import math
import posixpath
import re
from collections import Counter
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import git_tools, hostgit, path_patterns
from canopy.core.memory_text import hidden_char, visible
from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

#: The longest path an outline holds; a longer one is dropped, as one with a hidden character is.
MAX_PATH = 200
#: How many of an opened directory's own files are listed by name; the rest are counted.
MAX_FILES_SHOWN = 40
#: How many of the directories the work's words rank are tried, best first.
MAX_SEEDS = 200
#: How much of a text `words` reads: a ticket's body can be a pasted log.
MAX_TEXT = 20_000
#: The shortest word that ranks: shorter ones match too many names to tell a directory from another.
MIN_WORD = 3
#: How many characters of git's listing are read; a tree past it is outlined from what was read, and says so.
MAX_LISTING = 50_000_000
#: How long one git command may take.
TIMEOUT_SECONDS = 30
#: How many directories the fill may try to open once the work's own are, and how many in a row may not fit.
_MAX_FILL = 2000
_MAX_MISSES = 50
_INDENT = "  "
_QUOTE = "> "
# The words of a name or a text: a run of capitals, a word that may start with one, or a number, so camelCase and
# snake_case both split, and `HTTPServer` is `http` and `server`.
_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


# Words too common in a ticket's prose to say what it is about, which a file named for a sentence would still match.
_COMMON = frozenset(
    re.findall(
        r"[a-z]+",
        "about add added adds after all also and any are been before between but can could did does done each every "
        "for from get had has have her here his how into its just like make makes may more most must need needs new "
        "not now one only other our out over per see set should some still such than that the their them then there "
        "they this two under use used uses using via want wants was were what when where which while who why will "
        "with within without would you your",
    ),
)


class Unlisted(Exception):  # noqa: N818  (an outcome the run goes on without, not an error)
    """git could not list a tree. Its message is the harness's words and git's first line, hidden characters named."""


@dataclass(frozen=True)
class About:
    """What a run's work is about, which ranks the directories its outline opens and is rendered nowhere."""

    #: The words of the ticket or the task, as `words` splits them.
    words: AbstractSet[str] = frozenset()
    #: The paths the work already changed, from the repository's root; where there are any, they rank alone.
    changed: AbstractSet[str] = frozenset()


@dataclass(frozen=True)
class Listing:
    """The files of a tree, as git lists them."""

    #: Each file's path from the repository's root.
    paths: Sequence[str]
    #: Whether the listing went past `MAX_LISTING`, so `paths` is its start alone.
    cut: bool = False


def render(listing: Listing, about: About, *, bound: int, exclude: Collection[str] = ()) -> str | None:
    """Return the tree of `listing` as an outline of at most `bound` characters, opened where `about` says.

    Args:
        listing: The tree's files.
        about: What ranks the directories opened first.
        bound: The most characters the outline is, its last line included.
        exclude: Paths and patterns, as `path_patterns.covers` reads them, whose files the outline leaves out and
            does not count.

    Returns:
        The tree, each line quoted, then a line of the harness's own counting its files; None for a tree with no file
        to show.
    """
    patterns = [entry.removesuffix("/").split("/") for entry in exclude]
    root = _Dir("", None)
    index = {"": root}
    dropped = 0
    for path in listing.paths:
        parts = path.split("/")
        if any(path_patterns.covers(pattern, parts) for pattern in patterns):
            continue
        if not _shown(path):
            dropped += 1
            continue
        _add(root, index, parts)
    if not root.total:
        return None
    # The last line is longest when it names no file, and a blank line parts it from the tree.
    room = len(_footer(root.total, 0, dropped, cut=listing.cut)) + 1
    shown = _Shown(root, about, budget=max(bound - room, 0))
    for seed in _seeds(index, about)[:MAX_SEEDS]:
        shown.open(seed)
    shown.fill()
    lines, named = shown.lines()
    return "\n".join((*(_QUOTE + line for line in lines), "", _footer(root.total, named, dropped, cut=listing.cut)))


def words(text: str) -> frozenset[str]:
    """Return the words of `text` that can rank a path: split as identifiers are, lowercased, the short ones left out.

    A word is a run of letters or of digits; `invoiceRenderer`, `invoice_renderer`, and `invoice-renderer.py` each hold
    `invoice` and `renderer`, and a plain plural is its singular, so `desks` names `desk.py`.

    Returns:
        The distinct words of the first `MAX_TEXT` characters, each at least `MIN_WORD` long, not a number, and not
        one of the commonest words of English prose.
    """
    found = (_normal(w) for w in _WORD_RE.findall(text[:MAX_TEXT]))
    return frozenset(w for w in found if len(w) >= MIN_WORD and not w.isdigit() and w not in _COMMON)


def listed(runner: procs.Runner, where: Path, ref: str) -> Listing:
    """Return the files of the tree `ref` names in the checkout `where`, from git's objects, never its working tree.

    Returns:
        Every file's path, a submodule's as the one path it is.

    Raises:
        Unlisted: git could not run, timed out, failed, as on a ref it does not hold, or printed a path that is not
            UTF-8.
    """
    out = _git(runner, where, "ls-tree", "-r", "-z", "--name-only", "--full-tree", ref, max_stdout=MAX_LISTING)
    cut = len(out) >= MAX_LISTING
    paths = out.split("\0")
    # The last piece is empty after the final NUL, or, of a listing cut short, the start of a path.
    return Listing(tuple(paths[:-1]), cut=cut)


def changed(runner: procs.Runner, where: Path, base: str, head: str) -> frozenset[str]:
    """Return the paths `head` changed since it left `base`, in the checkout `where`.

    Returns:
        Each path from the repository's root, a renamed file's as both its names.

    Raises:
        Unlisted: As `listed` raises it.
    """
    out = _git(runner, where, "diff", "--name-only", "-z", "--no-renames", f"{base}...{head}", max_stdout=MAX_LISTING)
    return frozenset(path for path in out.split("\0") if path)


def holds(runner: procs.Runner, where: Path, ref: str) -> bool:
    """Whether the checkout `where` holds the commit `ref` names.

    Returns:
        False when it does not, or git could not say.
    """
    try:
        _git(runner, where, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except Unlisted:
        return False
    return True


class _Dir:
    """A directory of the tree being outlined; the root's name and path are empty."""

    __slots__ = ("depth", "dirs", "files", "hits", "name", "parent", "path", "total")

    def __init__(self, name: str, parent: _Dir | None) -> None:
        self.name = name
        self.parent = parent
        self.path: str = name if parent is None or not parent.path else f"{parent.path}/{name}"
        self.depth: int = 0 if parent is None else parent.depth + 1
        self.dirs: dict[str, _Dir] = {}
        #: The names of the files directly in it.
        self.files: list[str] = []
        #: How many files are in it and under it.
        self.total = 0
        #: The work's words its own name holds.
        self.hits: frozenset[str] = frozenset()

    def above(self) -> Iterator[_Dir]:
        """Yield each directory above it, nearest first, the root last."""
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _Shown:
    """Which directories of a tree an outline shows, and how: grown one directory at a time, never past its budget."""

    def __init__(self, root: _Dir, about: About, *, budget: int) -> None:
        self._root = root
        self._about = about
        self._budget = budget
        #: The paths of the directories whose children are shown; the root's always are.
        self._expanded: set[str] = {""}
        #: The paths of the directories whose own files are listed by name.
        self._opened: set[str] = set()

    def open(self, node: _Dir) -> bool:
        """Show `node` with its files listed, and every directory above it, if the outline stays within its budget.

        Returns:
            Whether it did.
        """
        expanded = self._expanded | {node.path} | {above.path for above in node.above()}
        return self._keep(expanded, self._opened | {node.path})

    def fill(self) -> None:
        """Open the directories still collapsed, outermost first and the largest first among those, while they fit."""
        waiting: list[tuple[int, int, int, str, _Dir]] = []

        def offer(node: _Dir) -> None:
            # A directory's own files are a level below its name, so its subdirectories are shown before them.
            if node.files and node.path not in self._opened:
                heapq.heappush(waiting, (node.depth + 1, 1, -len(node.files), node.path, node))
            for child in node.dirs.values():
                if child.path in self._expanded:
                    offer(child)
                elif child.dirs:
                    heapq.heappush(waiting, (child.depth, 0, -child.total, child.path, child))
                else:
                    # Nothing but files: shown open, or left as its name and count.
                    heapq.heappush(waiting, (child.depth + 1, 1, -child.total, child.path, child))

        offer(self._root)
        tried = misses = 0
        while waiting and tried < _MAX_FILL and misses < _MAX_MISSES:
            _, files, _, _, node = heapq.heappop(waiting)
            tried += 1
            if files:
                fits = self.open(node)
            else:
                fits = self._keep(self._expanded | {node.path}, self._opened)
                if fits:
                    offer(node)
            misses = 0 if fits else misses + 1

    def lines(self) -> tuple[list[str], int]:
        """Return the outline's lines, cut to its budget, and how many files they list by name."""
        lines, named = _lines(self._root, self._expanded, self._opened, self._about)
        if _cost(lines) <= self._budget:
            return lines, named
        # A root too wide for the budget even collapsed: its start, which the count below it accounts for.
        kept: list[str] = []
        room = self._budget
        for line in lines:
            room -= len(_QUOTE) + len(line) + 1
            if room < 0:
                break
            kept.append(line)
        return kept, 0

    def _keep(self, expanded: set[str], opened: set[str]) -> bool:
        lines, _ = _lines(self._root, expanded, opened, self._about)
        if _cost(lines) > self._budget:
            return False
        self._expanded, self._opened = expanded, opened
        return True


def _shown(path: str) -> bool:
    # Whether a path may be rendered: bounded, and with no character that hides text. Most are plain ASCII, which is
    # checked without a look at each character.
    if len(path) > MAX_PATH:
        return False
    if path.isascii():
        return path.isprintable()
    return not any(hidden_char(c) for c in path)


def _add(root: _Dir, index: dict[str, _Dir], parts: Sequence[str]) -> None:
    node = root
    node.total += 1
    for part in parts[:-1]:
        child = node.dirs.get(part)
        if child is None:
            child = node.dirs[part] = _Dir(part, node)
            index[child.path] = child
        node = child
        node.total += 1
    node.files.append(parts[-1])


def _seeds(index: Mapping[str, _Dir], about: About) -> list[_Dir]:
    # The directories the work is about, best first: those it changed, or else those its words name.
    if about.changed:
        counts = Counter(posixpath.dirname(path) for path in about.changed)
        found = [(count, index[path]) for path, count in counts.items() if path in index]
        return [node for _, node in sorted(found, key=lambda f: (-f[0], f[1].depth, f[1].path))]
    if not about.words:
        return []
    # A word that names many directories says little of any one, so each counts for less the more it names.
    named: Counter[str] = Counter()
    hit: list[tuple[_Dir, frozenset[str]]] = []
    split: dict[str, frozenset[str]] = {}
    for node in index.values():
        node.hits = _parts(node.name, split) & about.words
        inside = frozenset().union(*(_parts(name, split) & about.words for name in node.files)) - node.hits
        if node.hits or inside:
            named.update(node.hits | inside)
            hit.append((node, inside))
    weight = {word: math.log(1 + len(index) / count) for word, count in named.items()}
    scored: list[tuple[float, _Dir]] = []
    for node, inside in hit:
        above = frozenset().union(*(a.hits for a in node.above())) - node.hits - inside
        score = sum(weight[w] for w in node.hits) + sum(weight[w] for w in inside | above) / 2
        scored.append((score, node))
    return [node for _, node in sorted(scored, key=lambda s: (-s[0], s[1].depth, s[1].path))]


def _parts(name: str, split: dict[str, frozenset[str]]) -> frozenset[str]:
    # The same names recur across a tree (`BUILD`, `__init__.py`), so each is split once.
    found = split.get(name)
    if found is None:
        found = split[name] = frozenset(_normal(w) for w in _WORD_RE.findall(name))
    return found


def _normal(word: str) -> str:
    # Lowercase, and a plain plural made its singular, the same way for a text's words and a path's.
    lower = word.lower()
    return lower[:-1] if len(lower) > MIN_WORD and lower.endswith("s") and not lower.endswith("ss") else lower


def _lines(root: _Dir, expanded: AbstractSet[str], opened: AbstractSet[str], about: About) -> tuple[list[str], int]:
    # The tree's lines, each directory's subdirectories before its own files, and how many files they name.
    lines: list[str] = []
    named = 0
    # (directory, the next of its sorted subdirectories to show): a stack, since a tree may be deeper than Python's.
    stack: list[tuple[_Dir, Iterator[str]]] = [(root, iter(sorted(root.dirs)))]
    while stack:
        node, rest = stack[-1]
        pad = _INDENT * node.depth
        name = next(rest, None)
        if name is not None:
            child = node.dirs[name]
            if child.path in expanded:
                lines.append(f"{pad}{name}/")
                stack.append((child, iter(sorted(child.dirs))))
            else:
                lines.append(f"{pad}{name}/ ({_files(child.total)})")
            continue
        stack.pop()
        if not node.files:
            continue
        if node.path not in opened:
            lines.append(f"{pad}... {_files(len(node.files))}")
            continue
        listed_ = _first(node, about)
        lines.extend(pad + name for name in listed_)
        named += len(listed_)
        if len(listed_) < len(node.files):
            lines.append(f"{pad}... {_files(len(node.files) - len(listed_))} more")
    return lines, named


def _first(node: _Dir, about: About) -> list[str]:
    # The files of `node` its outline names, in order: all of a small directory, else those the work is about first.
    if len(node.files) <= MAX_FILES_SHOWN:
        return sorted(node.files)
    split: dict[str, frozenset[str]] = {}

    def rank(name: str) -> tuple[bool, bool, str]:
        path = f"{node.path}/{name}" if node.path else name
        return (path not in about.changed, not _parts(name, split) & about.words, name)

    return sorted(sorted(node.files, key=rank)[:MAX_FILES_SHOWN])


def _cost(lines: Iterable[str]) -> int:
    return sum(len(_QUOTE) + len(line) + 1 for line in lines)


def _files(count: int) -> str:
    return f"{count:,} file" if count == 1 else f"{count:,} files"


def _footer(total: int, named: int, dropped: int, *, cut: bool) -> str:
    said = [f"{_files(total)} in all, {total - named:,} not listed by name."]
    if dropped:
        said.append(
            f"{dropped:,} more left out, each a path over {MAX_PATH} characters or with a character that hides text.",
        )
    if cut:
        said.append("The tree is larger than canopy lists, so this is its start alone.")
    return " ".join(said)


def _git(runner: procs.Runner, where: Path, *args: str, max_stdout: int | None = None) -> str:
    """Run `git <args>` read-only in the checkout `where`, never one above it.

    Returns:
        What it printed.

    Raises:
        Unlisted: git could not start, timed out, failed, or printed what is not UTF-8 text.
    """
    env = {**git_tools.ENV, "GIT_CEILING_DIRECTORIES": str(where.parent)}
    try:
        done = runner.run(
            hostgit.argv(*git_tools.READ_FLAGS, *args),
            cwd=where,
            env=env,
            timeout=TIMEOUT_SECONDS,
            max_stdout=max_stdout,
        )
    except UnicodeDecodeError:
        raise Unlisted(f"git {args[0]} printed what is not UTF-8 text") from None
    except procs.ProcError as e:
        raise Unlisted(f"git {args[0]} could not run: {e}") from None
    if done.timed_out:
        raise Unlisted(f"git {args[0]} took more than {TIMEOUT_SECONDS} seconds")
    if not done.ok:
        said = (done.stderr.strip() or done.stdout.strip()).splitlines()
        first = visible(said[0])[:300] if said else f"exit {done.returncode}"
        raise Unlisted(f"git {args[0]} failed: {first}")
    return done.stdout
