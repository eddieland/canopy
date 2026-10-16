"""A chore's `days` and `hours` (DESIGN §19): when a run may start, checked in code."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from canopy.cli.main import main
from canopy.core import chore_view as view
from canopy.core import chore_window as window
from canopy.core import db, workspace
from canopy.core.config import CHORE_DAYS, Chore, load
from tests.canopy.helpers import InlineRunner, chore_decisions, chore_toml, in_tick, state_block
from tests.conftest import CanopyEnv

NY = "America/New_York"


def chore(**window_keys: object) -> Chore:
    return Chore.model_validate({"prompt": "~/chore.md", "every_minutes": 60, **window_keys})


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_without_days_or_hours_a_chore_is_always_open() -> None:
    always = chore()
    assert not window.limited(always)
    at = utc("2026-10-10T03:00")
    assert window.is_open(always, at)
    assert window.next_open(always, at) == at


def test_working_hours_in_a_time_zone() -> None:
    weekdays = chore(days=["mon", "tue", "wed", "thu", "fri"], hours="08:00-18:00", timezone=NY)
    # Thursday 2026-10-08: New York is UTC-4.
    assert window.is_open(weekdays, utc("2026-10-08T12:00"))  # 08:00 there
    assert not window.is_open(weekdays, utc("2026-10-08T11:59"))
    assert not window.is_open(weekdays, utc("2026-10-08T22:00"))  # 18:00 there: the end is not in the window
    # Before the start: today's. After the end: tomorrow's. Friday evening: Monday's.
    assert window.next_open(weekdays, utc("2026-10-08T05:00")) == utc("2026-10-08T12:00")
    assert window.next_open(weekdays, utc("2026-10-08T23:00")) == utc("2026-10-09T12:00")
    assert window.next_open(weekdays, utc("2026-10-09T23:00")) == utc("2026-10-12T12:00")
    # Across the end of daylight saving time (2026-11-01), 08:00 is UTC-5.
    assert window.next_open(weekdays, utc("2026-10-30T23:00")) == utc("2026-11-02T13:00")
    assert window.describe(weekdays) == f"mon,tue,wed,thu,fri 08:00-18:00 {NY}"


def test_days_alone_open_at_midnight_and_hours_alone_every_day() -> None:
    weekend = chore(days=["sat", "sun"], timezone="UTC")
    assert window.next_open(weekend, utc("2026-10-08T12:00")) == utc("2026-10-10T00:00")
    assert window.is_open(weekend, utc("2026-10-11T23:59"))
    nightly = chore(hours="01:00-24:00", timezone="UTC")
    assert window.next_open(nightly, utc("2026-10-08T00:30")) == utc("2026-10-08T01:00")
    assert window.is_open(nightly, utc("2026-10-08T23:59"))
    assert window.describe(nightly) == "every day 01:00-24:00 UTC"


def test_without_a_time_zone_the_window_is_local_time() -> None:
    try:
        with mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
            time.tzset()
            morning = chore(hours="09:00-10:00")
            assert window.next_open(morning, utc("2026-10-08T12:00")) == utc("2026-10-09T00:00")
            assert window.describe(morning) == "every day 09:00-10:00 local time"
    finally:
        time.tzset()


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        ({"hours": "8-18"}, "must be two times of day"),
        ({"hours": "08:00-24:30"}, "must be two times of day"),
        ({"hours": "25:00-26:00"}, "must be two times of day"),
        ({"hours": "18:00-08:00"}, "must end after they start"),
        ({"hours": "08:00-08:00"}, "must end after they start"),
        ({"days": ["mon", "mon"]}, "days must not repeat"),
        ({"days": ["monday"]}, "Input should be 'mon'"),
        ({"timezone": "Mars/Olympus"}, "not an IANA time zone"),
    ],
)
def test_a_bad_window_is_a_config_error(keys: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        chore(**keys)


def closed_today() -> list[str]:
    """Every day but today in UTC, so the window is closed now and opens at the next midnight UTC."""
    today = CHORE_DAYS[datetime.now(UTC).weekday()]
    return [d for d in CHORE_DAYS if d != today]


@pytest.fixture
def closed(canopy_env: CanopyEnv) -> Path:
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n")
    days = json.dumps(closed_today())
    canopy_env.write_user(canopy_env.user_file.read_text() + chore_toml(extra=f'days = {days}\ntimezone = "UTC"\n'))
    return prompt


def next_midnight() -> str:
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    return db.format_time(datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=UTC))


def test_outside_its_window_a_chore_is_refused_and_not_due(
    canopy_env: CanopyEnv, closed: Path, treehouse_state: Path, agent_log: Path
) -> None:
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
        [section] = state_block(agent_log)["chores"]
        assert (section["due"], section["due_at"]) == (False, next_midnight())

        conn = canopy_env.journal()
        with in_tick(conn) as tick_id:
            assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 1
            [(name, action, rationale)] = chore_decisions(conn, tick_id)
            assert (name, action) == ("build-health", "refused:outside_hours")
            assert rationale == (
                f"build-health starts only {','.join(closed_today())} all day UTC; next at {next_midnight()}"
            )


def test_a_run_waits_out_every_minutes_and_then_its_window(canopy_env: CanopyEnv, closed: Path) -> None:
    conn = canopy_env.journal()
    [state] = view.states(conn, load(canopy_env.root, canopy_env.user_file), workspace.load(canopy_env.root))
    now = datetime.now(UTC)
    assert state.earliest() is None  # never run: `every_minutes` allows it now, the window does not
    assert db.format_time(state.due_at(now) or now) == next_midnight()
