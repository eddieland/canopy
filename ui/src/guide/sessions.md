# Sessions

Every session the agent runtime keeps, yours and canopy's, newest first, so you can get back to one. This page covers
turning it on, reading the list, and what it never shows.

## Why a list

canopy runs a session for every tick, worker, review, chore, and task, in the same runtime you use by hand, so its
sessions pile up beside yours in the runtime's own list. Finding last Tuesday's conversation about the deploy script
under four hundred overseer ticks is the kind of archaeology nobody budgets for. The Sessions page, under Workspace,
opens on yours, with canopy's a filter away.

## Turning it on

It's off until you say otherwise. Set `sessions.search` to `"titles"` in your private config:

```toml
[sessions]
search = "titles"
exclude = ["/home/you/clients"]
```

The loop already reads the runtime's record between ticks, for spend; at `titles` that read keeps each session's title
too, and whether the runtime archived it. Turning it on reads the record again from its first session, so sessions you
ran before the change get their titles on the loop's next wait. `exclude` names directories, as globs, whose sessions
canopy never lists, by title or otherwise: another client's work, say. Both keys are yours alone, so the shared
workspace file can't set them, and the page can't change them either. Setting it back to `off` drops every title kept
on the loop's next read, and the page lists nothing meanwhile.

## The list

Each row is a session: where it opens, its title, what it cost, and when it started. A subagent's session sits under
the one it ran for, its title a step in, marked `subagent`. The runtime's own list leaves archived sessions out, and so
does this page until you press `archived`. It shows the newest 50 sessions with their subagents under them, so the
count in the header, which counts every row, can read higher: `newest 53`. When more match, the line at its foot links
to the newest 500, and back; the same line says how far the loop's read has come.

**Outside canopy**, the default, is yours, in any directory, and other workspaces' canopy runs, which this workspace
doesn't know. A row shows the end of the directory the session ran in, `…/acme/infra`, the whole on hover, and under
its title the command that reopens it there:

```sh
cd /home/you/acme/infra && opencode --session ses_3f9c2a1b
```

Hover the row, or tab to it, and its copy button shows beside the command. **canopy's** lists this workspace's runs'
sessions instead, each opening the page of what made it: a tick, a run, a review, a chore run, a task's run, or an
epic. That page has its transcript while the run's log is kept.

## Finding one

Search, the box at the top of every page, finds sessions by their titles: see [Search](overview#search). The command
line has the same list, `canopy sessions` for yours and `canopy sessions --canopy` for canopy's, with words to find
one and `--json` for scripts.

## What it never shows

A title is all canopy reads of a session for this page. It doesn't index what a session said or did, and it has no
reader for one: yours reopens in the runtime, and canopy's has its run's transcript. A title is whatever the runtime
made of the first words, ticket text among them, so it's shown as text and nothing in it is a link. No agent canopy
runs can list or search these: a worker never reads your other sessions through canopy.
