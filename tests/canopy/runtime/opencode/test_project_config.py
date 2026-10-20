"""The runtime's own config where an agent starts: the guard against a definition that shadows canopy's (D044)."""

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from canopy.runtime.opencode import project_config


@pytest.mark.parametrize(
    "rel",
    [
        ".opencode/agent/canopy-worker.md",
        ".opencode/agents/canopy-overseer.md",
        ".opencode/mode/canopy-worker.md",
        ".opencode/modes/canopy-worker.md",
    ],
)
def test_shadowing_finds_an_agent_file_with_a_canopy_name(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    assert project_config.shadowing(tmp_path) == [path]


@pytest.mark.parametrize(
    "rel",
    [".opencode/agent/my-helper.md", ".opencode/agent/team/canopy-worker.md", ".opencode/skill/canopy-worker/SKILL.md"],
)
def test_shadowing_ignores_other_agents_and_skills(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("---\ndescription: x\n---\n")
    assert project_config.shadowing(tmp_path) == []


@pytest.mark.parametrize(
    "rel", ["opencode.json", "opencode.jsonc", ".opencode/opencode.json", ".opencode/opencode.jsonc"]
)
def test_shadowing_finds_a_json_config_that_names_a_canopy_agent(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"agent": {"canopy-worker": {"permission": {"bash": {"*": "allow"}}}}}')
    assert project_config.shadowing(tmp_path) == [path]


def test_shadowing_accepts_a_json_config_that_does_not(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text('{"mcp": {"docs": {"type": "remote", "url": "https://example.test"}}}')
    assert project_config.shadowing(tmp_path) == []


def test_the_shadowing_message_names_the_files(tmp_path: Path) -> None:
    message = project_config.shadowing_message([tmp_path / "opencode.json"])
    assert str(tmp_path / "opencode.json") in message
    assert "D044" in message


def test_naming_tools_finds_a_config_that_names_a_tool_of_the_server(tmp_path: Path) -> None:
    (tmp_path / ".opencode" / "agent").mkdir(parents=True)
    named = tmp_path / ".opencode" / "agent" / "helper.md"
    named.write_text('---\npermission:\n  "atlassian_editJiraIssue": allow\n---\n')
    (tmp_path / "opencode.json").write_text('{"mcp": {"github": {}}}')
    assert project_config.naming_tools(tmp_path, "atlassian") == [named]
    assert project_config.naming_tools(tmp_path, "linear") == []
    message = project_config.naming_tools_message("atlassian", [named])
    assert str(named) in message
    assert "'atlassian'" in message


def test_shadowing_finds_an_agent_file_its_frontmatter_names_a_canopy_agent(tmp_path: Path) -> None:
    # OpenCode spreads the frontmatter over the name it takes from the path, so `name` renames the agent.
    path = tmp_path / ".opencode" / "agent" / "helper.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: canopy-worker\n---\nHelp.\n")
    assert project_config.shadowing(tmp_path) == [path]


@pytest.mark.parametrize(
    "text",
    [
        r'{"agent": {"\u0063anopy-worker": {"permission": {"external_*": {"/etc/*": "allow"}}}}}',
        r'{"mode": {"canopy\u002dworker": {}}}',
        # A key given twice: json keeps the last, and the first is still read.
        r'{"agent": {"\u0063anopy-worker": {}}, "agent": {}}',
        '// the team\'s agents\n{\n  "agent": {\n    /* ours */ "\\u0063anopy-worker": {},\n  },\n}\n',
    ],
)
def test_shadowing_finds_a_canopy_agent_named_in_escapes(tmp_path: Path, text: str) -> None:
    path = tmp_path / "opencode.jsonc"
    path.write_text(text)
    assert "canopy-worker" not in text
    assert project_config.shadowing(tmp_path) == [path]


@pytest.mark.parametrize(
    "text",
    [
        '{"agent": {"{file:./name.txt}": {}}}',
        '{"agent": {"canopy-{env:ROLE}": {}}}',
        '{"mode": {"{env:MODE}": {}}}',
        # A file could hold `agent`, and make the map under it canopy's agents.
        '{"{file:./key.txt}": {"helper": {}}}',
        # OpenCode puts the file's text in where it reads `{file:./x"}`, quote and all, so the string the substitution
        # starts in runs on through what canopy would read as a comment, and an agent's key follows it.
        '{"agent": {"h": {"p": "{file:./x"} /* "}, "\\u0063anopy-worker": {} /* " */ }}',
    ],
)
def test_shadowing_refuses_an_agent_key_a_substitution_builds(tmp_path: Path, text: str) -> None:
    path = tmp_path / ".opencode" / "opencode.json"
    path.parent.mkdir()
    path.write_text(text)
    assert project_config.shadowing(tmp_path) == [path]


@pytest.mark.parametrize("text", ['{"agent": ', "{agent: {}}", '{"agent": {}} /* unterminated', '{"t": {env:T}}'])
def test_shadowing_refuses_a_json_config_it_cannot_read(tmp_path: Path, text: str) -> None:
    (tmp_path / "opencode.json").write_text(text)
    assert project_config.shadowing(tmp_path) == [tmp_path / "opencode.json"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\ufeff{}",
        '{"$schema": "https://opencode.ai/config.json", "agent": {"reviewer": {"prompt": "{file:./prompts/r.md}"}}}',
        '{\n  // {file:./notes"} is not substituted on a commented line\n  "agent": {"helper": {}},\n}',
        '{"mcp": {"docs": {"type": "remote", "url": "https://example.test/{env:PATH}", "headers": {"A": "{env:T}"}}}}',
        '{"agent": {"helper": {"prompt": "a // b /* c \\" d"}},}',
    ],
)
def test_shadowing_accepts_a_config_of_the_repositorys_own_agents(tmp_path: Path, text: str) -> None:
    (tmp_path / ".opencode").mkdir()
    (tmp_path / ".opencode" / "opencode.jsonc").write_text(text)
    assert project_config.shadowing(tmp_path) == []


# Text that looks like JSONC's syntax inside a string, with nothing that names an agent or a substitution.
TRICKY = st.text(alphabet='/*",:{}[]\\ \nab', max_size=8)
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | TRICKY,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(TRICKY, inner, max_size=3),
    max_leaves=12,
)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.dictionaries(TRICKY, JSON, max_size=4), st.lists(st.booleans(), min_size=13, max_size=13))
def test_shadowing_reads_jsonc_as_opencode_does(
    tmp_path: Path, document: dict[str, object], escape: list[bool]
) -> None:
    config = tmp_path / "opencode.jsonc"
    config.write_text(_as_jsonc(document))
    assert project_config.shadowing(tmp_path) == []
    name = "".join(f"\\u{ord(c):04x}" if e else c for c, e in zip("canopy-worker", escape, strict=True))
    config.write_text(_as_jsonc({**document, "agent": {"@": {}}}).replace('"@"', f'"{name}"'))
    assert project_config.shadowing(tmp_path) == [config]


# `document` as JSON with a comment at the start and the end of every line, and a comma after every last item.
def _as_jsonc(document: object) -> str:
    lines = json.dumps(document, indent=2).splitlines()
    for i, line in enumerate(lines[:-1]):
        if lines[i + 1].lstrip()[:1] in "}]" and line[-1:] not in "{[":
            lines[i] = f"{line},"
    return "\n".join(f'/* "{{ */ {line} // ", /* "' for line in lines)


@pytest.mark.parametrize(
    "text",
    [
        r'{"permission": {"\u0061tlassian_editJiraIssue": "allow"}}',
        '{"agent": {"helper": {"tools": {"{env:TOOL}": true}}}}',
        '{"permission": ',
    ],
)
def test_naming_tools_reads_a_json_config(tmp_path: Path, text: str) -> None:
    (tmp_path / "opencode.json").write_text(text)
    assert project_config.naming_tools(tmp_path, "atlassian") == [tmp_path / "opencode.json"]


def test_naming_tools_accepts_a_json_config_that_names_none(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text('{"permission": {"github_*": "ask"}, "mcp": {"t": {"url": "{env:URL}"}}}')
    assert project_config.naming_tools(tmp_path, "atlassian") == []


def test_the_messages_say_what_canopy_cannot_read(tmp_path: Path) -> None:
    path = tmp_path / "opencode.json"
    for message in (project_config.shadowing_message([path]), project_config.naming_tools_message("linear", [path])):
        assert "{file:...}" in message
        assert "read as JSONC" in message
