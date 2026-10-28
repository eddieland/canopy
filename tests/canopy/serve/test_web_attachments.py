"""Attachments through the web UI (DESIGN §22, TRUST_MODEL T8), held to the CLI's functions and guards.

An upload and a removal write through the functions `canopy attach` and `canopy detach` call, with channel `web`, and
their guards refuse them as they refuse the CLI's.
"""

from canopy.core import conversation, db
from canopy.core.context import Context
from canopy.runs import attachments
from tests.canopy.helpers import in_run
from tests.canopy.web_helpers import refused, signed_in_client

DOC = "# Importer\n\nShard the queue by tenant.\n"
TASK = conversation.Ref(conversation.TASK, "1")


def test_a_file_uploaded_to_a_task_is_kept_and_shown_on_its_page(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post("/api/tasks", json={"text": "Review the design."}, headers=headers).status_code == 200
    put = c.put("/api/tasks/1/attachments/design.md", content=DOC.encode(), headers=headers)
    assert put.status_code == 200, put.text
    assert {k: v for k, v in put.json()["attachment"].items() if k != "added_at"} == {
        "name": "design.md",
        "size": 39,
        "channel": "web",
    }
    [kept] = attachments.of(ctx.conn, TASK)
    assert attachments.path(ctx.state_dir, kept).read_text() == DOC
    shown = c.get("/api/tasks/1").json()["attachments"]
    assert [a["name"] for a in shown["items"]] == ["design.md"]
    assert (shown["max_files"], shown["max_file_bytes"], shown["max_total_bytes"]) == (5, 512 * 1024, 1024 * 1024)


def test_a_ticket_s_page_lists_its_attachments_and_a_removal_deletes_one(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post("/api/tickets/PROJ-1/start", json={}, headers=headers).status_code == 200
    assert c.put("/api/tickets/PROJ-1/attachments/design.md", content=b"text", headers=headers).status_code == 200
    db.touch_ticket(ctx.conn, "PROJ-1", ctx.repo)
    assert [a["name"] for a in c.get("/api/tickets/PROJ-1").json()["attachments"]["items"]] == ["design.md"]
    assert c.delete("/api/tickets/PROJ-1/attachments/design.md", headers=headers).json() == {"name": "design.md"}
    assert c.get("/api/tickets/PROJ-1").json()["attachments"]["items"] == []
    gone = refused(c.delete("/api/tickets/PROJ-1/attachments/design.md", headers=headers))
    assert gone == "unknown: PROJ-1 has no attachment named 'design.md'"


def test_an_upload_canopy_cannot_use_is_refused_as_the_cli_refuses_it(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert refused(c.put("/api/tasks/9/attachments/a.md", content=b"x", headers=headers)) == (
        "unknown: canopy has no task:9"
    )
    assert c.post("/api/tasks", json={"text": "look"}, headers=headers).status_code == 200
    binary = c.put("/api/tasks/1/attachments/a.pdf", content=b"%PDF-1.7\n\xff\xfe\x00", headers=headers)
    assert refused(binary).startswith("not_text")
    assert refused(c.put("/api/tasks/1/attachments/.hidden", content=b"x", headers=headers)).startswith("bad_name")
    big = b"x" * (512 * 1024 + 1)
    assert refused(c.put("/api/tasks/1/attachments/big.md", content=big, headers=headers)).startswith("too_large")
    assert attachments.of(ctx.conn, TASK) == []


def test_every_attachment_write_is_refused_inside_a_run(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post("/api/tasks", json={"text": "look"}, headers=headers).status_code == 200
    assert c.put("/api/tasks/1/attachments/design.md", content=DOC.encode(), headers=headers).status_code == 200
    with in_run(7):
        put = c.put("/api/tasks/1/attachments/other.md", content=b"x", headers=headers)
        assert refused(put).startswith("inside_run")
        removed = c.delete("/api/tasks/1/attachments/design.md", headers=headers)
        assert refused(removed).startswith("inside_run")
    assert [a.name for a in attachments.of(ctx.conn, TASK)] == ["design.md"]
