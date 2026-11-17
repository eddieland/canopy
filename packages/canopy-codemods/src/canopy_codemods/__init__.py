"""canopy-codemods: the mechanical rewrites canopy's own code is held to, applied to files or checked against them.

`canopy-codemods PATHS` rewrites the Python under the paths with every codemod in `registry.CODEMODS`, and
`--check` changes nothing: it prints the diff each would make and fails when there is one, which is how the lint holds
the repository to them. A codemod is a `libcst.codemod` command, so it keeps every comment and blank line it does not
touch. The README beside this package says how to add one.
"""

from __future__ import annotations

from pathlib import Path

import click

from canopy_codemods import run
from canopy_codemods.registry import CODEMODS


@click.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option("--check", is_flag=True, help="Change nothing: print the diff, and fail when there is one.")
@click.option(
    "--only",
    "names",
    multiple=True,
    type=click.Choice(list(CODEMODS)),
    help="Run this codemod alone; give it again for each. By default, all of them.",
)
@click.option("--list", "listing", is_flag=True, help="List the codemods and exit.")
def main(*, paths: tuple[Path, ...], check: bool, names: tuple[str, ...], listing: bool) -> None:
    """Rewrite the Python under PATHS, files or directories, with canopy's codemods."""
    if listing:
        for name, codemod in CODEMODS.items():
            click.echo(f"{name}  {codemod.DESCRIPTION}")
        return
    if not paths:
        raise click.UsageError("Give the files or directories to rewrite.")
    rewrites = run.rewrite_all(paths, [name for name in CODEMODS if not names or name in names])
    failed = [rewrite for rewrite in rewrites if rewrite.error is not None]
    changed = [rewrite for rewrite in rewrites if rewrite.changed]
    for rewrite in failed:
        click.echo(f"{rewrite.path}: {rewrite.error}", err=True)
    for rewrite in changed:
        if check:
            click.echo(rewrite.diff(), nl=False)
        else:
            rewrite.path.write_text(rewrite.after, encoding="utf-8")
            click.echo(f"Rewrote {rewrite.path}")
    if failed:
        raise click.ClickException(f"{_files(len(failed))} could not be rewritten")
    if check and changed:
        raise click.ClickException(f"{_files(len(changed))} would be rewritten; run `make fmt`")


def _files(count: int) -> str:
    return "1 file" if count == 1 else f"{count} files"
