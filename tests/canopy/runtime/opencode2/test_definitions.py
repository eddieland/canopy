"""canopy's agent definitions as OpenCode 2 reads them: OpenCode 1's files, a service file, and links to config."""

import json
import os
from pathlib import Path
from unittest import mock

from canopy.runtime.opencode import definitions as opencode1
from canopy.runtime.opencode2 import definitions


def test_the_bundled_files_are_opencode_1s_and_a_service_file_that_disables_the_shared_service() -> None:
    files = definitions.bundled()
    assert json.loads(files.pop(definitions.SERVICE_FILE)) == {"disabled": True}
    assert files == opencode1.bundled()


def test_a_skill_is_counted_under_a_name_only_by_opencode_1s_rule() -> None:
    assert definitions.SKILL_NAME_RE.fullmatch("tracker-jira")
    assert not definitions.SKILL_NAME_RE.fullmatch("My Skill")
    assert definitions.MAX_SKILL_NAME == opencode1.MAX_SKILL_NAME


def test_the_snapshot_links_each_of_the_operators_config_files_where_opencode_2_keeps_them(tmp_path: Path) -> None:
    # The definitions directory takes the place of the operator's own, so their config is read through the links.
    with mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
        os.environ.pop("XDG_CONFIG_HOME", None)
        default = definitions.links()
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
            xdg = definitions.links()
    names = ("config.json", "opencode.json", "opencode.jsonc")
    assert default == {name: tmp_path / ".config" / "opencode" / name for name in names}
    assert xdg == {name: tmp_path / "xdg" / "opencode" / name for name in names}
