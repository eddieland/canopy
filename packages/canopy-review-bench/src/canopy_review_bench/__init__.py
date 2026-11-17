"""canopy-review-bench: score a code review bot on blind PRs whose bugs you know, opened in a repository it reviews.

`check` builds each case's commits and shows them, opening nothing; `run` opens each case's PR in the repository, waits
for the bot's review, takes the PR down, and scores the run; `score` scores a saved run again. The README beside this
package says how to choose cases and stage a bench.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import click

from canopy_review_bench import bench, commits, score
from canopy_review_bench import run as run_module
from canopy_review_bench.github import GitHub

_BENCH: Final = click.Path(exists=True, dir_okay=False, path_type=Path)
_OVERLAY: Final = click.Path(exists=True, file_okay=False, path_type=Path)


@click.group()
def main() -> None:
    """Score a code review bot on blind PRs whose bugs you know, opened in a repository it reviews."""


@main.command("check")
@click.argument("bench_file", type=_BENCH)
@click.option("--case", "names", multiple=True, help="Check this case alone; give it again for each.")
@click.option("--overlay", type=_OVERLAY, help="Write this directory's files into every case's trees.")
def cmd_check(*, bench_file: Path, names: tuple[str, ...], overlay: Path | None) -> None:
    """Build each case's commits in the source clone and show its PR's stat and where its bug is. Opens nothing.

    Read the stats before a run: a PR that deletes the test naming its bug, or a diff far larger than the case's,
    gives the answer away or measures something else.
    """
    loaded, cases, layer = _prepare(bench_file, names, None, overlay)
    failed = 0
    for case in cases:
        try:
            built = commits.build(loaded.source, case, layer)
        except bench.BenchError as e:
            failed += 1
            click.echo(f"{case.name}: {e}", err=True)
            continue
        click.echo(
            f"{case.name}  {case.kind}  {case.source}  {case.split}  base {built.base[:12]} head {built.head[:12]}",
        )
        click.echo("\n".join(f"    {line}" for line in built.stat.splitlines()))
        for spot in built.spots:
            click.echo(f"    bug at {spot} ({spot.side})")
    if failed:
        raise click.ClickException(f"{failed} of {len(cases)} cases cannot be built")


@main.command("run")
@click.argument("bench_file", type=_BENCH)
@click.option("--case", "names", multiple=True, help="Run this case alone; give it again for each.")
@click.option("--split", type=click.Choice(["tune", "holdout"]), help="Run this split's cases alone.")
@click.option("--overlay", type=_OVERLAY, help="Write this directory's files, such as the bot's instructions, in.")
@click.option("--repeat", type=click.IntRange(1, 20), default=1, show_default=True, help="Reviews of each case.")
@click.option("--label", default="", help="What to call the run, such as the bot's version and its instructions'.")
def cmd_run(
    *,
    bench_file: Path,
    names: tuple[str, ...],
    split: str | None,
    overlay: Path | None,
    repeat: int,
    label: str,
) -> None:
    """Open each case's PR in the repository, one at a time, wait for the bot's review, take it down, and score the run.

    Each PR is closed and its branches deleted once its review is read, whatever happened. The run is saved under
    results/ beside the bench file as it goes, and `score` reads it again.
    """
    loaded, cases, layer = _prepare(bench_file, names, split, overlay)
    settings = loaded.file.bench
    plan = run_module.Plan(cases, layer, overlay, repeat, label)
    github = GitHub(settings.repo, settings.host)
    where = run_module.run(loaded, plan, github, said=lambda line: click.echo(line, err=True), clock=run_module.Clock())
    meta, reviews = score.read(where)
    click.echo("\n".join(score.summary(meta, reviews, settings.tolerance)))
    click.echo(f"saved to {where}", err=True)


@main.command("score")
@click.argument("results", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--tolerance", type=click.IntRange(0, 50), help="Lines from a bug a comment may be. Default: the run's.")
def cmd_score(*, results: Path, tolerance: int | None) -> None:
    """Score the run saved in RESULTS again, as Markdown."""
    try:
        meta, reviews = score.read(results)
    except bench.BenchError as e:
        raise click.ClickException(str(e)) from None
    saved = meta.get("tolerance")
    used = tolerance if tolerance is not None else saved if isinstance(saved, int) else 3
    click.echo("\n".join(score.summary(meta, reviews, used)))


def _prepare(
    bench_file: Path,
    names: tuple[str, ...],
    split: str | None,
    overlay: Path | None,
) -> tuple[bench.Loaded, list[bench.Case], commits.Overlay]:
    """Read the bench file, choose its cases, and read the overlay, with the bench's `strip` paths in it.

    Returns:
        The bench, the cases chosen, and the overlay.

    Raises:
        ClickException: any of them is not valid.
    """
    try:
        loaded = bench.load(bench_file)
        cases = bench.chosen(loaded.file.cases, names, split)
        strip = loaded.file.bench.strip
        layer = commits.read_overlay(overlay, strip) if overlay is not None else commits.Overlay({}, strip)
    except bench.BenchError as e:
        raise click.ClickException(str(e)) from None
    return loaded, cases, layer
