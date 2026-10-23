"""The settings page's config writes (DESIGN §12, §22, ROADMAP M41).

Only the keys it lists, within their bounds, trust settings only toward stricter, the workspace's private file alone,
its comments kept, and a reload asked for after.
"""

import json
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

import httpx2
import tomlkit
from fastapi.testclient import TestClient

from canopy.core import conversation
from canopy.core.context import Context
from canopy.loop import reread
from canopy.serve import config_edit
from tests.canopy.web_helpers import refused, signed_in_client
from tests.conftest import CanopyEnv, user_toml

# The private file the tests edit: the user file under it is `user_toml()`, which no save writes.
COMMENTED = """# Two on the laptop; the desktop has room for more.
[capacity]
max_workers = 2  # raise when the fans allow
repo_slots = { repo = 3 }  # the only repository

[trust]
trusted_reviewers = [
    "alice",  # reviews everything
    "lint-bot",  # posts style nits
]
rebase = false
"""


def settings(c: TestClient) -> dict[str, object]:
    response = c.get("/api/config")
    assert response.status_code == 200, response.text
    found: dict[str, object] = response.json()
    return found


def keys_of(found: dict[str, object]) -> list[dict[str, object]]:
    keys = found["keys"]
    assert isinstance(keys, list)
    return keys


def key(found: dict[str, object], name: str) -> dict[str, object]:
    return next(k for k in keys_of(found) if k["name"] == name)


def read_hash(c: TestClient) -> str:
    return str(settings(c)["hash"])


def save(
    c: TestClient,
    headers: dict[str, str],
    changes: Mapping[str, object],
    hash_: str | None = None,
) -> httpx2.Response:
    body = {"hash": hash_ if hash_ is not None else read_hash(c), "changes": changes}
    return c.patch("/api/config", json=body, headers=headers)


def test_the_page_lists_each_editable_key_with_its_value_source_and_bound(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(COMMENTED)
    canopy_env.write_user(user_toml().replace("[paths]", "[loop]\ninterval_minutes = 20\n\n[paths]"))
    canopy_env.write_shared(canopy_env.shared_file.read_text() + "\n[policy]\nmax_resume_attempts = 1\n")
    c, _ = signed_in_client(ctx)

    found = settings(c)

    assert [k["name"] for k in keys_of(found)] == [e.name for e in config_edit.EDITABLE]
    assert key(found, "capacity.max_workers") == {
        "name": "capacity.max_workers",
        "value": 2,
        "source": "private",
        "kind": "limit",
        "bound": 32,
        "looser": "higher",
    }
    assert key(found, "policy.max_resume_attempts")["source"] == "workspace"
    assert key(found, "policy.max_implement_attempts")["source"] == "default"
    assert key(found, "loop.interval_minutes") | {"value": None} == {
        "name": "loop.interval_minutes",
        "value": None,
        "source": "user",
        "kind": "limit",
        "bound": 2,
        "looser": "lower",
    }
    assert key(found, "capacity.repo_slots")["value"] == {"repo": 3}
    assert key(found, "trust.trusted_reviewers") | {"value": None} == {
        "name": "trust.trusted_reviewers",
        "value": None,
        "source": "private",
        "kind": "stricter",
        "bound": None,
        "looser": None,
    }
    assert found["private_file"] == str(canopy_env.private_file)
    assert found["user_file"] == str(canopy_env.user_file)
    assert found["repos"] == ["repo"]
    assert found["every"] is None
    assert found["hash"] == config_edit.digest(canopy_env.private_file.read_bytes())


def test_with_no_private_file_the_hash_is_an_empty_file_s(ctx: Context, canopy_env: CanopyEnv) -> None:
    c, _ = signed_in_client(ctx)

    assert read_hash(c) == config_edit.digest(b"")


def test_a_save_writes_the_private_file_keeping_its_comments_and_asks_for_a_reload(
    ctx: Context,
    canopy_env: CanopyEnv,
) -> None:
    canopy_env.write_private(COMMENTED)
    shared = canopy_env.shared_file.read_text()
    reload = reread.Reload()
    c, headers = signed_in_client(ctx, reload)
    assert c.patch("/api/config", json={"hash": "x", "changes": {"capacity.max_workers": 3}}).status_code == 403
    assert not reload.requested

    response = save(
        c,
        headers,
        {
            "capacity.max_workers": 4,
            "capacity.repo_slots": {"repo": 2, "other": 5},
            "trust.trusted_reviewers": ["alice"],
            "policy.max_implement_attempts": 3,
        },
    )

    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["changed"] == [
        {"name": "capacity.max_workers", "old": 2, "new": 4},
        {"name": "capacity.repo_slots", "old": {"repo": 3}, "new": {"repo": 2, "other": 5}},
        {"name": "policy.max_implement_attempts", "old": 2, "new": 3},
        {"name": "trust.trusted_reviewers", "old": ["alice", "lint-bot"], "new": ["alice"]},
    ]
    assert saved["reload"]["changed"] == [
        "policy.max_implement_attempts",
        "trust.trusted_reviewers",
        "capacity.max_workers",
        "capacity.repo_slots",
    ]
    assert saved["reload"]["after_tick"] is False
    assert saved["reload_refused"] is None
    assert reload.requested
    text = canopy_env.private_file.read_text()
    assert saved["hash"] == config_edit.digest(text.encode())
    assert (
        text
        == COMMENTED.replace("max_workers = 2  #", "max_workers = 4  #")
        .replace("repo_slots = { repo = 3 }", "repo_slots = { repo = 2, other = 5}")
        .replace('    "lint-bot",  # posts style nits\n', "")
        + "\n[policy]\nmax_implement_attempts = 3\n"
    )
    assert canopy_env.shared_file.read_text() == shared  # a shared policy key goes to the private file, which wins
    assert canopy_env.user_file.read_text() == user_toml()
    log = [json.loads(line) for line in (canopy_env.state_dir / "canopy.log").read_text().splitlines()]
    assert {"key": "capacity.max_workers", "old": 2, "new": 4, "channel": "web"}.items() <= next(
        r for r in log if r.get("key") == "capacity.max_workers"
    ).items()


def test_a_key_from_the_user_file_is_written_to_the_private_file_whole(ctx: Context, canopy_env: CanopyEnv) -> None:
    # The user file is the operator's for every workspace: the change shadows it here, and leaves it as it was.
    user = user_toml().replace(
        "[paths]",
        "[capacity]\nmax_workers = 2\nrepo_slots = { repo = 3, other = 4 }\n\n"
        '[trust]\ntrusted_reviewers = ["alice", "bob", "lint-bot"]\n\n[paths]',
    )
    canopy_env.write_user(user)
    assert not canopy_env.private_file.exists()
    c, headers = signed_in_client(ctx)

    saved = save(
        c,
        headers,
        {"capacity.repo_slots": {"repo": 5}, "trust.trusted_reviewers": ["alice", "bob"]},
    ).json()

    assert saved["changed"] == [
        {"name": "capacity.repo_slots", "old": {"repo": 3, "other": 4}, "new": {"repo": 5, "other": 4}},
        {"name": "trust.trusted_reviewers", "old": ["alice", "bob", "lint-bot"], "new": ["alice", "bob"]},
    ]
    assert canopy_env.user_file.read_text() == user
    assert canopy_env.private_file.read_text() == (
        '[capacity]\nrepo_slots = {repo = 5, other = 4}\n\n[trust]\ntrusted_reviewers = ["alice", "bob"]\n'
    )
    assert canopy_env.private_file.stat().st_mode & 0o777 == 0o600
    assert not canopy_env.private_file.with_name("config.toml.bak").exists()  # nothing was there to keep
    found = settings(c)
    assert key(found, "capacity.max_workers")["source"] == "user"
    assert key(found, "capacity.repo_slots")["source"] == "private"


def test_a_save_that_changes_nothing_writes_nothing_and_asks_for_no_reload(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(COMMENTED)
    reload = reread.Reload()
    c, headers = signed_in_client(ctx, reload)
    before = canopy_env.private_file.stat().st_mtime_ns

    saved = save(c, headers, {"capacity.max_workers": 2}).json()

    assert saved["changed"] == []
    assert saved["reload"] is None
    assert not reload.requested
    assert canopy_env.private_file.stat().st_mtime_ns == before
    canopy_env.private_file.unlink()
    assert save(c, headers, {"capacity.max_workers": 2}).json()["changed"] == []
    assert not canopy_env.private_file.exists()  # not made for nothing


def test_a_save_keeps_the_files_mode(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(COMMENTED)
    canopy_env.private_file.chmod(0o640)
    c, headers = signed_in_client(ctx)

    assert save(c, headers, {"capacity.max_chores": 2}).status_code == 200

    assert canopy_env.private_file.stat().st_mode & 0o777 == 0o640
    assert [p.name for p in canopy_env.state_dir.iterdir() if p.name.endswith(".tmp")] == []


def test_each_refusal_leaves_the_files_as_they_were(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(COMMENTED)
    reload = reread.Reload()
    c, headers = signed_in_client(ctx, reload)
    cases: tuple[tuple[dict[str, object], str], ...] = (
        ({"runtime.worker_cmd": "sh -c {prompt}"}, "not_editable"),
        ({"serve.port": 9000}, "not_editable"),
        ({"capacity": {"max_workers": 3}}, "not_editable"),
        ({"capacity.max_workers": 33}, "past_bound"),
        ({"capacity.repo_slots": {"repo": 33}}, "past_bound"),
        ({"capacity.slots_per_repo": 40}, "past_bound"),
        ({"loop.interval_minutes": 1}, "past_bound"),
        ({"policy.ci_cooldown_minutes": 0}, "past_bound"),
        ({"trust.rebase": True}, "not_stricter"),
        ({"trust.commit_trailer": False}, "not_stricter"),
        ({"trust.trusted_reviewers": ["alice", "lint-bot", "mallory"]}, "not_stricter"),
        ({"trust.authorized_repliers": ["mallory"]}, "not_stricter"),
        ({"capacity.max_workers": -1}, "config_invalid"),
        ({"capacity.max_workers": "many"}, "config_invalid"),
        ({"capacity.max_workers": True}, "config_invalid"),
        ({"policy.stacking": "always"}, "config_invalid"),
        ({"capacity.slots_per_repo": None}, "config_invalid"),
    )
    for changes, guard in cases:
        assert refused(save(c, headers, changes)).startswith(f"{guard}: "), changes
        assert canopy_env.private_file.read_text() == COMMENTED
        assert canopy_env.user_file.read_text() == user_toml()
    assert f"set more in {canopy_env.private_file}" in refused(save(c, headers, {"capacity.max_workers": 33}))
    assert not reload.requested
    assert [p.name for p in canopy_env.state_dir.iterdir() if p.name.endswith(".tmp")] == []


def test_the_loader_s_message_names_the_private_file_not_the_copy_it_checked(
    ctx: Context,
    canopy_env: CanopyEnv,
) -> None:
    c, headers = signed_in_client(ctx)

    reason = refused(save(c, headers, {"capacity.max_workers": "many"}))

    assert f"{canopy_env.private_file}: capacity.max_workers" in reason
    assert ".tmp" not in reason


def test_a_trust_setting_may_be_made_stricter(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(COMMENTED.replace("rebase = false", "rebase = true\ncommit_trailer = false"))
    c, headers = signed_in_client(ctx)

    saved = save(
        c,
        headers,
        {
            "trust.rebase": False,
            "trust.commit_trailer": True,
            "policy.stacking": "never",
            "trust.trusted_reviewers": [],
        },
    ).json()

    assert {(c["name"], json.dumps(c["new"])) for c in saved["changed"]} == {
        ("trust.rebase", "false"),
        ("trust.commit_trailer", "true"),
        ("policy.stacking", '"never"'),
        ("trust.trusted_reviewers", "[]"),
    }
    assert refused(save(c, headers, {"policy.stacking": "auto"})).startswith("not_stricter: ")


def test_a_limit_the_file_set_past_its_bound_may_still_be_lowered(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(user_toml().replace("[paths]", "[capacity]\nmax_workers = 40\n\n[paths]"))
    c, headers = signed_in_client(ctx)

    assert save(c, headers, {"capacity.max_workers": 35}).status_code == 200
    assert "max_workers = 35" in canopy_env.private_file.read_text()
    assert refused(save(c, headers, {"capacity.max_workers": 36})).startswith("past_bound: ")


def test_a_save_on_a_stale_hash_is_refused(ctx: Context, canopy_env: CanopyEnv) -> None:
    c, headers = signed_in_client(ctx)
    read = read_hash(c)
    canopy_env.write_private("# edited by hand\n")

    assert refused(save(c, headers, {"capacity.max_workers": 3}, read)).startswith("stale: ")
    assert canopy_env.private_file.read_text() == "# edited by hand\n"


def test_two_saves_on_one_hash_cannot_both_pass(ctx: Context, canopy_env: CanopyEnv) -> None:
    c, headers = signed_in_client(ctx)
    read = read_hash(c)
    first_holds = threading.Event()
    let_go = threading.Event()
    reads: list[Path] = []
    real = config_edit._read_own  # noqa: SLF001  (the first save is held inside the lock, past its hash check)

    def slow(path: Path) -> tuple[bytes, int | None]:
        reads.append(path)
        found = real(path)
        if len(reads) == 1:
            first_holds.set()
            assert let_go.wait(10)
        return found

    answers: dict[str, httpx2.Response] = {}

    def saving(name: str, workers: int) -> threading.Thread:
        thread = threading.Thread(
            target=lambda: answers.update({name: save(c, headers, {"capacity.max_workers": workers}, read)}),
        )
        thread.start()
        return thread

    with mock.patch.object(config_edit, "_read_own", autospec=True, side_effect=slow):
        first = saving("first", 3)
        assert first_holds.wait(10)
        second = saving("second", 4)
        second.join(0.5)
        assert second.is_alive()
        assert len(reads) == 1  # the second waits for the lock before it reads the file
        let_go.set()
        first.join(10)
        second.join(10)

    assert answers["first"].status_code == 200, answers["first"].text
    assert refused(answers["second"]).startswith("stale: ")
    assert "max_workers = 3" in canopy_env.private_file.read_text()


def test_a_symlinked_private_file_is_refused(ctx: Context, canopy_env: CanopyEnv, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text(COMMENTED)
    c, headers = signed_in_client(ctx)
    canopy_env.private_file.symlink_to(elsewhere)

    # The page cannot read the files to get a hash now, so the save carries the one the target would have.
    reason = refused(save(c, headers, {"capacity.max_workers": 3}, config_edit.digest(COMMENTED.encode())))

    assert reason.startswith("unsafe_file: ")
    assert elsewhere.read_text() == COMMENTED
    assert canopy_env.private_file.is_symlink()


def test_a_save_inside_a_run_is_refused(ctx: Context, canopy_env: CanopyEnv) -> None:
    c, headers = signed_in_client(ctx)

    with mock.patch.dict(os.environ, {conversation.RUN_ID_ENV: "7"}):
        assert refused(save(c, headers, {"capacity.max_workers": 3})).startswith("inside_run: ")
    assert not canopy_env.private_file.exists()


def test_a_save_says_every_still_sets_the_pace(ctx: Context, canopy_env: CanopyEnv) -> None:
    c, headers = signed_in_client(ctx, every=3)

    assert settings(c)["every"] == 3
    saved = save(c, headers, {"loop.interval_minutes": 30}).json()
    assert saved["every"] == 3
    assert saved["changed"] == [{"name": "loop.interval_minutes", "old": 15, "new": 30}]
    assert canopy_env.private_file.read_text() == "[loop]\ninterval_minutes = 30\n"


def test_a_section_written_as_an_inline_table_is_edited_in_place(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private("capacity = { max_workers = 3, max_chores = 2 }\n")
    c, headers = signed_in_client(ctx)

    saved = save(c, headers, {"capacity.max_workers": 4}).json()

    assert saved["changed"] == [{"name": "capacity.max_workers", "old": 3, "new": 4}]
    assert canopy_env.private_file.read_text() == "capacity = { max_workers = 4, max_chores = 2 }\n"


def test_a_save_keeps_the_file_as_it_was_beside_it(ctx: Context, canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(COMMENTED)
    canopy_env.private_file.chmod(0o600)
    c, headers = signed_in_client(ctx)
    backup = canopy_env.private_file.with_name("config.toml.bak")

    assert save(c, headers, {"capacity.max_workers": 3}).status_code == 200
    assert backup.read_text() == COMMENTED
    assert backup.stat().st_mode & 0o777 == 0o600

    written = canopy_env.private_file.read_text()
    assert save(c, headers, {"capacity.max_workers": 4}).status_code == 200
    assert backup.read_text() == written  # the last save's, not the first


def test_a_symlinked_backup_is_refused(ctx: Context, canopy_env: CanopyEnv, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    canopy_env.write_private(COMMENTED)
    canopy_env.private_file.with_name("config.toml.bak").symlink_to(elsewhere)
    c, headers = signed_in_client(ctx)

    assert refused(save(c, headers, {"capacity.max_workers": 3})).startswith("unsafe_file: ")
    assert not elsewhere.exists()
    assert canopy_env.private_file.read_text() == COMMENTED


def test_a_file_that_would_not_write_back_exactly_is_refused(ctx: Context, canopy_env: CanopyEnv) -> None:
    c, headers = signed_in_client(ctx)
    real = tomlkit.dumps

    def lossy(data: Mapping[str, object], sort_keys: bool = False) -> str:  # noqa: FBT001, FBT002  (tomlkit's own signature)
        return real(data, sort_keys=sort_keys).replace("# ", "#")

    canopy_env.write_private("# a comment tomlkit would change\n")
    with mock.patch.object(tomlkit, "dumps", autospec=True, side_effect=lossy):
        assert refused(save(c, headers, {"capacity.max_workers": 3})).startswith("not_roundtrip: ")
    assert canopy_env.private_file.read_text() == "# a comment tomlkit would change\n"
