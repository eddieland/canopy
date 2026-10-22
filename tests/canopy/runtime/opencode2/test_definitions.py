"""canopy's agent definitions as OpenCode 2 reads them: OpenCode 1's files, and a config that disables the service."""

import json

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
