"""The model list the server keeps (DESIGN §13): read from the runtime once, then served until it is minutes old.

A read starts the runtime for seconds, so the Model panel's menus and a choice's check share one list; the loop reading
its config again, a refresh, or a read that failed asks the runtime anew.
"""

import dataclasses
import json
from pathlib import Path

import httpx2

from canopy.core.context import Context
from canopy.loop import reread, tick_now, web
from canopy.runtime.implementation import Version
from canopy.runtime.report import ModelList
from canopy.serve.backend import MODEL_LIST_SECONDS, Backend
from tests.canopy.helpers import KEY, FakeTime
from tests.canopy.web_helpers import refused, signed_in_client


def test_the_model_list_is_read_once_for_the_menus_and_a_choice_until_refreshed(
    ctx: Context,
    opencode_state: Path,
) -> None:
    lists(opencode_state, "acme/fake-model-1")
    c, headers = signed_in_client(ctx)
    expected: dict[str, object] = {"models": ["acme/fake-model-1"], "variants": {}, "error": None}

    def choose(model: str) -> httpx2.Response:
        return c.post(f"/api/tickets/{KEY}/models", json={"model": model}, headers=headers)

    assert c.get("/api/models").json() == expected
    assert c.get("/api/models").json() == expected
    # A choice is checked against the same list, with no runtime started for it.
    assert choose("acme/fake-model-1").json()["model"] == "acme/fake-model-1"
    assert runtime_runs(opencode_state) == 1

    # A refresh asks the runtime now, and what it lists is the list kept from then on.
    lists(opencode_state, "acme/fake-model-2")
    assert c.get("/api/models", params={"refresh": 1}).json()["models"] == ["acme/fake-model-2"]
    assert runtime_runs(opencode_state) == 2
    # A model the kept list lacks is looked up again before it is refused, so one set up since is not.
    assert refused(choose("acme/fake-model-1")).startswith("unknown_model: ")
    assert runtime_runs(opencode_state) == 3
    lists(opencode_state, "acme/fake-model-2", "acme/fake-model-3")
    assert choose("acme/fake-model-3").json()["model"] == "acme/fake-model-3"
    assert runtime_runs(opencode_state) == 4
    assert choose("acme/fake-model-2").json()["model"] == "acme/fake-model-2"
    assert runtime_runs(opencode_state) == 4


def test_a_list_that_could_not_be_read_is_never_kept(ctx: Context, opencode_state: Path) -> None:
    backend, _ = kept(ctx)
    opencode_state.write_text(json.dumps({"exit": 1}))
    assert listed(backend).error == "`opencode models --verbose` exited 1"

    # The runtime is asked again at once, and then answers.
    lists(opencode_state, "acme/fake-model-1")
    assert listed(backend).models == {"acme/fake-model-1"}
    assert listed(backend).models == {"acme/fake-model-1"}
    assert runtime_runs(opencode_state) == 2

    # A refresh that fails drops the list it had, so the next read asks again rather than serve the old one.
    opencode_state.write_text(json.dumps({"exit": 1}))
    assert listed(backend, refresh=True).error is not None
    lists(opencode_state, "acme/fake-model-2")
    assert listed(backend).models == {"acme/fake-model-2"}
    assert runtime_runs(opencode_state) == 4


def test_the_model_list_is_read_again_once_it_is_minutes_old(ctx: Context, opencode_state: Path) -> None:
    backend, time = kept(ctx)
    lists(opencode_state, "acme/fake-model-1")
    assert listed(backend).models == {"acme/fake-model-1"}

    lists(opencode_state, "acme/fake-model-2")
    time.sleep(MODEL_LIST_SECONDS - 1)
    assert listed(backend).models == {"acme/fake-model-1"}
    time.sleep(1)
    assert listed(backend).models == {"acme/fake-model-2"}
    assert runtime_runs(opencode_state) == 2


def test_the_model_list_is_read_again_when_the_loop_reads_its_config_again(ctx: Context, opencode_state: Path) -> None:
    backend, _ = kept(ctx)
    lists(opencode_state, "acme/fake-model-1")
    assert listed(backend).models == {"acme/fake-model-1"}

    # Even a config that changes nothing the list depends on: what changed is not the server's to judge.
    lists(opencode_state, "acme/fake-model-2")
    backend.use(backend.config.model_copy(), backend.workspace)
    assert listed(backend).models == {"acme/fake-model-2"}

    # Another runtime version is asked in its own way.
    runtime = backend.config.runtime.model_copy(update={"version": Version.TWO})
    backend.use(backend.config.model_copy(update={"runtime": runtime}), backend.workspace)
    assert listed(backend).models == {"acme/fake-model-2"}
    argvs = [json.loads(line)["argv"] for line in log(opencode_state).read_text().splitlines()]
    assert [a[:1] for a in argvs] == [["models"], ["models"], ["api"]]


def kept(ctx: Context) -> tuple[Backend, FakeTime]:
    """The server's backend as the loop builds it over `ctx`, on a clock only the test moves."""
    time = FakeTime()
    backend = web.backend(ctx, reread.Reload(), tick_now.TickNow(), None)
    return dataclasses.replace(backend, monotonic=time.clock), time


def listed(backend: Backend, *, refresh: bool = False) -> ModelList:
    """The model list `backend` serves a request opened now."""
    with backend.open() as opened:
        return backend.model_list(opened, refresh=refresh)


def lists(state: Path, *models: str) -> None:
    """Have the fake `opencode` list `models` from now on."""
    state.write_text(json.dumps({"models": list(models)}))


def runtime_runs(state: Path) -> int:
    """How many times the fake `opencode` was started."""
    found = log(state)
    return len(found.read_text().splitlines()) if found.exists() else 0


def log(state: Path) -> Path:
    """The file the fake `opencode` appends each run to."""
    return state.with_name("opencode.jsonl")
