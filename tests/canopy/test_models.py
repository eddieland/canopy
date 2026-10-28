import importlib
import pkgutil
import sys
from typing import Final

import pydantic
import pytest

import canopy
from canopy.infra import procs

# The web server's models stay eager: FastAPI builds every one when it creates the app, so deferring them saves
# nothing, and only a serving `canopy loop` imports them.
EAGER: Final = "canopy.serve."


def canopy_models() -> list[type[pydantic.BaseModel]]:
    """Every pydantic model canopy defines outside the web server, each of its modules imported."""
    for info in pkgutil.walk_packages(canopy.__path__, "canopy."):
        if info.name != "canopy.__main__":  # it runs the CLI
            importlib.import_module(info.name)
    found: list[type[pydantic.BaseModel]] = []
    pending = [pydantic.BaseModel]
    while pending:
        for sub in pending.pop().__subclasses__():
            pending.append(sub)
            if sub.__module__.startswith("canopy.") and not sub.__module__.startswith(EAGER):
                found.append(sub)
    return sorted(found, key=lambda m: f"{m.__module__}.{m.__qualname__}")


@pytest.mark.parametrize("model", canopy_models(), ids=lambda m: f"{m.__module__}.{m.__qualname__}")
def test_a_model_defers_its_build_and_builds(model: type[pydantic.BaseModel]) -> None:
    # Deferred, a broken model would fail only where it is first used; building each one here fails it now.
    assert model.model_config.get("defer_build") is True
    assert model.model_rebuild(force=True) is True


def test_the_cli_starts_without_building_a_model() -> None:
    # The overseer and workers run `canopy` many times a tick; each start-up pays for every schema it builds.
    code = """
import canopy.cli.main, pydantic
pending, built = [pydantic.BaseModel], []
while pending:
    for sub in pending.pop().__subclasses__():
        pending.append(sub)
        if sub.__module__.startswith("canopy.") and sub.__pydantic_complete__:
            built.append(f"{sub.__module__}.{sub.__qualname__}")
print(sorted(built))
"""
    result = procs.SubprocessRunner().run([sys.executable, "-c", code])
    assert result.ok, result.stderr
    assert result.stdout.strip() == "[]"
