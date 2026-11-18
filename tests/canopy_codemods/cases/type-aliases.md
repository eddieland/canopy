# `type-aliases`

Each case is a module's text. Under Rewritten, a case is the text before and the text after; under Left alone, text
the codemod does not change. `test_type_aliases.py` runs them.

## Rewritten

### Literal

```python
Outcome = Literal["packed", "skipped"]
```

```python
type Outcome = Literal["packed", "skipped"]
```

### Private and dotted

```python
_Kind = typing.Literal[1, 2]
```

```python
type _Kind = typing.Literal[1, 2]
```

### Tuple

```python
Unit = tuple[str, str | None]
```

```python
type Unit = tuple[str, str | None]
```

### Tuple of any length

```python
Many = tuple[int, ...]
```

```python
type Many = tuple[int, ...]
```

### Callable

```python
Endpoint = Callable[[str], 'Reply']
```

```python
type Endpoint = Callable[[str], 'Reply']
```

### Union of builtins

```python
Value = int | str | None
```

```python
type Value = int | str | None
```

### Union with none

```python
Found = Row | None
```

```python
type Found = Row | None
```

### Union with a subscript

```python
Rows = Row | list[Row]
```

```python
type Rows = Row | list[Row]
```

### Keeps comments and layout

```python
"""Doc."""

#: What it is.
Unit = tuple[
    str,  # one
    int,
]  # why
```

```python
"""Doc."""

#: What it is.
type Unit = tuple[
    str,  # one
    int,
]  # why
```

### One line

```python
Unit = tuple[int]; Pair = tuple[str]
```

```python
type Unit = tuple[int]; type Pair = tuple[str]
```

### Read in annotations

```python
Unit = tuple[str, int]


def f(unit: Unit, *more: Unit, key: Unit) -> list[Unit]:
    found: dict[str, Unit] = {}
    return [unit, *more, key, *found.values()]
```

```python
type Unit = tuple[str, int]


def f(unit: Unit, *more: Unit, key: Unit) -> list[Unit]:
    found: dict[str, Unit] = {}
    return [unit, *more, key, *found.values()]
```

### Read by another alias

```python
Unit = tuple[str, int]
Units = tuple[Unit, ...]
type Found = Unit | None
```

```python
type Unit = tuple[str, int]
type Units = tuple[Unit, ...]
type Found = Unit | None
```

### Beside one read at run time

```python
Kind = Literal[1, 2]
Unit = tuple[str, int]
print(Kind)
```

```python
Kind = Literal[1, 2]
type Unit = tuple[str, int]
print(Kind)
```

## Left alone

### Passed to get args

```python
Kind = Literal[1, 2]
KINDS = get_args(Kind)
```

### Read in a function

```python
Kind = Literal[1, 2]


def f(x: object) -> bool:
    return x in args(Kind)
```

### Isinstance

```python
Unit = tuple[str, int]


def f(x: object) -> bool:
    return isinstance(x, Unit)
```

### Called

```python
Unit = tuple[str, int]
EMPTY = Unit(('', 0))
```

### Subclassed

```python
Unit = tuple[str, int]


class Named(Unit):
    pass
```

### Subscripted at run time

```python
Unit = tuple[str, int]
ADAPTER = TypeAdapter(list[Unit])
```

### Read by an alias left alone

```python
Kind = Literal[1, 2]
Field = Annotated[Kind, 'which']
```

### Read by an alias read at run time

```python
Kind = Literal[1, 2]
Kinds = tuple[Kind, ...]
print(Kinds)
```

### Annotated

```python
Key = Annotated[str, Field(description='A key.')]
```

### Dependency

```python
Dep = Annotated[Options, Depends(options)]
```

### Another subscript

```python
Index = dict[str, int]
Rows = list[Row]
```

### Union that may be of values

```python
Both = Color.RED | Color.BLUE
Either = Left | Right
```

### Not a type expression

```python
Total = int | 3
Span = tuple[int, 1 + 2]
```

### A class used as a value

```python
Row = records.Run
Make = make_row
```

### Generic

```python
from typing import TypeVar

T = TypeVar('T')
Pair = tuple[T, T]
```

### New type

```python
UserId = NewType('UserId', int)
```

### Namedtuple

```python
Point = namedtuple('Point', ['x', 'y'])
```

### Explicit type alias

```python
Unit: TypeAlias = tuple[str, int]
```

### Type statement already

```python
type Unit = tuple[str, int]
```

### Upper case

```python
UNIT = tuple[str, int]
T = tuple[int]
```

### Lowercase

```python
unit = tuple[str, int]
```

### Assigned twice

```python
Unit = tuple[str, int]
Unit = tuple[str, str]
```

### Chained

```python
Unit = Other = tuple[str, int]
```

### Nested

```python
import sys

if sys.platform == 'darwin':
    Unit = tuple[str, int]
else:
    Unit = tuple[str]
```

### Not module

```python
class C:
    Unit = tuple[str, int]


def f() -> None:
    Unit = tuple[str]
```
