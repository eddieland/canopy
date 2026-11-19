# `vocab-members`

Each case is a module's text, read as one of canopy's own modules. Under Rewritten, a case is the text before and the
text after; under Left alone, text the codemod does not change. `test_vocab_members.py` runs them. The vocabularies are
canopy's own, read from `src/canopy/core/vocab.py`, so a case names their real members.

## Rewritten

### A parameter annotated with the vocabulary

```python
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> bool:
    return status == "done"
```

```python
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> bool:
    return status == RunStatus.DONE
```

### Optional, unequal, and the string on the left

```python
from canopy.core.vocab import RunStatus


def waiting(status: RunStatus | None) -> bool:
    return "blocked" != status
```

```python
from canopy.core.vocab import RunStatus


def waiting(status: RunStatus | None) -> bool:
    return RunStatus.BLOCKED != status
```

### An annotated assignment

```python
from canopy.core.vocab import TickStatus


def label(found: str) -> str:
    status: TickStatus = TickStatus(found)
    return "busy" if status == "running" else "idle"
```

```python
from canopy.core.vocab import TickStatus


def label(found: str) -> str:
    status: TickStatus = TickStatus(found)
    return "busy" if status == TickStatus.RUNNING else "idle"
```

### A row type's field

```python
from canopy.core import records


def live(run: records.Run) -> bool:
    return run.status == "running"
```

```python
from canopy.core import records
from canopy.core.vocab import RunStatus


def live(run: records.Run) -> bool:
    return run.status == RunStatus.RUNNING
```

### A row type imported by name

```python
from canopy.core.records import Run
from canopy.core.vocab import RunStatus


def live(run: Run | None) -> bool:
    return run is not None and run.status == "running"
```

```python
from canopy.core.records import Run
from canopy.core.vocab import RunStatus


def live(run: Run | None) -> bool:
    return run is not None and run.status == RunStatus.RUNNING
```

### In a tuple, a list, or a set

```python
from canopy.core import records
from canopy.core.vocab import RunKind


def works(run: records.Run) -> bool:
    started = run.kind in ("implement", "resume")
    return started and run.kind not in {"plan"} and run.kind in ["resume"]
```

```python
from canopy.core import records
from canopy.core.vocab import RunKind


def works(run: records.Run) -> bool:
    started = run.kind in (RunKind.IMPLEMENT, RunKind.RESUME)
    return started and run.kind not in {RunKind.PLAN} and run.kind in [RunKind.RESUME]
```

### Matched by a case

```python
from canopy.core.vocab import Phase


def step(phase: Phase) -> int:
    match phase:
        case "ready":
            return 0
        case "ci_red" | "conflicted" as broken if broken:
            return 1
        case _:
            return 2
```

```python
from canopy.core.vocab import Phase


def step(phase: Phase) -> int:
    match phase:
        case Phase.READY:
            return 0
        case Phase.CI_RED | Phase.CONFLICTED as broken if broken:
            return 1
        case _:
            return 2
```

### A field of the class of self

```python
from dataclasses import dataclass

from canopy.core.vocab import PlanStatus


@dataclass(frozen=True)
class Plan:
    status: PlanStatus

    def waits(self) -> bool:
        return self.status == "proposed"
```

```python
from dataclasses import dataclass

from canopy.core.vocab import PlanStatus


@dataclass(frozen=True)
class Plan:
    status: PlanStatus

    def waits(self) -> bool:
        return self.status == PlanStatus.PROPOSED
```

### A status only one vocabulary holds, which the module imports

```python
from canopy.core.vocab import TickStatus


def failed(outcome: Outcome) -> bool:
    return outcome.status == "overseer_failed"
```

```python
from canopy.core.vocab import TickStatus


def failed(outcome: Outcome) -> bool:
    return outcome.status == TickStatus.OVERSEER_FAILED
```

### A closure reads the annotation of the function around it

```python
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> Callable[[], bool]:
    def build() -> bool:
        return status == "blocked"

    return build
```

```python
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> Callable[[], bool]:
    def build() -> bool:
        return status == RunStatus.BLOCKED

    return build
```

### Imported for the type checker beside others

```python
from typing import TYPE_CHECKING

from canopy.core import db

if TYPE_CHECKING:
    from canopy.core.vocab import ChoreRunStatus, RunStatus


def ended(status: RunStatus, chore: ChoreRunStatus) -> bool:
    return status == "done"
```

```python
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.vocab import RunStatus

if TYPE_CHECKING:
    from canopy.core.vocab import ChoreRunStatus


def ended(status: RunStatus, chore: ChoreRunStatus) -> bool:
    return status == RunStatus.DONE
```

### Imported for the type checker alone

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db

if TYPE_CHECKING:
    from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> bool:
    return status == "done"
```

```python
from __future__ import annotations

from canopy.core import db
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> bool:
    return status == RunStatus.DONE
```

### The vocabularies' module

```python
from canopy.core import vocab


def ended(status: vocab.RunStatus) -> bool:
    return status == "done"
```

```python
from canopy.core import vocab


def ended(status: vocab.RunStatus) -> bool:
    return status == vocab.RunStatus.DONE
```

## Left alone

### A string several vocabularies hold

```python
from canopy.core.vocab import RunStatus


def live(run: object) -> bool:
    return run.status == "running"
```

### A string the vocabulary does not hold

```python
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> bool:
    return status == "finished"
```

### Strings outside a comparison

```python
from canopy.core import records, sql
from canopy.core.vocab import RunStatus


def running(conn: Connection, run: records.Run) -> dict[str, int]:
    log.info("status running", extra={"status": "running"})
    rows = sql.select("id").from_("runs").where("status = 'running'").all(conn)
    return {"running": len(rows), run.status: 1}
```

### Annotated with something else

```python
from typing import Literal

from canopy.core.vocab import RunStatus


def ended(status: str, kind: Literal["implement", "resume"]) -> bool:
    return status == "done" and kind == "implement"
```

### A union of vocabularies

```python
from canopy.core.vocab import AnyRunStatus


def ended(status: AnyRunStatus) -> bool:
    return status == "done"
```

### A field of the class of self annotated otherwise

```python
from typing import Literal

from canopy.core.vocab import SourceKind


class Source:
    kind: Literal["vcs", "tracker"]

    def reads_prs(self) -> bool:
        return self.kind == "vcs"
```

### A status only one vocabulary holds, which the module does not import

```python
from canopy.core import records


def failed(outcome: Outcome) -> bool:
    return outcome.status == "overseer_failed"
```

### A kind only a vocabulary of another word holds

```python
from canopy.core.vocab import RequestAction


def ends(kind: str) -> bool:
    return kind == "end"
```

### A name a nested function binds again

```python
from canopy.core.vocab import RunStatus


def ended(status: RunStatus) -> Callable[[str], bool]:
    def build(status: str) -> bool:
        return status == "blocked"

    return build
```

### A comprehension's name

```python
from canopy.core import records


def live(run: records.Run, rows: list[Row]) -> list[Row]:
    return [run for run in rows if run.status == "running"]
```

### A vocabulary's name bound by another import

```python
from canopy.core import records
from canopy.serve.schema import RunStatus


def live(run: records.Run) -> bool:
    return run.status == "running"
```

### Some strings no vocabulary holds

```python
from canopy.core.vocab import RunStatus


def settled(status: RunStatus) -> bool:
    return status in ("done", "settled")
```

### A chained comparison

```python
from canopy.core.vocab import RunStatus


def same(status: RunStatus, other: RunStatus) -> bool:
    return status == "done" == other
```

### A module that imports nothing from canopy's core

```python
from vocab import RunStatus


def ended(status: RunStatus) -> bool:
    return status == "done"
```
