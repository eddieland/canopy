"""The `final-constants` codemod: what it annotates, what it leaves alone, and that it has nothing to do twice."""

from typing import Final

import pytest
from canopy_codemods import run
from canopy_codemods.final_constants import FinalConstants, constants

NAME: Final = "final-constants"


def rewrite(source: str) -> str:
    return run.rewrite(source, [NAME])


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param("LIMIT = 3\n", "from typing import Final\n\nLIMIT: Final = 3\n", id="plain"),
        pytest.param("_LIMIT = 3\n", "from typing import Final\n\n_LIMIT: Final = 3\n", id="private"),
        pytest.param(
            "from collections.abc import Sequence\n\nNAMES: Sequence[str] = ()\n",
            "from collections.abc import Sequence\nfrom typing import Final\n\nNAMES: Final[Sequence[str]] = ()\n",
            id="annotated",
        ),
        pytest.param(
            "from typing import Any\n\nA = 1\n",
            # Unsorted, as libcst adds it: ruff sorts it next (`make fmt`).
            "from typing import Final, Any\n\nA: Final = 1\n",
            id="joins-the-import-of-typing",
        ),
        pytest.param(
            "from typing import Final\n\nA: Final = 1\nB = 2\n",
            "from typing import Final\n\nA: Final = 1\nB: Final = 2\n",
            id="beside-one-already-final",
        ),
        pytest.param(
            '"""Doc."""\n\n#: What it is.\nA = (\n    1,  # one\n    2,\n)  # why\n',
            '"""Doc."""\nfrom typing import Final\n\n#: What it is.\nA: Final = (\n    1,  # one\n    2,\n)  # why\n',
            id="keeps-comments-and-layout",
        ),
        pytest.param("A = 1; B = 2\n", "from typing import Final\n\nA: Final = 1; B: Final = 2\n", id="one-line"),
        pytest.param(
            "A = 1\n\n\ndef f() -> None:\n    A = 2\n    print(A)\n",
            "from typing import Final\n\nA: Final = 1\n\n\ndef f() -> None:\n    A = 2\n    print(A)\n",
            id="a-local-of-the-same-name-is-another-name",
        ),
        pytest.param(
            "class Kind:\n    ROW = 1\n\n\nROW = Kind.ROW\n",
            "from typing import Final\n\nclass Kind:\n    ROW = 1\n\n\nROW: Final = Kind.ROW\n",
            id="a-class-attribute-of-the-same-name-is-another-name",
        ),
    ],
)
def test_a_module_constant_is_annotated_final(before: str, after: str) -> None:
    assert rewrite(before) == after
    assert rewrite(after) == after
    assert not FinalConstants.wants(after)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import logging\n\n_log = logging.getLogger(__name__)\nrouter = object()\n", id="lowercase"),
        pytest.param("__all__ = ['a']\n__version__ = '1'\n", id="dunder"),
        pytest.param("Alias = dict[str, int]\n", id="camel-case"),
        pytest.param("import logging\n\nLOG = logging.getLogger(__name__)\n", id="logger"),
        pytest.param("import threading\n\n_LOCK = threading.Lock()\n", id="lock"),
        pytest.param("from contextvars import ContextVar\n\nTICK: ContextVar[str] = ContextVar('tick')\n", id="var"),
        pytest.param("from typing import TypeVar\n\nT = TypeVar('T')\n", id="type-variable"),
        pytest.param("from typing import TypeAlias\n\nJSON: TypeAlias = dict[str, object]\n", id="type-alias"),
        pytest.param("import typing\n\nA: typing.Final = 1\nB: typing.Final[int] = 2\n", id="final-already"),
        pytest.param("A: 'Final[int]' = 1\n", id="final-already-quoted"),
        pytest.param("A: int\n", id="declared-without-a-value"),
        pytest.param("A = 1\nA = 2\n", id="assigned-twice"),
        pytest.param("A = 1\nA += 1\n", id="augmented"),
        pytest.param("A = 1\ndel A\n", id="deleted"),
        pytest.param("A = 1\nfor A in ():\n    pass\n", id="loop-variable"),
        pytest.param("A = 1\nwith open('f') as A:\n    pass\n", id="with-target"),
        pytest.param("A = None\ntry:\n    import a as A\nexcept ImportError:\n    pass\n", id="imported"),
        pytest.param("A = 0\n\n\ndef bump() -> None:\n    global A\n    A += 1\n", id="global"),
        pytest.param("A = 0\nprint(A := 1)\n", id="walrus"),
        pytest.param("A, B = 1, 2\n", id="unpacked"),
        pytest.param("A = B = 1\n", id="chained"),
        pytest.param("import sys\n\nif sys.platform == 'darwin':\n    A = 1\nelse:\n    A = 2\n", id="nested"),
        pytest.param(
            "class C:\n    LIMIT = 3\n\n\ndef f() -> None:\n    LIMIT = 4\n    print(LIMIT)\n",
            id="not-module",
        ),
    ],
)
def test_what_is_not_a_constant_is_left_alone(source: str) -> None:
    assert not constants(source)
    assert not FinalConstants.wants(source)
    assert rewrite(source) == source


def test_a_module_that_does_not_parse_is_wanted_so_that_it_is_reported() -> None:
    assert FinalConstants.wants("A = (\n")
    with pytest.raises(run.CodemodError, match="final-constants"):
        rewrite("A = (\n")
