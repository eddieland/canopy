"""An agent's result, reported by calling canopy's `result` tool as the last thing it does (DESIGN §13).

A worker, a planner, a reviewer, a one-off task's worker, or a chore's agent reports how its run ended by calling
`result`, a tool of a server canopy gives the run, with its result's fields as the call's arguments. So the runtime
writes the JSON, the tool's input schema says what each field is, and the server refuses a result that does not
validate while the agent can still send it again. The server writes nothing: the harness reads the last call the server
took from the events the agent prints, as it reads a `status` update (`core.cards`), and holds it to the same input. So
nothing the agent writes reaches the journal but what canopy observes it print (TRUST_MODEL T1).

What a run reports is its `Contract`: the fields every run of its kind reports, and groups of fields only some are asked
for, such as memory's while a tier of it is on. The run is told which in `CANOPY_RESULT`, the contract's name and the
groups asked of it, so its tool lists the fields this run reports and no others, and refuses any other.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from canopy.runtime import servers
from canopy.runtime.watch import Watch

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from canopy.runtime.implementation import Version
    from canopy.runtime.report import Called

#: The tool, as its server names it: the agent sees it as `<server>_result`.
TOOL = "result"
#: The variable that says what the run reports: its contract's name, then, after a colon, the groups asked of it,
#: joined by commas, as `worker:created,notes`.
ENV = "CANOPY_RESULT"
#: What a note says of a run that ended without one.
MISSING = "reported no result"
#: What the tool says of itself to every agent that reports with it, after what its result is.
REPORTING = (
    "Call it once, as the last thing you do: it is how your run reports, and nothing you print is read as a result. "
    "A refusal names the field that is wrong; fix it and call again. Once it is taken, end your run, and call it "
    "again only to correct it. It changes nothing: canopy reads the call when your run ends."
)
#: What a `status` of `blocked` or `failed` says, after what `done` means for the run's kind.
ENDED = (
    "`blocked` when you cannot go on without the operator's answer, which `question` asks; `failed` when you could "
    "not do it, with why in `summary`."
)
# A contract's name and a group's: a word of the variable's value.
_WORD_RE = re.compile(r"[a-z][a-z_]{0,39}")
# How many groups a value may name: more than any contract has.
_MAX_GROUPS = 20


# Compared by identity: a contract is one of a few constants, and so the key its inputs are kept by.
@dataclass(frozen=True, eq=False)
class Contract:
    """What a kind of run reports: the fields of its result, and the groups of fields only some runs are asked for."""

    #: Its name, as `CANOPY_RESULT` gives it.
    name: str
    #: What the tool does and when to call it, for the model.
    description: str
    #: The fields every run of it reports: its result contract, each with its description.
    model: type[BaseModel]
    #: The fields only some runs are asked for, by the group's name: a model whose fields join the result's.
    groups: Mapping[str, type[BaseModel]] = field(default_factory=dict)

    def input(self, asked: Collection[str] = ()) -> type[BaseModel]:
        """The tool's input for a run asked for the groups `asked`: the result's fields, and those groups'.

        A field no part of it names is refused, so an agent that sends a field its run was not asked for is told so.

        Returns:
            The model, the same one for the same groups; a group the contract does not have adds nothing.
        """
        return _input(self, frozenset(asked) & frozenset(self.groups))

    def asked(self, groups: Collection[str] = ()) -> Asked:
        """What a run of it asked for `groups` reports.

        Returns:
            The contract with those of `groups` it has.
        """
        return Asked(self, frozenset(groups) & frozenset(self.groups))


@dataclass(frozen=True)
class Asked:
    """What one run reports: its contract, and the groups of fields it is asked for."""

    contract: Contract
    groups: frozenset[str] = frozenset()

    def input(self) -> type[BaseModel]:
        """The tool's input for this run, which the harness holds a call to as the server does.

        Returns:
            The contract's input for the groups asked.
        """
        return self.contract.input(self.groups)

    def env(self) -> dict[str, str]:
        """The variable that tells the run's server what it reports.

        Returns:
            `CANOPY_RESULT`, with the contract's name and the groups asked.
        """
        return {ENV: ":".join(part for part in (self.contract.name, ",".join(sorted(self.groups))) if part)}


def markdown(limit: int) -> str:
    """What a field's description says of text the operator reads in canopy, of at most `limit` characters.

    Returns:
        The sentences, for the end of a `summary`'s or a `question`'s description.
    """
    return (
        "The operator reads it in canopy as Markdown: paragraphs, `-` and `1.` lists, `code`, fenced code, **bold**, "
        "*italics*, `>` quotes, `---` rules, and tables; a link shows its address, so write a URL as itself. At most "
        f"{limit:,} characters; the rest is cut."
    )


def asked_of(value: str, contracts: Mapping[str, Contract]) -> Asked | None:
    """What the run whose `CANOPY_RESULT` is `value` reports, among `contracts` by name.

    Returns:
        The contract and the groups asked, or None when `value` names none of `contracts`, or is not as `Asked.env`
        writes it: such a run is served no `result` tool.
    """
    name, _, rest = value.partition(":")
    groups = rest.split(",") if rest else []
    known = contracts.get(name)
    if known is None or len(groups) > _MAX_GROUPS or not all(_WORD_RE.fullmatch(group) for group in groups):
        return None
    return known.asked(groups)


def tool_name(server: str) -> str:
    """The name the agent, and the definitions' rules, know the tool by on the server `server`.

    Returns:
        `<server>_result`, as the runtime names it.
    """
    return servers.tool_name(server, TOOL)


def read_call(called: Called, asked: Asked, *, server: str) -> str | None:
    """The result a tool call the agent made reports, if it is a `result` call that completed and validates.

    A call the server refused is a tool error, which the runtime prints as failed, not completed; its input is held to
    the tool's own too, as a `status` call's is (`cards.read_call`).

    Returns:
        The call's input as one line of JSON, which a contract's readers read; None for any other call, a refused one,
        or one whose input is not this run's result.
    """
    if called.tool != tool_name(server) or not called.completed:
        return None
    try:
        asked.input().model_validate(called.input)
        return json.dumps(dict(called.input))
    except (ValidationError, TypeError, ValueError):
        return None


def reported(stdout: str, asked: Asked, *, server: str, version: Version) -> str:
    """The result an agent that printed `stdout` reported: its last `result` call the server took, or none.

    Read from the events of the runtime `version` runs, once the agent has ended, a kill at its timeout included: what
    it reported before the kill is still its result. A later call replaces an earlier one, as a correction does.

    Returns:
        The result as one line of JSON, which the contract's readers read; "" when it reported none.
    """
    watch = Watch(version=version, model=None)
    found = ""
    for line in stdout.splitlines(keepends=True):
        change = watch.read(line)
        if change is not None and change.called is not None:
            found = read_call(change.called, asked, server=server) or found
    return found


@functools.cache
def _input(contract: Contract, groups: frozenset[str]) -> type[BaseModel]:
    bases = (*(contract.groups[name] for name in sorted(groups)), contract.model)
    name = "".join(part.title() for part in (contract.name, *sorted(groups), "result")).replace("_", "")
    # A field the run was not asked for is refused, where the contract's own readers pass it over.
    strict = ConfigDict(extra="forbid", frozen=True, defer_build=True)
    return type(name, bases, {"model_config": strict, "__doc__": contract.description, "__module__": __name__})
