"""The config keys a person or an agent tunes: each one's value, its default, its bounds, and the file that set it.

`canopy config show` prints them, so a chore that recommends a setting can see what it is now and whether a file set
it, and name only keys that exist. Only a number, a switch, or a choice is shown, each chore's among them: a key that
holds text, a command, a path, or a table of those may name a host, carry a token, or say what the operator kept off
the tracker, and an agent that reads this reports what it reads. It reads only, so the overseer's reach to it changes
nothing it can do.
"""

from __future__ import annotations

import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Annotated, Literal, Union, get_args, get_origin

from pydantic.fields import FieldInfo

from canopy.core import config

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.config import Config


class Layer(StrEnum):
    """The config file a key's value came from, as `config.load` merges them (DESIGN §12)."""

    WORKSPACE = "workspace"
    USER = "user"
    PRIVATE = "private"


#: A value as JSON holds it: a number, a switch, a choice, a list of choices, or None for unset.
Value = int | float | bool | str | Sequence[str] | None


@dataclass(frozen=True)
class Setting:
    """One key `canopy config show` prints."""

    #: Its name, `section.key`, or `chores.<name>.<key>` for one chore's.
    key: str
    value: Value
    #: Its built-in default; None for a key with no default, which `required` says.
    default: Value
    #: The file that set it, or None when it is the default.
    set_in: Layer | None
    #: Whether every table of its kind must set it, as a chore's `every_minutes`: it has no default.
    required: bool = False
    #: The values a choice may take, empty for a number or a switch.
    choices: Sequence[str] = ()
    #: The least and the most a number may be, where the schema bounds it.
    minimum: int | float | None = None
    maximum: int | float | None = None


def settings(cfg: Config, origin: Mapping[str, Path], files: tuple[Path, Path, Path]) -> list[Setting]:
    """Return the keys shown, in the schema's order, then each chore's, by name.

    `origin` is `config.origins`, and `files` is `config.config_files`, for the workspace `cfg` was loaded for.

    Returns:
        A setting for every number, switch, and choice in the schema, and in each chore's table.
    """
    layers = dict(zip(files, Layer, strict=True))
    found: list[Setting] = []
    for name, spec in config.SPECS.items():
        if name in config.TABLE_SECTIONS:
            continue
        section, key = name.split(".", 1)
        set_in = layers[origin[name]] if name in origin else None
        shown = _setting(name, spec.field, getattr(getattr(cfg, section), key), set_in)
        if shown is not None:
            found.append(shown)
    chores_from = layers[origin["chores"]] if "chores" in origin else None
    for chore, table in sorted(cfg.chores.items()):
        for key, field in config.Chore.model_fields.items():
            set_in = chores_from if key in table.model_fields_set else None
            shown = _setting(f"chores.{chore}.{key}", field, getattr(table, key), set_in)
            if shown is not None:
                found.append(shown)
    return found


# The setting of a key shown, or None for one that is not a number, a switch, or a choice.
def _setting(name: str, field: FieldInfo, value: object, set_in: Layer | None) -> Setting | None:
    kind = _kind(field.annotation)
    if kind is None:
        return None
    low, high = _bounds(field)
    required = field.is_required()
    default = None if required else field.default
    return Setting(name, _json(value), _json(default), set_in, required, kind, low, high)


# The choices of an annotation that is a number, a switch, or a choice, optional or a tuple of choices: empty for a
# number or a switch; None for anything else.
def _kind(annotation: object) -> tuple[str, ...] | None:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        return _kind(args[0])
    if origin in (Union, types.UnionType):
        kept = [a for a in args if a is not type(None)]
        return _kind(kept[0]) if len(kept) == 1 else None
    if origin is tuple:
        # `tuple[Choice, ...]` is several of a choice's values; a tuple of anything else is left out.
        return (_kind(args[0]) or None) if args[1:] == (Ellipsis,) else None
    return _choices(annotation)


def _choices(annotation: object) -> tuple[str, ...] | None:
    if get_origin(annotation) is Literal:
        return tuple(str(a) for a in get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return tuple(str(m.value) for m in annotation)
    return () if annotation in (int, float, bool) else None


# The bounds the schema puts on a number, from its field's constraints and those of the type it is optional of.
def _bounds(field: FieldInfo) -> tuple[int | float | None, int | float | None]:
    low: int | float | None = None
    high: int | float | None = None
    for c in _constraints(field.metadata, field.annotation):
        for name in ("ge", "gt"):
            n = getattr(c, name, None)
            low = n if isinstance(n, int | float) else low
        for name in ("le", "lt"):
            n = getattr(c, name, None)
            high = n if isinstance(n, int | float) else high
    return low, high


def _constraints(metadata: Sequence[object], annotation: object) -> list[object]:
    found = list(metadata)
    for arg in get_args(annotation):
        if get_origin(arg) is Annotated:
            for m in get_args(arg)[1:]:
                found.extend(m.metadata if isinstance(m, FieldInfo) else [m])
    return [c for c in found if not isinstance(c, FieldInfo)]


def _json(value: object) -> Value:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, tuple):
        return [str(v) for v in value]
    if value is None or isinstance(value, int | float | str):
        return value
    raise TypeError(f"not a setting's value: {value!r}")
