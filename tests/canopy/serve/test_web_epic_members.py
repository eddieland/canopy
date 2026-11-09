"""The operator's word on an epic's members through the web UI (DESIGN §43, TRUST_MODEL T1).

Adding a ticket, registering it against the approved plan's entries, and removing it write through the functions
`canopy epic add` and `canopy epic remove` call, with channel `web`, and their guards refuse them as they refuse the
CLI's.
"""

from canopy.core import epics
from canopy.serve.backend import Backend
from canopy.serve.mock import epics as mock_epics
from tests.canopy.helpers import in_run
from tests.canopy.web_helpers import refused, signed_in_to

APPROVED, PROPOSED, PLANNING = mock_epics.APPROVED, mock_epics.PROPOSED, mock_epics.PLANNING


def members(backend: Backend, epic_id: int) -> dict[str, tuple[list[str], str]]:
    """Each member of the epic, by key, with the entries it is registered against and the channel that added it."""
    with backend.open() as ctx:
        return {
            m.ticket_key: (epics.entries_of(ctx.conn, m.id), m.added_channel)
            for m in epics.members_of(ctx.conn, epic_id)
        }


def test_a_ticket_registered_on_an_entry_from_the_web_fills_its_none_yet(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    route = f"/api/epics/{APPROVED}/members"
    body = {"key": "ABC-105", "entries": ["B3"]}
    # A write needs the session's token, as every write does.
    assert c.post(route, json=body).status_code == 403

    assert c.post(route, json=body, headers=headers).json() == {"key": "ABC-105", "added": True, "entries": ["B3"]}
    assert members(backend, APPROVED)["ABC-105"] == (["B3"], "web")
    board = {e["id"]: e["members"] for e in c.get(f"/api/epics/{APPROVED}").json()["outline"]["entries"]}
    assert board["B3"] == ["ABC-105"]


def test_registering_a_member_again_replaces_its_entries(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    route = f"/api/epics/{APPROVED}/members"
    again = c.post(route, json={"key": "ABC-103", "entries": ["B4", "B3"]}, headers=headers).json()
    # Already a member: its entries replaced, by number, and the channel that added it kept.
    assert again == {"key": "ABC-103", "added": False, "entries": ["B3", "B4"]}
    assert members(backend, APPROVED)["ABC-103"] == (["B3", "B4"], "cli")

    # With none, it is a member of no entry, as `--no-entry` makes it.
    assert c.post(route, json={"key": "ABC-103", "entries": []}, headers=headers).json()["entries"] == []
    found = c.get(f"/api/epics/{APPROVED}").json()
    assert next(m for m in found["members"] if m["key"] == "ABC-103")["entries"] == []
    assert {e["id"]: e["members"] for e in found["outline"]["entries"]}["B1"] == []


def test_a_ticket_of_no_entry_is_added_before_any_plan_is_approved(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    for epic_id in (PROPOSED, PLANNING):
        added = c.post(f"/api/epics/{epic_id}/members", json={"key": f"WEB-{epic_id}", "entries": []}, headers=headers)
        assert added.json() == {"key": f"WEB-{epic_id}", "added": True, "entries": []}
        assert members(backend, epic_id) == {f"WEB-{epic_id}": ([], "web")}


def test_a_member_is_removed_from_the_web_and_its_ticket_left_as_it_is(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    route = f"/api/epics/{APPROVED}/members/ABC-104"
    assert c.delete(route).status_code == 403
    assert c.delete(route, headers=headers).json() == {"key": "ABC-104"}
    assert "ABC-104" not in members(backend, APPROVED)
    found = c.get(f"/api/epics/{APPROVED}").json()
    assert {e["id"]: e["members"] for e in found["outline"]["entries"]}["B2"] == [mock_epics.HELD]
    # Its membership ended, its ticket stays.
    assert c.get("/api/tickets/ABC-104").status_code == 200
    assert refused(c.delete(route, headers=headers)) == f"not_member: ABC-104 is not a member of epic:{APPROVED}"


def test_each_add_is_refused_naming_its_guard(backend: Backend) -> None:
    c, headers = signed_in_to(backend)

    def add(epic_id: int, key: str, *entries: str) -> str:
        body = {"key": key, "entries": list(entries)}
        return refused(c.post(f"/api/epics/{epic_id}/members", json=body, headers=headers))

    assert add(PROPOSED, "ABC-103") == f"other_epic: ABC-103 is a member of epic:{APPROVED}"
    assert add(APPROVED, "ABC-105", "B9") == f"unknown_entry: the approved plan of epic:{APPROVED} has no B9"
    assert add(PROPOSED, "ABC-105", "B1") == (
        f"no_plan: epic:{PROPOSED} has no approved plan, so no entry to register against"
    )
    assert add(APPROVED, "abc 105").startswith("bad_key: 'abc 105' is not a ticket key")
    assert add(99, "ABC-105") == "unknown_epic: canopy has no epic:99"
    # The mock's bound is policy.max_epic_tickets' default, 8: epic 1 holds 4.
    for n in range(4):
        c.post(f"/api/epics/{APPROVED}/members", json={"key": f"WEB-{n}", "entries": []}, headers=headers)
    assert add(APPROVED, "ABC-105") == (
        f"epic_full: epic:{APPROVED} has 8 members, and policy.max_epic_tickets lets it hold 8"
    )
    # A refusal changes nothing.
    assert "ABC-105" not in members(backend, APPROVED)
    assert members(backend, PROPOSED) == {}


def test_a_removal_is_refused_naming_its_guard(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    said = refused(c.delete(f"/api/epics/{PROPOSED}/members/ABC-103", headers=headers))
    assert said == f"not_member: ABC-103 is not a member of epic:{PROPOSED}"
    assert refused(c.delete("/api/epics/99/members/ABC-103", headers=headers)) == "unknown_epic: canopy has no epic:99"
    assert refused(c.delete(f"/api/epics/{APPROVED}/members/abc%20103", headers=headers)).startswith("bad_key:")
    assert "ABC-103" in members(backend, APPROVED)


def test_adding_and_removing_are_refused_inside_a_run(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    with in_run(7):
        added = c.post(f"/api/epics/{APPROVED}/members", json={"key": "ABC-105", "entries": ["B3"]}, headers=headers)
        assert refused(added).startswith("inside_run")
        assert refused(c.delete(f"/api/epics/{APPROVED}/members/ABC-103", headers=headers)).startswith("inside_run")
    assert members(backend, APPROVED) == {
        "ABC-100": ([], "cli"),
        "ABC-103": (["B1"], "cli"),
        "ABC-104": (["B2"], "cli"),
        mock_epics.HELD: (["B2"], "cli"),
    }
