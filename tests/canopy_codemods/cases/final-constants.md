# `final-constants`

Each case is a module's text. Under Rewritten, a case is the text before and the text after; under Left alone, text
the codemod does not change. `test_final_constants.py` runs them.

## Rewritten

### Plain

```python
LIMIT = 3
```

```python
from typing import Final

LIMIT: Final = 3
```

### Private

```python
_LIMIT = 3
```

```python
from typing import Final

_LIMIT: Final = 3
```

### Annotated

```python
from collections.abc import Sequence

NAMES: Sequence[str] = ()
```

```python
from collections.abc import Sequence
from typing import Final

NAMES: Final[Sequence[str]] = ()
```

### Joins the import of typing

Unsorted, as libcst adds it: ruff sorts it next (`make fmt`).

```python
from typing import Any

A = 1
```

```python
from typing import Final, Any

A: Final = 1
```

### Beside one already final

```python
from typing import Final

A: Final = 1
B = 2
```

```python
from typing import Final

A: Final = 1
B: Final = 2
```

### Keeps comments and layout

```python
"""Doc."""

#: What it is.
A = (
    1,  # one
    2,
)  # why
```

```python
"""Doc."""
from typing import Final

#: What it is.
A: Final = (
    1,  # one
    2,
)  # why
```

### One line

```python
A = 1; B = 2
```

```python
from typing import Final

A: Final = 1; B: Final = 2
```

### A local of the same name is another name

```python
A = 1


def f() -> None:
    A = 2
    print(A)
```

```python
from typing import Final

A: Final = 1


def f() -> None:
    A = 2
    print(A)
```

### A class attribute of the same name is another name

```python
class Kind:
    ROW = 1


ROW = Kind.ROW
```

```python
from typing import Final

class Kind:
    ROW = 1


ROW: Final = Kind.ROW
```

## Left alone

### Lowercase

```python
import logging

_log = logging.getLogger(__name__)
router = object()
```

### Dunder

```python
__all__ = ['a']
__version__ = '1'
```

### Camel case

```python
Alias = dict[str, int]
```

### Logger

```python
import logging

LOG = logging.getLogger(__name__)
```

### Lock

```python
import threading

_LOCK = threading.Lock()
```

### Var

```python
from contextvars import ContextVar

TICK: ContextVar[str] = ContextVar('tick')
```

### Type variable

```python
from typing import TypeVar

T = TypeVar('T')
```

### Type alias

```python
from typing import TypeAlias

JSON: TypeAlias = dict[str, object]
```

### Final already

```python
import typing

A: typing.Final = 1
B: typing.Final[int] = 2
```

### Final already quoted

```python
A: 'Final[int]' = 1
```

### Declared without a value

```python
A: int
```

### Assigned twice

```python
A = 1
A = 2
```

### Augmented

```python
A = 1
A += 1
```

### Deleted

```python
A = 1
del A
```

### Loop variable

```python
A = 1
for A in ():
    pass
```

### With target

```python
A = 1
with open('f') as A:
    pass
```

### Imported

```python
A = None
try:
    import a as A
except ImportError:
    pass
```

### Global

```python
A = 0


def bump() -> None:
    global A
    A += 1
```

### Walrus

```python
A = 0
print(A := 1)
```

### Unpacked

```python
A, B = 1, 2
```

### Chained

```python
A = B = 1
```

### Nested

```python
import sys

if sys.platform == 'darwin':
    A = 1
else:
    A = 2
```

### Not module

```python
class C:
    LIMIT = 3


def f() -> None:
    LIMIT = 4
    print(LIMIT)
```
