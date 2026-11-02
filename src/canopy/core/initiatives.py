"""Initiatives (DESIGN §43): the operator's submissions, the repositories each one's plan reads, and its members.

Only the operator's channels write here, and every write refuses inside a tick or any agent's run (`inside_run`,
TRUST_MODEL T1): the submission is what will authorize an initiative's plan runs, and membership is the operator's
word alone. A tracker's epic, parent, or sub-issue link never makes a ticket a member, and membership authorizes no work
on it: a member is worked only once a label or a start says so, as any ticket is. The overseer never reads an
initiative. `policy.max_initiative_tickets` bounds the members of one, a guard in code (§4).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, records
from canopy.core.conversation import Refused

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from canopy.core.workspace import Workspace

#: The most an initiative's text holds, as an operator message does.
MAX_TEXT = conversation.MAX_OPERATOR
#: A tracker project's key, or an epic's, as a ticket key spells it (DESIGN §18).
KEY_RE = conversation.KEY_RE
MAX_KEY = conversation.MAX_KEY


@dataclass(frozen=True)
class Added:
    """What `add` did: the keys it made members, and those already members of this initiative."""

    added: Sequence[str]
    already: Sequence[str]


def submit(
    conn: sqlite3.Connection,
    workspace: Workspace,
    text: str,
    *,
    repos: Sequence[str],
    project: str | None,
    epic: str | None,
    channel: str,
) -> records.Initiative:
    """Record the operator's initiative, its goal `text`, whose plan reads repositories `repos` (DESIGN §43).

    `repos` may be empty only in a workspace of one repository, which it then reads. `project` names the tracker
    project its breakdown's tickets are filed in, and `epic` a tracker key whose children are put to the operator as
    suggestions; None for either is none.

    Returns:
        The initiative, as recorded.

    Raises:
        Refused: `inside_run` inside a tick or a run, `bad_body` for an empty text or one over `MAX_TEXT` characters,
            `unknown_repo` for a repository the map does not name, or none named in a workspace of several, and
            `bad_key` for a project or an epic that is not a plain key.
        DatabaseError: the row was not recorded, which nothing but a broken journal does.
    """
    conversation.check_operator()
    body = text.strip()
    if not body:
        raise Refused("bad_body", "the initiative's text is empty")
    if len(body) > MAX_TEXT:
        raise Refused("bad_body", f"the initiative's text is {len(body)} characters; the most is {MAX_TEXT}")
    names = _repositories(workspace, repos)
    for option, value in (("--project", project), ("--epic", epic)):
        if value is not None:
            _check_key(value, option)
    with db.transaction(conn):
        insert = records.insert(
            records.Initiative,
            text=body,
            project=project,
            epic=epic,
            channel=channel,
            submitted_at=db.now(),
        )
        initiative_id = int(insert.run(conn).lastrowid or 0)
        rows = records.insert_rows(records.InitiativeRepo, ("initiative_id", "repo"))
        rows.many(conn, [(initiative_id, name) for name in names])
    found = get(conn, initiative_id)
    if found is None:
        raise sqlite3.DatabaseError("the initiative's row was not recorded")
    return found


def get(conn: sqlite3.Connection, initiative_id: int) -> records.Initiative | None:
    """Return initiative `initiative_id`, or None if there is none."""
    return records.select(records.Initiative).where("id = ?", initiative_id).one(conn)


def every(conn: sqlite3.Connection) -> list[records.Initiative]:
    """Return every initiative, the newest first: none is ever deleted."""
    return records.select(records.Initiative).order_by("id DESC").all(conn)


def repos_of(conn: sqlite3.Connection, initiative_id: int) -> list[str]:
    """Return the repositories initiative `initiative_id`'s plan reads, by name, in the order the map gave them."""
    rows = records.select(records.InitiativeRepo).where("initiative_id = ?", initiative_id).order_by("rowid").all(conn)
    return [row.repo for row in rows]


def members_of(conn: sqlite3.Connection, initiative_id: int) -> list[records.InitiativeMember]:
    """Return initiative `initiative_id`'s members, those the operator has not removed, by when each was added."""
    query = records.select(records.InitiativeMember).where(
        "initiative_id = ? AND removed_at IS NULL",
        initiative_id,
    )
    return query.order_by("id").all(conn)


def membership(conn: sqlite3.Connection, key: str) -> records.InitiativeMember | None:
    """Return ticket `key`'s membership of an initiative, or None while it is a member of none."""
    query = records.select(records.InitiativeMember).where("ticket_key = ? AND removed_at IS NULL", key)
    return query.one(conn)


def add(
    conn: sqlite3.Connection,
    initiative_id: int,
    keys: Iterable[str],
    *,
    bound: int,
    channel: str,
) -> Added:
    """Make tickets `keys` members of initiative `initiative_id`, the operator's word alone (DESIGN §43).

    Every key is added or none is: a refusal leaves the members as they were. A key already a member of this initiative
    is left as it is. `bound` is `policy.max_initiative_tickets`, the most members the initiative may then hold.

    Returns:
        The keys it added, in the order given, and those already members.

    Raises:
        Refused: `inside_run` inside a tick or a run, `unknown_initiative` for no such initiative, `bad_key` for a key
            that is not a ticket key, `other_initiative` for a ticket already a member of another, and
            `initiative_full` when the members would then be more than `bound`.
    """
    conversation.check_operator()
    _check_initiative(conn, initiative_id)
    wanted = list(dict.fromkeys(keys))
    for key in wanted:
        _check_key(key, "a ticket key")
    with db.transaction(conn):
        added: list[str] = []
        already: list[str] = []
        for key in wanted:
            found = membership(conn, key)
            if found is None:
                added.append(key)
            elif found.initiative_id == initiative_id:
                already.append(key)
            else:
                raise Refused("other_initiative", f"{key} is a member of init:{found.initiative_id}")
        held = len(members_of(conn, initiative_id))
        if held + len(added) > bound:
            raise Refused(
                "initiative_full",
                f"init:{initiative_id} has {held} members, and policy.max_initiative_tickets lets it hold {bound}",
            )
        if added:
            now = db.now()
            rows = records.insert_rows(
                records.InitiativeMember,
                ("initiative_id", "ticket_key", "added_at", "added_channel"),
            )
            rows.many(conn, [(initiative_id, key, now, channel) for key in added])
    return Added(added=tuple(added), already=tuple(already))


def remove(conn: sqlite3.Connection, initiative_id: int, keys: Iterable[str], *, channel: str) -> list[str]:
    """End tickets `keys`' membership of initiative `initiative_id`, the operator's word alone (DESIGN §43).

    Every key is removed or none is. The rows stay, ended, so what was a member stays to read; the ticket and its work
    are left as they are.

    Returns:
        The keys it removed, in the order given.

    Raises:
        Refused: `inside_run` inside a tick or a run, `unknown_initiative` for no such initiative, `bad_key` for a key
            that is not a ticket key, and `not_member` for one that is not a member of this initiative.
    """
    conversation.check_operator()
    _check_initiative(conn, initiative_id)
    wanted = list(dict.fromkeys(keys))
    for key in wanted:
        _check_key(key, "a ticket key")
    with db.transaction(conn):
        for key in wanted:
            found = membership(conn, key)
            if found is None or found.initiative_id != initiative_id:
                raise Refused("not_member", f"{key} is not a member of init:{initiative_id}")
        now = db.now()
        for key in wanted:
            update = records.update(records.InitiativeMember).set(removed_at=now, removed_channel=channel)
            update.where("initiative_id = ? AND ticket_key = ? AND removed_at IS NULL", initiative_id, key).run(conn)
    return wanted


def _repositories(workspace: Workspace, repos: Sequence[str]) -> list[str]:
    """The repositories an initiative's plan reads: `repos`, each once, or the workspace's only one.

    Returns:
        Their names as the map spells them, in the order given.

    Raises:
        Refused: (`unknown_repo`) a repository is not in the map, or none is named in a workspace of several.
    """
    names = ", ".join(r.name for r in workspace.repos) or "none yet"
    if not repos:
        if len(workspace.repos) == 1:
            return [workspace.repos[0].name]
        raise Refused("unknown_repo", f"--repo is required: name each repository its plan reads ({names})")
    found: list[str] = []
    for repo in repos:
        named = workspace.repo(repo)
        if named is None:
            raise Refused("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
        found.append(named.name)
    return list(dict.fromkeys(found))


def _check_key(value: str, what: str) -> None:
    """Refuse `value` unless it is a plain tracker key (`bad_key`), `what` naming it in the reason.

    Raises:
        Refused: (`bad_key`) it does not match `KEY_RE`, or is over `MAX_KEY` characters.
    """
    if len(value) > MAX_KEY or not KEY_RE.fullmatch(value):
        raise Refused("bad_key", f"{value[:MAX_KEY]!r} is not {what}: it must match {KEY_RE.pattern}")


def _check_initiative(conn: sqlite3.Connection, initiative_id: int) -> None:
    """Refuse an initiative canopy has none of (`unknown_initiative`).

    Raises:
        Refused: (`unknown_initiative`) there is no initiative `initiative_id`.
    """
    if get(conn, initiative_id) is None:
        raise Refused("unknown_initiative", f"canopy has no init:{initiative_id}")
