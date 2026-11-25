"""The environment every agent canopy starts runs with (TRUST_MODEL T4)."""

from canopy.core import agent_env, hostgit


def test_the_editors_and_terminals_variables_are_removed_by_name_and_by_prefix() -> None:
    inherited = [
        "VSCODE_IPC_HOOK_CLI",
        "VSCODE_GIT_IPC_HANDLE",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "COLORTERM",
        "GPG_TTY",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "SSH_ASKPASS",
        # What an agent may use, and what canopy sets over: kept.
        "HOME",
        "PATH",
        "TERM",
        "GIT_ASKPASS",
        "SSH_AUTH_SOCK",
        "MY_VSCODE_THING",
    ]
    assert agent_env.unset(inherited) == set(inherited[:9])


def test_an_agent_reaches_no_askpass_or_prompt_the_harness_git_does_not() -> None:
    assert hostgit.ENV.items() <= agent_env.ENV.items()
    assert agent_env.ENV["GIT_ASKPASS"] == "false"
    assert agent_env.ENV["SSH_ASKPASS_REQUIRE"] == "never"
