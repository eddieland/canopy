# `general-params`

Each case is a module's text. Under Rewritten, a case is the text before and the text after; under Left alone, text
the codemod does not change. `test_general_params.py` runs them. The codemod adds an import where libcst puts it, and
ruff then sorts and spaces it, which a case does not show.

## Rewritten

### One for

```python
def total(costs: list[float]) -> float:
    result = 0.0
    for cost in costs:
        result += cost
    return result
```

```python
from collections.abc import Iterable

def total(costs: Iterable[float]) -> float:
    result = 0.0
    for cost in costs:
        result += cost
    return result
```

### One comprehension

```python
def total(costs: list[float]) -> float:
    return sum(c for c in costs)
```

```python
from collections.abc import Iterable

def total(costs: Iterable[float]) -> float:
    return sum(c for c in costs)
```

### A builtin that iterates

```python
def total(costs: list[float]) -> float:
    return sum(costs)
```

```python
from collections.abc import Iterable

def total(costs: Iterable[float]) -> float:
    return sum(costs)
```

### Joined

```python
def line(words: list[str]) -> str:
    return ", ".join(words)
```

```python
from collections.abc import Iterable

def line(words: Iterable[str]) -> str:
    return ", ".join(words)
```

### Measured

```python
def count(items: list[str]) -> int:
    return len(items)
```

```python
from collections.abc import Collection

def count(items: Collection[str]) -> int:
    return len(items)
```

### Searched

```python
def has(items: list[str], item: str) -> bool:
    return item in items
```

```python
from collections.abc import Collection

def has(items: Collection[str], item: str) -> bool:
    return item in items
```

### Two passes

```python
def spread(costs: list[float]) -> float:
    return max(costs) - min(costs)
```

```python
from collections.abc import Collection

def spread(costs: Collection[float]) -> float:
    return max(costs) - min(costs)
```

### A loop inside a loop

```python
def pairs(left: list[int], right: list[int]) -> int:
    found = 0
    for a in left:
        for b in right:
            found += a * b
    return found
```

```python
from collections.abc import Collection, Iterable

def pairs(left: Iterable[int], right: Collection[int]) -> int:
    found = 0
    for a in left:
        for b in right:
            found += a * b
    return found
```

### Tested

```python
def first(items: list[str]) -> str:
    if not items:
        return ""
    return "x"
```

```python
from collections.abc import Collection

def first(items: Collection[str]) -> str:
    if not items:
        return ""
    return "x"
```

### Indexed

```python
def first(items: list[str]) -> str:
    return items[0]
```

```python
from collections.abc import Sequence

def first(items: Sequence[str]) -> str:
    return items[0]
```

### Reversed

```python
def last(items: list[str]) -> str:
    for item in reversed(items):
        return item
    return ""
```

```python
from collections.abc import Sequence

def last(items: Sequence[str]) -> str:
    for item in reversed(items):
        return item
    return ""
```

### Sliced and only read

```python
def rest(items: list[str]) -> int:
    return len(items[1:])
```

```python
from collections.abc import Sequence

def rest(items: Sequence[str]) -> int:
    return len(items[1:])
```

### A dict only read

```python
def name(row: dict[str, str]) -> str:
    return row.get("name") or row["id"]
```

```python
from collections.abc import Mapping

def name(row: Mapping[str, str]) -> str:
    return row.get("name") or row["id"]
```

### A set tested with in

```python
def kept(name: str, names: set[str]) -> bool:
    return name in names
```

```python
from collections.abc import Set as AbstractSet

def kept(name: str, names: AbstractSet[str]) -> bool:
    return name in names
```

### A frozenset tested with in

```python
def kept(name: str, names: frozenset[str]) -> bool:
    return name not in names
```

```python
from collections.abc import Set as AbstractSet

def kept(name: str, names: AbstractSet[str]) -> bool:
    return name not in names
```

### Under TYPE_CHECKING

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def total(costs: list[float], path: Path) -> float:
    return sum(costs)
```

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def total(costs: Iterable[float], path: Path) -> float:
    return sum(costs)
```

### Joins an import

```python
from collections.abc import Callable


def total(costs: list[float], round: Callable[[float], float]) -> float:
    return round(sum(costs))
```

```python
from collections.abc import Iterable, Callable


def total(costs: Iterable[float], round: Callable[[float], float]) -> float:
    return round(sum(costs))
```

### A method of a class with no base

```python
class Totals:
    def total(self, costs: list[float]) -> float:
        return sum(costs)
```

```python
from collections.abc import Iterable

class Totals:
    def total(self, costs: Iterable[float]) -> float:
        return sum(costs)
```

### Plain decorators

```python
import pytest


@pytest.mark.parametrize("costs", [[1.0]])
def test_total(costs: list[float]) -> None:
    assert sum(costs)
```

```python
import pytest
from collections.abc import Iterable


@pytest.mark.parametrize("costs", [[1.0]])
def test_total(costs: Iterable[float]) -> None:
    assert sum(costs)
```

### A nested function's own parameter

```python
def outer() -> float:
    def total(costs: list[float]) -> float:
        return sum(costs)

    return total([1.0])
```

```python
from collections.abc import Iterable

def outer() -> float:
    def total(costs: Iterable[float]) -> float:
        return sum(costs)

    return total([1.0])
```

### Each parameter by itself

```python
def merge(left: list[int], right: list[int]) -> int:
    right.append(1)
    return sum(left)
```

```python
from collections.abc import Iterable

def merge(left: Iterable[int], right: list[int]) -> int:
    right.append(1)
    return sum(left)
```

### Keeps an already-imported name

```python
from collections.abc import Set as AbstractSet


def kept(name: str, names: set[str], others: AbstractSet[str]) -> bool:
    return name in names and name in others
```

```python
from collections.abc import Set as AbstractSet


def kept(name: str, names: AbstractSet[str], others: AbstractSet[str]) -> bool:
    return name in names and name in others
```

### A name bound again

```python
def pick(items: list[str], rows: list[list[str]]) -> int:
    for items in rows:
        pass
    return 0
```

```python
from collections.abc import Iterable

def pick(items: list[str], rows: Iterable[list[str]]) -> int:
    for items in rows:
        pass
    return 0
```

### The left of in

```python
def known(item: list[str], seen: list[list[str]]) -> bool:
    return item in seen
```

```python
from collections.abc import Collection

def known(item: list[str], seen: Collection[list[str]]) -> bool:
    return item in seen
```

### A dict copied

```python
def copy(row: dict[str, str]) -> int:
    return len(dict(row))
```

```python
from collections.abc import Mapping

def copy(row: Mapping[str, str]) -> int:
    return len(dict(row))
```

### Imported again where a function's import cannot serve

```python
def helper() -> None:
    from collections.abc import Iterable


def total(costs: list[float]) -> float:
    return sum(costs)
```

```python
from collections.abc import Iterable

def helper() -> None:
    from collections.abc import Iterable


def total(costs: Iterable[float]) -> float:
    return sum(costs)
```

### Imported again where the checker's import cannot serve

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def total(costs: list[float]) -> float:
    return sum(costs)
```

```python
from typing import TYPE_CHECKING
from collections.abc import Iterable

if TYPE_CHECKING:
    from collections.abc import Iterable


def total(costs: Iterable[float]) -> float:
    return sum(costs)
```

### Beside a one-line TYPE_CHECKING suite

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING: from pathlib import Path


def total(costs: list[float], path: Path) -> float:
    return sum(costs)
```

```python
from __future__ import annotations

from typing import TYPE_CHECKING
from collections.abc import Iterable

if TYPE_CHECKING: from pathlib import Path


def total(costs: Iterable[float], path: Path) -> float:
    return sum(costs)
```

## Left alone

### Mutated

```python
def add(items: list[str]) -> None:
    items.append("x")
```

### Subscript stored

```python
def put(row: dict[str, str]) -> None:
    row["x"] = "y"
```

### Stored on an object

```python
class Box:
    def __init__(self, items: list[str]) -> None:
        self.items = items
```

### Returned

```python
def same(items: list[str]) -> object:
    return items
```

### Returned when true

```python
def same(items: list[str]) -> object:
    return items or None
```

### Yielded

```python
def each(items: list[str]):
    yield from items
```

### Passed to another call

```python
import json


def dump(items: list[str]) -> str:
    return json.dumps(items)
```

### Given to isinstance

```python
def check(items: dict[str, str]) -> bool:
    return isinstance(items, dict)
```

### Given as a keyword argument

```python
def ordered(items: list[str], keys: dict[str, int]) -> list[str]:
    return sorted(items, key=keys.get)
```

### Compared

```python
def empty(items: list[str]) -> bool:
    return items == []
```

### Formatted

```python
def show(items: list[str]) -> str:
    return f"{items}"
```

### Sliced and returned

```python
def rest(items: list[str]) -> list[str]:
    return items[1:]
```

### Unused

```python
def ignore(items: list[str]) -> None:
    pass
```

### Reassigned

```python
def pick(items: list[str]) -> int:
    items = sorted(items)
    return len(items)
```

### A closure

```python
def later(items: list[str]):
    def count() -> int:
        return len(items)

    return count
```

### A lambda

```python
def later(items: list[str]):
    return lambda: len(items)
```

### A click command

```python
import click


@click.command()
@click.argument("names", nargs=-1)
def main(names: list[str]) -> None:
    for name in names:
        click.echo(name)
```

### An override

```python
from typing import override


class Base:
    def total(self, costs: list[float]) -> float:
        return 0.0


class Totals(Base):
    @override
    def total(self, costs: list[float]) -> float:
        return sum(costs)
```

### A method of a class with a base

```python
class Totals(Base):
    def total(self, costs: list[float]) -> float:
        return sum(costs)
```

### A protocol

```python
from typing import Protocol


class Totals(Protocol):
    def total(self, costs: list[float]) -> float:
        return sum(costs)
```

### Returns the type it takes

```python
def unique(items: list[str]) -> list[str]:
    return sorted(set(items))
```

### A set's own method

```python
def overlap(names: set[str], other: set[str]) -> bool:
    return names.isdisjoint(other)
```

### A dict merged

```python
def merged(row: dict[str, str]) -> int:
    return len(row | {"x": "y"})
```

### A dict reversed

```python
def last(row: dict[str, str]) -> list[str]:
    return [k for k in reversed(row)]
```

### A set indexed

```python
def first(names: set[str]) -> str:
    return names[0]
```

### Quoted

```python
def total(costs: "list[float]") -> float:
    return sum(costs)
```

### Optional

```python
def total(costs: list[float] | None) -> float:
    return sum(costs or [])
```

### Bare

```python
def total(costs: list) -> float:
    return sum(costs)
```

### Already abstract

```python
from collections.abc import Iterable


def total(costs: Iterable[float]) -> float:
    return sum(costs)
```

### A clashing name

```python
from typing import Iterable


def total(costs: list[float], more: Iterable[float]) -> float:
    return sum(costs) + sum(more)
```

### Variadic

```python
def total(*costs: list[float]) -> float:
    return sum(costs[0])
```

### Max of two

```python
def larger(a: list[int], b: list[int]) -> list[int] | int:
    return max(a, b)
```

### A class binds the abstract name

```python
class Box:
    Mapping = 3

    def get(self, row: dict[str, str]) -> str:
        return row["x"]
```

### A builtin's name bound

```python
from mylib import sorted


def ordered(items: list[str]) -> int:
    return len(sorted(items))
```

### A method another class of the module overrides

```python
class Base:
    def total(self, costs: list[float]) -> float:
        return sum(costs)


class Totals(Base):
    def total(self, costs: list[float]) -> float:
        costs.append(1.0)
        return 0.0
```

### A method under an if in a class with a base

```python
import sys


class Totals(Base):
    if sys.version_info >= (3, 12):
        def total(self, costs: list[float]) -> float:
            return sum(costs)
```
