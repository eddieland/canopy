# M63. Attachments on tickets and tasks

DESIGN §22 and §36, TRUST_MODEL T1, T3, T6, and T8. Asked for by the operator (2026-10-23): attach the design docs
people send them to a ticket or a task, to have its runs review them against the repository, held strictly to a few
files, a size per file, and a size per ticket or task. The operator settled three points the same day: text files
only, on tasks and on every ticket, public ones too, with the limits as config keys under ceilings in code.

- **Stage 1, attaching.** `canopy attach REF FILE` (`--name`; `-` reads stdin, with `--name`) and
  `canopy detach REF NAME`, on a ticket canopy knows or a task not stopped, refused inside a tick or any run
  (`inside_run`); `canopy show` lists a subject's attachments. An `attachments` table; the text kept as a plan is, in
  `<state_dir>/attachments/`; a removed one's file deleted and its row kept. `policy.max_attachments` (5),
  `max_attachment_kib` (512), and `max_attachments_total_kib` (1024), under ceilings of 20, 1024, and 4096, which the
  workspace file may only lower. Only UTF-8 text with no NUL, never blank.
- **Stage 2, runs read them.** Each run of a ticket (`implement`, `resume`, its plan) and of a task gets a copy of its
  subject's attachments in its slot, excluded from git, each read bounded, never through a link, and checked against
  its hash, and removed before the slot is returned; its prompt names them as data. A push holding one is refused as a
  plan's copy is. TRUST_MODEL T6: on a public ticket, keeping an attachment's text off the tracker is the prompt's
  rule, as for the operator's messages.
- **Stage 3, the web UI.** Attach and remove on a task's page and a ticket's, one file per request within the server's
  body bound, written through `runs/attachments.py`; the three limits on Settings' Limits and trust page, within
  their ceilings (TRUST_MODEL T8).
- Tests with the fakes: an attachment kept operator-only and shown; each limit, a name taken, text that is not
  UTF-8, holds a NUL, or is blank, a stopped task, and an unknown ticket refused; a removed file deleted and its row
  kept; the copy in a ticket's run and a task's, named in the prompt and gone from the returned slot; a file changed
  since it was attached left out; the web's upload and removal, and its limits.

Accept: on the operator's workspace, a design doc attached to a task asking for a review against the code, and to a
private ticket, each read by its next run, whose report or plan cites it.

Status: in progress. All three stages are built: `canopy attach` and `detach`, the `attachments` table, and the three
limits; each ticket's run, plan and feedback plan among them, and each task's, copies its subject's attachments and
names them in its prompt; and a ticket's and a task's pages upload and remove them, with the limits on Settings. Left:
the live check in Accept.
