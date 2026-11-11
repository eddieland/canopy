"""A run's result, reported with canopy's `result` tool: its contract, the groups asked of it, and reading a call."""

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from canopy.core import run_result
from canopy.runtime.report import Called

SERVER = "canopy_run"


class _Core(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "failed"] = Field(description="How it ended.")


class _Notes(BaseModel):
    model_config = ConfigDict(frozen=True, defer_build=True)

    notes: list[str] = Field(default_factory=list, description="Notes.")


CONTRACT = run_result.Contract("worker", "Report.", _Core, {"notes": _Notes})
CONTRACTS = {CONTRACT.name: CONTRACT}


def test_a_runs_input_holds_its_contracts_fields_and_the_groups_asked_of_it() -> None:
    plain, noted = CONTRACT.input(), CONTRACT.input(["notes", "no-such-group"])
    assert set(plain.model_fields) == {"status"}
    assert set(noted.model_fields) == {"status", "notes"}
    # One model for the same groups, so a run's tool is built once.
    assert CONTRACT.input(["notes"]) is noted
    assert noted.model_validate({"status": "done", "notes": ["a"]})
    # A field the run was not asked for is refused, where the contract's own reader passes it over.
    with pytest.raises(ValidationError, match="notes"):
        plain.model_validate({"status": "done", "notes": []})
    assert _Core.model_validate({"status": "done", "notes": []})


@pytest.mark.parametrize(
    ("groups", "value"),
    [((), "worker"), (("notes",), "worker:notes"), (("notes", "no-such-group"), "worker:notes")],
)
def test_a_run_is_told_what_it_reports_in_one_variable(groups: tuple[str, ...], value: str) -> None:
    asked = CONTRACT.asked(groups)
    assert asked.env() == {run_result.ENV: value}
    assert run_result.asked_of(value, CONTRACTS) == asked


@pytest.mark.parametrize(
    "value",
    ["", "task", "Worker", "worker:Notes", "worker:notes,", "worker:" + ",".join("a" * 21)],
)
def test_a_variable_that_names_no_contract_is_no_result_to_report(value: str) -> None:
    assert run_result.asked_of(value, CONTRACTS) is None


@pytest.mark.parametrize(
    ("called", "read"),
    [
        (Called(f"{SERVER}_result", completed=True, input={"status": "done"}), '{"status": "done"}'),
        # A call the server refused, another tool's, and one whose input is not the run's result report nothing.
        (Called(f"{SERVER}_result", completed=False, input={"status": "done"}), None),
        (Called(f"{SERVER}_status", completed=True, input={"status": "done"}), None),
        (Called("other_result", completed=True, input={"status": "done"}), None),
        (Called(f"{SERVER}_result", completed=True, input={"status": "finished"}), None),
        (Called(f"{SERVER}_result", completed=True, input={"status": "done", "notes": []}), None),
    ],
)
def test_a_result_is_read_from_a_call_the_server_took_and_held_to_the_runs_input(
    called: Called,
    read: str | None,
) -> None:
    assert run_result.read_call(called, CONTRACT.asked(), server=SERVER) == read
