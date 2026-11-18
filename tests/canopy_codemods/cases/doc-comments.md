# `doc-comments`

Each case is a module's text. Under Rewritten, a case is the text before and the text after; under Left alone, text
the codemod does not change. `test_doc_comments.py` runs them.

## Rewritten

### A constant

```python
# How many times a run is resumed before it is given up.
MAX_RESUMES: Final = 3
```

```python
#: How many times a run is resumed before it is given up.
MAX_RESUMES: Final = 3
```

### A block of several lines, with an empty one

```python
import re

# A key a tracker gives a ticket.
#
# Letters, a hyphen, and a number.
_KEY = re.compile(r"[A-Z]+-[0-9]+")
```

```python
import re

#: A key a tracker gives a ticket.
#:
#: Letters, a hyphen, and a number.
_KEY = re.compile(r"[A-Z]+-[0-9]+")
```

### A type alias

```python
# How a run ended.
type Outcome = Literal["packed", "failed"]
# A login, checked.
Login = Annotated[str, AfterValidator(check)]
```

```python
#: How a run ended.
type Outcome = Literal["packed", "failed"]
#: A login, checked.
Login = Annotated[str, AfterValidator(check)]
```

### Only the block that touches the name

```python
# A note on the module, a blank line away.

# The most a note holds.
LIMIT: Final = 400
```

```python
# A note on the module, a blank line away.

#: The most a note holds.
LIMIT: Final = 400
```

### A value of several lines, and the constant after it

```python
# The first.
NAMES: Final = (
    # Not this one, inside the value.
    "a",
)
# The second.
OTHER: Final = 2
```

```python
#: The first.
NAMES: Final = (
    # Not this one, inside the value.
    "a",
)
#: The second.
OTHER: Final = 2
```

### A dataclass's fields

```python
@dataclass(frozen=True)
class Rewrite:
    """What the codemods made of one file."""

    path: Path
    # The file's text as it was read.
    before: str
    # Why a codemod could not run, or None.
    error: str | None = None
    # How many there may be.
    limit: ClassVar[int] = 3
```

```python
@dataclass(frozen=True)
class Rewrite:
    """What the codemods made of one file."""

    path: Path
    #: The file's text as it was read.
    before: str
    #: Why a codemod could not run, or None.
    error: str | None = None
    #: How many there may be.
    limit: ClassVar[int] = 3
```

### A dataclass by its dotted name, with no docstring

```python
@dataclasses.dataclass
class Point:
    # Across.
    x: int
```

```python
@dataclasses.dataclass
class Point:
    #: Across.
    x: int
```

### A NamedTuple's fields

```python
class Cases(typing.NamedTuple):
    # A module's text before and after.
    rewritten: list[str]
```

```python
class Cases(typing.NamedTuple):
    #: A module's text before and after.
    rewritten: list[str]
```

### An enum's members

```python
class Draft(StrEnum):
    """Where a draft stands."""

    # Checked, and the operator's to send.
    WAITING = "waiting"
    SENT = "sent"


class Bits(enum.IntFlag):
    # The first.
    ONE = 1
```

```python
class Draft(StrEnum):
    """Where a draft stands."""

    #: Checked, and the operator's to send.
    WAITING = "waiting"
    SENT = "sent"


class Bits(enum.IntFlag):
    #: The first.
    ONE = 1
```

### A class inside a function or another class

```python
def make():
    @dataclass
    class Local:
        # Its name.
        name: str

    return Local


class Outer:
    class Kind(Enum):
        # The only one.
        ONLY = 1
```

```python
def make():
    @dataclass
    class Local:
        #: Its name.
        name: str

    return Local


class Outer:
    class Kind(Enum):
        #: The only one.
        ONLY = 1
```

### A comment that already holds a colon or a hash

```python
# `#` opens a comment: this one.
MARK: Final = "#"
```

```python
#: `#` opens a comment: this one.
MARK: Final = "#"
```

## Left alone

### Already a doc comment

```python
#: The most a note holds.
LIMIT: Final = 400
```

### A block with a doc comment in it

```python
# Kept as the author wrote it.
#: The most a note holds.
LIMIT: Final = 400
```

### A blank line between

```python
# Limits.

LIMIT: Final = 400
```

### A pydantic model's field

```python
class Ticket(Model):
    # Kept out of the schema.
    key: str
    """The ticket's key."""


class Policy(BaseModel):
    # Not read by pydantic.
    max_workers: int = 3
```

### Any other class's attribute

```python
class Reader:
    # Not a field the class statement declares.
    limit = 3
```

### A lowercase module object

```python
# One per module.
_log = logging.getLogger(__name__)
# The routes.
router: APIRouter = APIRouter()
```

### A function, a class, and an import

```python
# Sorted last.
import os


# Called once.
def main() -> None:
    # A local.
    LIMIT = 3


# A reader.
class Reader:
    # A method.
    def read(self) -> None:
        # Another local.
        self.limit = 3
```

### A method's locals in a dataclass

```python
@dataclass
class Point:
    x: int

    def moved(self) -> Point:
        # Not a field.
        x = self.x + 1
        return Point(x)
```

### A directive to a tool

```python
# fmt: off
TABLE: Final = [
    1, 2,
]
# The names.
# pyrefly: ignore[bad-assignment]
NAMES: Final[int] = ()
# noqa: ERA001
OTHER: Final = 1
# type: ignore
THIRD: Final = 1
```

### A shebang

```python
#!/usr/bin/env python3
LIMIT: Final = 3
```

### A section's banner

```python
# ---- Limits ----
LIMIT: Final = 400
# ====
OTHER: Final = 1
# Limits -----------------
# The third.
THIRD: Final = 1
```

### An assignment to several names, or to none of its own

```python
# Both.
A, B = 1, 2
# Twice.
C = D = 3
# An item.
TABLE["key"] = 1
# An attribute.
config.LIMIT = 3
```

### An assignment nested in another statement

```python
if sys.platform == "darwin":
    # Where the cache is.
    CACHE: Final = "Library/Caches"
```

### The comment that closes the block above

```python
def main() -> None:
    pass
    # The end of main.
LIMIT: Final = 3
```

### A string that ends like a comment

```python
TEXT: Final = """
# A heading in the text."""
LIMIT: Final = 3
```

### A comment beside the value

```python
LIMIT: Final = 3  # The most a note holds.
OTHER: Final = 4
```
