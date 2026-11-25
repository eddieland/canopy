"""The models OpenCode 2 lists to run an agent on, asked of a private `opencode serve` as OpenCode 2.3.0 answers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final
from unittest import mock

import pytest

from canopy.infra import procs
from canopy.runtime.opencode2 import models
from canopy.runtime.report import ModelLimits, ModelList

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

#: What OpenCode 2.1.4 listed in a workspace whose config adds a provider, `stub`, cut to three of its models: one of
#: its own with no variants, one whose `id` is not its `modelID`, and the config's, its key in its `settings`.
RECORDED: Final = Path(__file__).parent / "recorded" / "model-list.json"
URL: Final = "http://127.0.0.1:41234"
#: The models of OpenCode's catalog, which it lists until a provider has fetched its own, and the provider's own: the
#: models the account has, and its router, which no catalog names.
CATALOG: Final = ("github-copilot/gpt-5", "github-copilot/claude-x")
FETCHED: Final = ("github-copilot/gpt-5", "github-copilot/auto")


def listing(*entries: object) -> str:
    return json.dumps({"location": {"directory": "/ws"}, "data": entries})


def named(*names: str) -> str:
    """A list of the models `names`, each `provider/model`, with no variants."""
    return listing(*({"providerID": n.split("/")[0], "id": n.split("/")[1]} for n in names))


@dataclass
class Serve:
    """Plays `opencode serve` and `opencode api --server`, its lists as given, and records what ran."""

    #: Each answer of `model.list` in turn, the last kept once they run out.
    lists: Sequence[str]
    #: How many times `plugin.list` answers with no plugin, before they load.
    loading: int = 0
    #: What answers in place of the play, for a command it is given.
    fail: Callable[[Sequence[str]], procs.Result | None] = lambda _: None
    ran: list[tuple[tuple[str, ...], Path | None, dict[str, str]]] = field(default_factory=list)

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002
        on_start: Callable[[int], None] | None = None,  # noqa: ARG002
        on_line: Callable[[str], None] | None = None,
        stdout_to_file: bool = False,
        max_stdout: int | None = None,  # noqa: ARG002
        unset: Iterable[str] = (),  # noqa: ARG002
    ) -> procs.Result:
        self.ran.append((tuple(args), cwd, dict(env or {})))
        failed = self.fail(args)
        if failed is not None:
            return failed
        match list(args):
            case ["opencode", "serve", *_]:
                assert on_line is not None
                on_line(f"server listening on {URL}\n")
                raise AssertionError("the server outlived its questions")
            case ["opencode", "api", "--server", url, "plugin.list"]:
                assert url == URL
                loaded = self.asked("plugin.list") > self.loading
                printed = json.dumps({"data": [{"id": "opencode.provider.github.copilot"}] if loaded else []})
            case ["opencode", "api", "--server", url, "model.list"]:
                assert url == URL
                # Read from a file, as OpenCode cuts what it prints to a pipe short.
                assert stdout_to_file
                printed = self.lists[min(self.asked("model.list"), len(self.lists)) - 1]
            case _:
                raise AssertionError(args)
        return procs.Result(tuple(args), 0, printed, "")

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002
        raise AssertionError(args)

    def asked(self, operation: str) -> int:
        """How many times `operation` was asked so far."""
        return sum(argv[-1] == operation for argv, _, _ in self.ran)


@pytest.fixture(autouse=True)
def no_polling_delay() -> Iterator[None]:
    """Ask again at once, so a list that fills as it is asked costs a test no time."""
    with mock.patch.object(models, "POLL_SECONDS", 0):
        yield


def test_a_recorded_list_gives_each_model_by_its_provider_and_id() -> None:
    serve = Serve([RECORDED.read_text()])
    assert models.listed(serve, cwd=Path("/ws")) == ModelList(
        frozenset({"opencode/mimo-v2.6-flash-free", "github-copilot/claude-opus-4.8-fast", "stub/stub-1"}),
        limits={
            # The provider's own model lists the input a call may send, short of its context; the others only the
            # context.
            "github-copilot/claude-opus-4.8-fast": ModelLimits(input=168000, context=200000),
            "opencode/mimo-v2.6-flash-free": ModelLimits(input=None, context=200000),
            "stub/stub-1": ModelLimits(input=None, context=200000),
        },
    )
    # A server started where the caller says, on loopback, and each question asked with its password, one canopy made.
    serve_argv, cwd, env = serve.ran[0]
    assert serve_argv == ("opencode", "serve", "--hostname", "127.0.0.1", "--port", "0")
    assert cwd == Path("/ws")
    assert len(env["OPENCODE_PASSWORD"]) >= 32
    assert all(e == env for _, _, e in serve.ran)


def test_with_variants_each_models_variants_are_read_in_its_order() -> None:
    assert models.listed(Serve([RECORDED.read_text()]), cwd=Path("/ws"), variants=True).variants == {
        "opencode/mimo-v2.6-flash-free": (),
        "github-copilot/claude-opus-4.8-fast": ("low", "medium", "high", "xhigh", "max"),
        "stub/stub-1": ("deep",),
    }


def test_an_entry_that_names_no_model_canopy_renders_is_passed_over() -> None:
    printed = listing(
        {"providerID": "anthropic", "id": "claude-x", "variants": [{"id": "high"}]},
        {"providerID": "", "id": "nameless"},
        {"providerID": "bad provider", "id": "x"},
    )
    assert models.listed(Serve([printed]), cwd=Path("/ws"), variants=True) == ModelList(
        frozenset({"anthropic/claude-x"}),
        {"anthropic/claude-x": ("high",)},
    )


def test_a_limit_canopy_cannot_read_is_none_and_fails_no_read_of_the_list() -> None:
    printed = listing(
        {"providerID": "a", "id": "both", "limit": {"context": 200000, "input": 64000, "output": 16000}},
        {"providerID": "a", "id": "input", "limit": {"input": 64000, "context": "lots"}},
        {"providerID": "a", "id": "odd", "limit": {"context": 0, "input": True}},
        {"providerID": "a", "id": "huge", "limit": {"context": 10**20, "input": 2.5}},
        {"providerID": "a", "id": "listless", "limit": [1, 2]},
        {"providerID": "a", "id": "none"},
    )
    found = models.listed(Serve([printed]), cwd=Path("/ws"))
    assert found.models == frozenset({"a/both", "a/input", "a/odd", "a/huge", "a/listless", "a/none"})
    assert found.limits == {
        "a/both": ModelLimits(input=64000, context=200000),
        "a/input": ModelLimits(input=64000, context=None),
    }


def test_an_opencode_with_no_provider_lists_no_model() -> None:
    assert models.listed(Serve([listing()]), cwd=Path("/ws")) == ModelList()


def test_the_list_is_asked_only_once_the_plugins_have_loaded() -> None:
    serve = Serve([named(*FETCHED)], loading=2)
    assert models.listed(serve, cwd=Path("/ws")).models == frozenset(FETCHED)
    assert [argv[-1] for argv, _, _ in serve.ran[1:4]] == ["plugin.list"] * 3
    assert serve.ran[4][0][-1] == "model.list"


def test_a_server_whose_plugins_never_load_fails() -> None:
    with mock.patch.object(models, "LOADED_SECONDS", 0):
        found = models.listed(Serve([named(*FETCHED)], loading=1000), cwd=Path("/ws"))
    assert found == ModelList(error="`opencode serve` had loaded no plugin after 0 seconds")


def test_a_model_asked_about_is_waited_for_while_its_provider_fetches_its_own() -> None:
    # The catalog's list twice, then the provider's own, its router among them.
    serve = Serve([named(*CATALOG), named(*CATALOG), named(*FETCHED)])
    with mock.patch.object(models, "WANTED_SECONDS", 60):
        found = models.listed(serve, cwd=Path("/ws"), wanted="github-copilot/auto")
    assert found.models == frozenset(FETCHED)
    assert serve.asked("model.list") == 3


def test_a_model_asked_about_and_listed_is_not_waited_for() -> None:
    serve = Serve([named(*CATALOG), named(*FETCHED)])
    assert models.listed(serve, cwd=Path("/ws"), wanted="github-copilot/gpt-5").models == frozenset(CATALOG)
    assert serve.asked("model.list") == 1


def test_a_model_never_listed_is_waited_for_only_so_long() -> None:
    serve = Serve([named(*CATALOG)])
    with mock.patch.object(models, "WANTED_SECONDS", 0.05):
        found = models.listed(serve, cwd=Path("/ws"), wanted="github-copilot/auto")
    assert found.models == frozenset(CATALOG)
    assert serve.asked("model.list") > 1


def test_with_no_model_asked_about_the_list_is_read_until_it_holds_still() -> None:
    # It changes on the fourth answer, and is taken once it has answered the same for the time it must.
    serve = Serve([named(*CATALOG)] * 3 + [named(*FETCHED)])
    with mock.patch.object(models, "SETTLE_SECONDS", 0.05):
        found = models.listed(serve, cwd=Path("/ws"))
    assert found.models == frozenset(FETCHED)


def test_a_list_that_cannot_be_read_says_why_in_canopy_s_words() -> None:
    def exits(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), 1, "", "") if args[-1] == "model.list" else None

    assert models.listed(Serve([], fail=exits), cwd=Path("/ws")) == ModelList(
        error="`opencode api model.list` exited 1",
    )

    # What it printed is not quoted: a model's settings may hold a provider's key.
    for printed in ('{"data": [{"providerID": "x", "settings": {"apiKey": "sk-s3cret"}}]}', "not json"):
        found = models.listed(Serve([printed]), cwd=Path("/ws"))
        assert found == ModelList(error="`opencode api model.list` printed what canopy cannot read")


def test_a_server_that_cannot_start_fails() -> None:
    def gone(args: Sequence[str]) -> procs.Result | None:
        raise procs.CommandNotFoundError(args[0])

    assert models.listed(Serve([], fail=gone), cwd=Path("/ws")) == ModelList(error="opencode is not on PATH")

    def exits(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), 2, "", "")

    assert models.listed(Serve([], fail=exits), cwd=Path("/ws")).error == "`opencode serve` exited 2; run it to see why"
