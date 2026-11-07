"""The mock's desks (DESIGN §18): ABC-103's is open, on web's sixth slot, holding work origin lacks.

The mock has no pool or git to ask, so its desks are kept in memory beside its pools' slots, which a desk's open leases
as `operator:KEY` and its close returns, so the worktrees page shows what the ticket's page did. An open takes each
repository's first idle slot, and is refused, as `canopy desk` is, for a repository with none; a close is refused for
the work the seeded desk holds until told to discard it, and a desk opened here holds none.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db, pools
from canopy.runs import checkouts

if TYPE_CHECKING:
    from collections.abc import Callable

    from canopy.core.context import Context

#: The ticket whose desk is open from the start, and the slot of web's pool it holds.
SEEDED = "ABC-103"
SEEDED_SLOT = 6
#: What the seeded desk holds that origin lacks, until a close discards it.
SEEDED_CHANGES = 2


class Desks:
    """The mock workspace's open desks, by ticket, over its pools' slots, which opening and closing lease and return."""

    def __init__(
        self,
        root: Path,
        slots: dict[str, list[pools.Slot]],
        leased_at: Callable[[int], str],
    ) -> None:
        """Open the seeded desk on `slots`, the pools by repository, which the desks change in place.

        Args:
            root: The mock workspace's root, where `checkouts/` would be.
            slots: Each cloned repository's slots, as the worktrees page reads them.
            leased_at: The mock's time, minutes from T0, as its journal's times are written.
        """
        self._root = root
        self._slots = slots
        self._leased_at = leased_at
        self._open: dict[str, checkouts.Desk] = {}
        # Work origin lacks, by ticket: the seeded desk's alone.
        self._unsafe: dict[str, list[checkouts.Unsafe]] = {}
        branch = "agent/ABC-103-billing-v2"
        self._open[SEEDED] = self._desk(SEEDED, branch, {"web": self._lease("web", SEEDED, SEEDED_SLOT - 1, branch)})
        self._unsafe[SEEDED] = [checkouts.Unsafe("web", SEEDED_CHANGES, 0)]

    def find(self, _ctx: Context, key: str) -> checkouts.Desk | None:
        """`key`'s desk, if open.

        Returns:
            The desk, or None.
        """
        return self._open.get(key)

    def open(self, ctx: Context, key: str, repos: Collection[str]) -> checkouts.Desk:
        """Open `key`'s desk as `checkouts.open_desk` does, on each repository's first idle slot.

        Returns:
            The desk.

        Raises:
            CheckoutError: The ticket has no branch, or not in one of `repos`, or a repository has no idle slot.
        """
        with_branch = {str(u.repo): str(u.branch) for u in db.units(ctx.conn, key) if u.repo and u.branch}
        if not with_branch:
            raise checkouts.CheckoutError(f"{key} has no branch in the journal yet: its first implement names one")
        missing = [name for name in repos if name not in with_branch]
        if missing:
            raise checkouts.CheckoutError(
                f"{key} has no branch in {', '.join(missing)}; it has one in {', '.join(with_branch)}",
            )
        chosen = [r.name for r in ctx.workspace.repos if r.name in with_branch and (not repos or r.name in repos)]
        free = {name: self._idle(name) for name in chosen}
        full = [name for name, index in free.items() if index is None]
        if full:
            raise checkouts.CheckoutError(f"could not open {key}'s desk: {full[0]}'s pool has no idle slot")
        branch = with_branch[chosen[0]]
        slots = {name: self._lease(name, key, index, branch) for name, index in free.items() if index is not None}
        desk = self._desk(key, branch, slots)
        self._open[key] = desk
        return desk

    def close(self, _ctx: Context, desk: checkouts.Desk, discard: bool) -> list[checkouts.Unsafe]:  # noqa: FBT001
        """Close `desk` as `checkouts.close_desk` does: refused for the work it holds unless `discard`.

        Returns:
            What it would lose, when it kept the desk for it; else nothing, its slots returned.
        """
        unsafe = self._unsafe.get(desk.key, [])
        if unsafe and not discard:
            return list(unsafe)
        for name, path in desk.slots.items():
            pool = self._slots[name]
            for index, slot in enumerate(pool):
                if slot.path == path:
                    pool[index] = slot.model_copy(
                        update={
                            "status": "available",
                            "branch": "",
                            "detached": True,
                            "lease_id": "",
                            "lease_holder": "",
                            "leased_at": None,
                        },
                    )
        self._open.pop(desk.key, None)
        self._unsafe.pop(desk.key, None)
        return []

    def _idle(self, repo: str) -> int | None:
        pool = self._slots.get(repo, [])
        return next((i for i, slot in enumerate(pool) if slot.status == "available" and not slot.lease_id), None)

    def _lease(self, repo: str, key: str, index: int, branch: str) -> Path:
        pool = self._slots[repo]
        slot = pool[index]
        # On the branch, as a desk's slot is: not detached, as a run's is (D109).
        pool[index] = slot.model_copy(
            update={
                "status": "leased",
                "branch": branch,
                "detached": False,
                "lease_id": f"desk-{key}-{repo}",
                "lease_holder": checkouts.holder_for(key),
                "leased_at": self._leased_at(-15),
            },
        )
        return slot.path

    def _desk(self, key: str, branch: str, slots: dict[str, Path]) -> checkouts.Desk:
        return checkouts.Desk(key, checkouts.path(self._root, key), branch, slots)
