"""`canopy init`, `canopy skill`, `canopy completion`, `canopy secret`, and `canopy sandbox setup`: setting canopy up.

`canopy skill` is for the operator's own agent sessions, `canopy completion` for their shell, `canopy secret` for the
web UI, and `canopy sandbox setup` for sandboxed runs.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Sequence
from pathlib import Path

import click
from click.shell_completion import BashComplete, FishComplete, ShellComplete, ZshComplete

from canopy.chores import history
from canopy.cli import workspace as cli_workspace
from canopy.cli.common import CliError, runner_of
from canopy.core import config, conversation, git_tools, hostgit, workspace
from canopy.infra import procs, resources
from canopy.runtime import project_config
from canopy.serve import secret
from canopy.setup import init
from canopy.setup import sandbox as setup_sandbox
from canopy.setup import workspace as setup_workspace

# The shells `canopy completion` writes a script for. The script runs canopy with `_CANOPY_COMPLETE` set, which click
# answers before any command runs.
SHELLS: dict[str, type[ShellComplete]] = {"bash": BashComplete, "zsh": ZshComplete, "fish": FishComplete}
COMPLETE_VAR = "_CANOPY_COMPLETE"

# Where `canopy skill --install` saves the skill when given no directory: the home skills directory shared by agent
# runtimes (DESIGN §13).
SKILLS_DIR = "~/.agents/skills"
#: canopy's own MCP servers, which a review, a plan, or a chore is given (DESIGN §27): init warns of config naming one.
OWN_SERVERS = (git_tools.SERVER, history.SERVER)


@click.command("init")
@click.option("--provider", help="Tracker provider for a new workspace map (jira, github, linear, ...).")
@click.option(
    "--workspace",
    "in_checkout",
    is_flag=True,
    help="Make this directory a workspace even though it is inside a git repository, such as one that holds only "
    "the workspace's own files. A repository at your home directory, such as your dotfiles, needs no flag.",
)
@click.argument("repos", metavar="[[NAME=]URL]...", nargs=-1)
@click.pass_context
def cmd_init(click_ctx: click.Context, provider: str | None, repos: tuple[str, ...], *, in_checkout: bool) -> int:
    """Set up a workspace in this directory, with its private config.

    canopy runs from a workspace, even for one repository: a directory of its own, ideally empty, where it clones each
    repository and keeps their worktree pools and its journal. Its private config, .canopy/config.toml, is yours alone:
    your queue label and whom you trust, for this workspace. Clone URLs add those repositories to the map and sync:
    each is cloned, and its pool made the size your config declares. A repository is named after its URL, unless
    given as NAME=URL. Run inside a workspace, init fills in what it is missing.
    """
    root = workspace.find_root(Path.cwd())
    if root is None:
        root = Path.cwd().resolve()
        _check_new_root(root, in_checkout=in_checkout)
    provider = _provider(provider, root / config.WORKSPACE_FILE_NAME, "workspace")
    return _init_workspace(click_ctx, root, provider, repos)


def _check_new_root(root: Path, *, in_checkout: bool) -> None:
    """Refuse a directory that must not become a new workspace (D016).

    Not the home directory: every later `canopy init` below it would fill it in rather than make a workspace, and its
    `.canopy/` is an earlier canopy's journal. Not a directory with a `.canopy/` already, which a new workspace would
    take over as its own. Not inside a code checkout, unless --workspace says the checkout holds only the workspace; a
    repository at the home directory is the operator's dotfiles, not code canopy works on.

    Raises:
        click.UsageError: `root` is the home directory, has a `.canopy/` but no workspace file, or is inside a git
            repository other than one at the home directory and `in_checkout` is false.
    """
    home = Path.home().resolve()
    new_dir = (
        "Make a directory of its own, such as ~/canopy, and run `canopy init --provider <tracker> <URL>...` there."
    )
    if root == home:
        raise click.UsageError(f"{root} is your home directory, and a workspace is a directory of its own. {new_dir}")
    state_dir = root / config.WORKSPACE_STATE_DIR
    if state_dir.exists():
        raise click.UsageError(
            f"{state_dir} exists but {root} has no {config.WORKSPACE_FILE_NAME}: it may be an earlier canopy's "
            f"journal, which a new workspace must not take over. Move it aside, or run `canopy init` elsewhere.",
        )
    checkout = hostgit.git_root(root)
    if checkout is None or checkout == home or in_checkout:
        return
    message = (
        f"{root} is inside the git repository {checkout}, and canopy writes nothing into a code repository. {new_dir}"
    )
    old = workspace.old_repo_file(root)
    if old is not None:
        message += f" {old} is not read: move its keys to {config.WORKSPACE_FILE_NAME} in the new workspace (D016)."
    raise click.UsageError(f"{message} Pass --workspace if this repository holds only the workspace's own files.")


def _provider(provider: str | None, shared_file: Path, what: str) -> str | None:
    """Return the tracker provider for a new shared file, asking for it on a terminal. None if the file exists.

    Raises:
        click.UsageError: No provider is given for a new file and stdin is not a terminal, or the provider is invalid.
    """
    if provider is None and not shared_file.exists():
        if not sys.stdin.isatty():
            raise click.UsageError(f"the {what} has no {shared_file.name}; pass --provider (jira, github, linear, ...)")
        answer: str = click.prompt(f"Tracker provider for this {what} (jira, github, linear, ...)")
        provider = answer.strip().lower()
    if provider is not None and not init.valid_provider(provider):
        raise click.UsageError(f"invalid provider {provider!r}: use a short lowercase name such as jira or github")
    return provider


def _init_workspace(click_ctx: click.Context, root: Path, provider: str | None, repos: Sequence[str]) -> int:
    user_file = config.user_config_path()
    report = setup_workspace.run_init(root, user_file, provider)
    _print_files(report)
    if report.label is not None:
        click.echo(f"\nYour queue label is {report.label!r}. Add it to a ticket to hand the ticket to canopy.")
    map_file = root / config.WORKSPACE_FILE_NAME
    if map_file in report.written and not repos:
        click.echo(
            f"Edit tracker.query and add each repository under [repos.<name>] in {map_file}, describe them in "
            f"{workspace.MAP_FILE_NAME}, then run `canopy workspace sync`. Or pass clone URLs to "
            f"`canopy workspace add`, which adds and syncs them.",
        )
    try:
        ws = workspace.load(root)
        cfg = config.load(root, user_file, runner_of(click_ctx))
    except config.ConfigError as e:
        click.echo(f"\nThe config does not load yet; fix it before the first tick:\n{e}")
        if repos:
            raise CliError("nothing was added or synced; fix the config, then run `canopy workspace add`") from e
        return 0
    synced: list[setup_workspace.Checked] = []
    if repos:
        click.echo()
        synced = cli_workspace.sync(click_ctx, dry_run=False, add=repos)
        ws = workspace.load(root)
        click.echo(
            f"\nWrite a one-line summary for each repository in {map_file}, and describe them in "
            f"{workspace.MAP_FILE_NAME}: the overseer reads both to choose repositories. Edit tracker.query too.",
        )
    click.echo()
    click.echo(init.BRANCH_PROTECTION.format(prefix=cfg.trust.branch_prefix), nl=False)
    click.echo(setup_workspace.protection_targets(ws), nl=False)
    if sandbox := init.sandbox_suggestion(cfg.runtime, user_file):
        click.echo()
        click.echo(sandbox, nl=False)
    # A repository can carry copies of canopy's agents that an earlier single-repository init committed there.
    report.shadowing += [path for repo in ws.repos if repo.cloned for path in project_config.shadowing(repo.path)]
    _print_shadowing(report)
    _print_own_servers(ws)
    cli_workspace.check_synced(synced)
    return 0


def _print_files(report: init.Report) -> None:
    for path in report.written:
        click.echo(f"wrote   {path}")
    for path in report.updated:
        click.echo(f"updated {path}")
    for path in report.kept:
        click.echo(f"kept    {path}")


def _print_shadowing(report: init.Report) -> None:
    if report.shadowing:
        click.echo()
        click.echo(f"Warning: {project_config.shadowing_message(report.shadowing)}")
        click.echo(
            "  Earlier versions of `canopy init` put them there. Agent runs refuse to start until they are gone.",
        )


def _print_own_servers(ws: workspace.Workspace) -> None:
    places = [ws.root, *(repo.path for repo in ws.repos if repo.cloned)]
    named = project_config.naming_servers(places, OWN_SERVERS)
    if named is not None:
        click.echo()
        click.echo(f"Warning: {named}")
        click.echo("  A review, a plan, or a chore refuses to start where the runtime reads it.")


@click.group("sandbox")
def sandbox_group() -> None:
    """Run agents in an OS sandbox (docs/SANDBOX.md)."""


@sandbox_group.command("setup")
@click.pass_context
def cmd_sandbox_setup(click_ctx: click.Context) -> int:
    """Install what sandboxed runs need, and say what is left to do.

    Copies canopy-sandbox's policy templates to ~/.config/canopy/sandbox/, keeping any already there. Installs the srt
    canopy pins, with npm, in ~/.local/share/canopy/sandbox-runtime/. Checks what needs root, and prints how to do it:
    bubblewrap, socat, and ripgrep on Linux, ripgrep on macOS, and user namespaces. Changes no config: prefix your
    command templates with canopy-sandbox to use the sandbox. Run it again after upgrading canopy. Exits 1 while
    something is left to do.
    """
    report = setup_sandbox.run_setup(runner_of(click_ctx))
    for path in report.written:
        click.echo(f"wrote   {path}")
    for path in report.kept:
        click.echo(f"kept    {path}")
    if report.runtime:
        click.echo(report.runtime)
    for item in report.todo:
        click.echo(f"\nTo do: {item}")
    user_file = config.user_config_path()
    click.echo(
        "\nFill in your hosts in each template: your model provider, your tracker's and other MCP services,\n"
        "and the registries your builds fetch from (docs/SANDBOX.md, step 3).",
    )
    runtime = _runtime(runner_of(click_ctx), user_file)
    if suggestion := init.sandbox_suggestion(runtime, user_file, text=init.SANDBOX_NEXT):
        click.echo()
        click.echo(suggestion, nl=False)
    return 1 if report.todo else 0


def _runtime(runner: procs.Runner, user_file: Path) -> config.Runtime:
    """The `[runtime]` this workspace's config sets, or the built-in one outside a workspace or if it does not load."""
    root = workspace.find_root(Path.cwd())
    if root is not None:
        with contextlib.suppress(config.ConfigError):
            return config.load(root, user_file, runner).runtime
    return config.Runtime()


@click.command("skill")
@click.option(
    "--install",
    "skills_dir",
    is_flag=False,
    flag_value=SKILLS_DIR,
    metavar="[DIR]",
    help="Save the skill as canopy/SKILL.md in DIR, where your agent runtime reads skills, instead of printing it. "
    f"DIR defaults to {SKILLS_DIR}.",
)
def cmd_skill(skills_dir: str | None) -> int:
    """Print the canopy skill for your own agent sessions, or save it with --install.

    Save it where your agent runtime reads skills, and again after upgrading canopy:

    \b
        canopy skill --install
        canopy skill --install ~/.claude/skills
    """  # noqa: D301  (\b is click's marker for a paragraph it must not rewrap)
    text = resources.operator_skill().read_text(encoding="utf-8")
    if skills_dir is None:
        click.echo(text, nl=False)
        return 0
    path = Path(skills_dir).expanduser() / "canopy" / "SKILL.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        raise CliError(f"could not save the skill: {e}") from None
    click.echo(f"wrote {path}")
    return 0


@click.command("completion")
@click.argument("shell", type=click.Choice(tuple(SHELLS)))
@click.pass_context
def cmd_completion(click_ctx: click.Context, shell: str) -> int:
    """Print the script that completes canopy's commands, options, and names in your shell.

    It completes repository and chore names from the workspace you are in. Load it from your shell's startup file
    (bash needs 4.4 or newer):

    \b
        echo 'eval "$(canopy completion bash)"' >> ~/.bashrc
        echo 'eval "$(canopy completion zsh)"' >> ~/.zshrc
        canopy completion fish > ~/.config/fish/completions/canopy.fish
    """  # noqa: D301  (\b is click's marker for a paragraph it must not rewrap)
    script = SHELLS[shell](click_ctx.find_root().command, {}, "canopy", COMPLETE_VAR)
    # The template rather than `source()`, whose bash version check runs bash outside canopy.infra.procs.
    click.echo(script.source_template % script.source_vars(), nl=False)
    return 0


@click.command("secret")
@click.option("--rotate", is_flag=True, help="Replace the secret with a new one, signing every browser out.")
def cmd_secret(*, rotate: bool) -> int:
    """Print the listener secret the web UI's sign-in asks for, making one first if there is none.

    It is kept in a file only you can read, next to your user config. `canopy loop` reads it when it starts serving;
    restart the loop after --rotate.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"secret refused ({r.guard}): {r.reason}") from None
    path = secret.path()
    try:
        value, written = secret.create(path, rotate=rotate)
    except secret.SecretError as e:
        raise CliError(str(e)) from None
    click.echo(f"{'wrote' if written else 'kept '} {path}", err=True)
    if written and rotate:
        click.echo("Every browser is signed out once the loop restarts.", err=True)
    click.echo(value)
    return 0
