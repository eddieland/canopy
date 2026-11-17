"""The models OpenCode 2 lists to run an agent on (DESIGN §13), asked of a private server as OpenCode 2.3.0 answers.

`model.list` answers `{location, data}`: each model in `data` as an object whose `providerID` and `id` name it,
`provider/model`, and whose `variants` are the variants a run on it may use, each an object with an `id`, those
OpenCode derives for the model and the provider's config adds. It is the same list `opencode models` prints a line
each, `providerID/id`, which has no option to print the variants. A run's agent is looked up in it: OpenCode 2 refuses
a variant the model lacks before the first call, but tries a model the list lacks on the provider, so canopy looks the
model up first.

The list is not whole when the server starts. It holds the models of OpenCode's catalog until its plugins have loaded,
and a provider that fetches its own models, as GitHub Copilot does, replaces its part only once that fetch ends: the
models the account has, and a router of the provider's own, `github-copilot/auto`, that no catalog names. Nothing the
server answers says the fetches have ended. So canopy asks a server it starts (`canopy.runtime.opencode2.serve`) and
not `opencode api --standalone`, whose server answers once and is gone: `plugin.list` until it names a plugin, then
`model.list` until the answer has held still for `SETTLE_SECONDS`, or, asked about one model, until the list holds it,
at most `WANTED_SECONDS`. A run waits the same way before its first prompt (the plugin's `listedModel`, DESIGN §33).

Only `providerID`, `id`, and the variants' `id` are read: a model's `settings` and `headers` may hold a provider's key,
so no failure quotes what was printed. An entry that does not name a model canopy renders is passed over.

OpenCode 2.1.2 ran a primary agent on the default model, whatever its definition named; 2.1.4 runs it on the
definition's model and variant, so a model chosen in config needs 2.1.4 or later.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from canopy.runtime.opencode2.definitions import MODEL_RE
from canopy.runtime.opencode2.serve import OPENCODE, Client, FailedError, Serve, read
from canopy.runtime.report import ModelList

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.infra import procs

#: How long the server's plugins may take to load, and how long to wait between two questions of it.
LOADED_SECONDS = 30
POLL_SECONDS = 0.25
#: How long the list must answer the same to be taken as whole, when no one model is asked about.
SETTLE_SECONDS = 3.0
#: How long a list that lacks the model asked about is read again: a provider's fetch of its own models, which
#: OpenCode itself gives up on after seconds.
WANTED_SECONDS = 15


class _Variant(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    id: StrictStr


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    provider: StrictStr = Field(alias="providerID")
    id: StrictStr
    variants: tuple[_Variant, ...] = ()


class _Models(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    data: tuple[_Model, ...]


class _Plugins(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    # Only whether there is one is read.
    data: tuple[object, ...]


def listed(runner: procs.Runner, *, cwd: Path, variants: bool = False, wanted: str | None = None) -> ModelList:
    """Ask OpenCode 2, started in `cwd`, which models it can run an agent on, and with `variants` each one's variants.

    With `wanted`, a model as `provider/model`, the list is read until it holds that model, for a provider that lists
    its own models only once it has fetched them; with none, until it has held still.

    Returns:
        The models it listed, with their variants when asked for; or none, with why, when OpenCode could not be run,
        failed, or printed what canopy cannot read.
    """
    try:
        found = Serve(runner, OPENCODE, cwd, {}).ask(lambda client: _whole(client, wanted))
    except FailedError as e:
        return ModelList(error=str(e))
    return ModelList(frozenset(found), found if variants else {})


def _whole(client: Client, wanted: str | None) -> dict[str, tuple[str, ...]]:
    """Ask the server its models once its plugins have loaded, until the list is whole as far as canopy can tell.

    Returns:
        Each model canopy renders, by its name, with its variants.

    Raises:
        FailedError: An answer could not be read, or no plugin had loaded within `LOADED_SECONDS`.
    """
    deadline = time.monotonic() + LOADED_SECONDS
    while not read(client.get("plugin.list"), _Plugins.model_validate_json, "plugin.list").data:
        if time.monotonic() >= deadline:
            raise FailedError(f"`opencode serve` had loaded no plugin after {LOADED_SECONDS} seconds")
        time.sleep(POLL_SECONDS)
    started = since = time.monotonic()
    found = _models(client)
    while True:
        now = time.monotonic()
        if wanted is None:
            if now - since >= SETTLE_SECONDS:
                return found
        elif wanted in found or now - started >= WANTED_SECONDS:
            return found
        time.sleep(POLL_SECONDS)
        again = _models(client)
        if again != found:
            found, since = again, time.monotonic()


def _models(client: Client) -> dict[str, tuple[str, ...]]:
    printed = read(client.get("model.list"), _Models.model_validate_json, "model.list")
    return {
        name: tuple(v.id for v in model.variants)
        for model in printed.data
        if MODEL_RE.fullmatch(name := f"{model.provider}/{model.id}")
    }
