"""The bundled prompts', agent definitions', and skills' sizes, and the most each may grow to.

These are sent to the model on every run: the overseer's prompt is its system prompt on every tick (DESIGN §6), and a
worker's prompt and definition on every run, so a paragraph a PR adds is paid for on every run after it.
`test_prompt_sizes.py` fails when a file grows past its entry in LIMITS, and raising the entry is a one-line change
the PR's diff shows. `make prompt-sizes` runs this module to print each file's size, for reading before and after an
edit. It measures text, never model output (AGENTS.md, Testing).
"""

import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = (".agents/prompts", ".agents/agents", ".agents/skills")
# A rough rule for English prose; the overseer's prompt measured about 13k tokens at 51k characters.
CHARS_PER_TOKEN = 4

# The most characters each file may hold, keyed by its path from the repository root. Raise one when growth is meant.
LIMITS: dict[str, int] = {
    ".agents/prompts/overseer.md": 51462,
    ".agents/prompts/reviewer.md": 3526,
    ".agents/prompts/worker-fix-ci-private.md": 3296,
    ".agents/prompts/worker-fix-ci.md": 3654,
    ".agents/prompts/worker-implement-private.md": 5336,
    ".agents/prompts/worker-implement.md": 5707,
    ".agents/prompts/worker-resume-private.md": 6633,
    ".agents/prompts/worker-resume.md": 7399,
    ".agents/prompts/worker-split.md": 4960,
    ".agents/agents/canopy-chore.md": 1957,
    ".agents/agents/canopy-overseer.md": 1603,
    ".agents/agents/canopy-reviewer.md": 2181,
    ".agents/agents/canopy-splitter.md": 2060,
    ".agents/agents/canopy-worker-private.md": 4563,
    ".agents/agents/canopy-worker.md": 4219,
    ".agents/skills/tracker-github/SKILL.md": 4318,
    ".agents/skills/tracker-jira/SKILL.md": 3476,
}


def sizes() -> dict[str, int]:
    """Return the characters in each file under DIRECTORIES, keyed by its path from the repository root."""
    return {
        path.relative_to(ROOT).as_posix(): len(path.read_text(encoding="utf-8"))
        for directory in DIRECTORIES
        for path in sorted((ROOT / directory).rglob("*"))
        if path.is_file()
    }


def tokens(chars: int) -> int:
    """Return an estimate of the tokens in `chars` characters of prose."""
    return math.ceil(chars / CHARS_PER_TOKEN)


def main() -> None:
    """Print each file's characters, estimated tokens, and room left under its limit, then the totals."""
    measured = sizes()
    width = max(len(path) for path in measured)
    print(f"{'file':<{width}}  {'chars':>7}  {'~tokens':>7}  {'limit':>7}  {'room':>6}")
    for path, chars in measured.items():
        limit = LIMITS.get(path)
        room = "-" if limit is None else str(limit - chars)
        print(f"{path:<{width}}  {chars:>7}  {tokens(chars):>7}  {limit or '-':>7}  {room:>6}")
    total = sum(measured.values())
    print(f"{'total':<{width}}  {total:>7}  {tokens(total):>7}")


if __name__ == "__main__":
    main()
