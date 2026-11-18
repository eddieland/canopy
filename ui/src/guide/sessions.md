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

Set it to `"text"` and the loop also keeps an index of what each session said, did, and read, in
`.canopy/sessions.db`: words only, no copy of the text, built newest first in the waits between ticks, so last week's
sessions are findable long before last year's. Going back below `text` deletes the file on the loop's next wait. Under
runtime version 1, `text` behaves as `titles`, and says so.

## The list

Each row is a session: where it opens, its title, what it cost, and when it started. A subagent's session sits under
the one it ran for, marked `subagent`. The runtime's own list leaves archived sessions out, and so
does this page until you press `archived`. It shows the newest 50 sessions with their subagents under them, so the
count in the header, which counts every row, can read higher: `newest 53`. When more match, the line at its foot links
to the newest 500, and back; the same line says how far the loop's read has come. At `text` a second line reports on
the index. While the first build is still working its way back through your history it leads with that, `Still
indexing`, and says how many sessions so far and how far back it has got; once built, it says what it holds and up to
when.

Under a title sits the session's model, when anything recorded one: the model it was asked to run on, and, when
something else answered, what did. A session set to a router reads `github-copilot/auto → github-copilot/gpt-5`,
which is the only place the runtime admits `auto` was ever involved, since every reply names the model it was routed
to. For one of canopy's, what was asked is what canopy asked for its run. `canopy sessions --model github-copilot/auto`
lists just the sessions asked for a model or served by it, which is how you find out where your router has been.

**Outside canopy**, the default, is yours, in any directory, and other workspaces' canopy runs, which this workspace
doesn't know. A row shows the end of the directory the session ran in, `…/acme/infra`, the whole on hover, and under
its title the command that reopens it there:

```sh
cd /home/you/acme/infra && opencode --session ses_3f9c2a1b
```

Hover the row, or tab to it, and its copy button shows beside the command. **canopy's** lists this workspace's runs'
sessions instead, each opening the page of what made it: a tick, a run, a review, a chore run, a task's run, or an
epic. That page has its transcript while the run's log is kept.

## Narrowing to a directory

A title is whatever the runtime made of your first words; where you were is usually the better memory. So a row's
directory is a link: click it and the list narrows to the sessions that ran in that directory, exactly, not the ones
below it. A subagent that ran there while its parent ran somewhere else gets a row of its own, so nothing that ran in
the directory goes missing. The header says `in …/acme/infra` while it's narrowed, and its `×` clears it. The count and
the link to the newest 500 follow the narrowed list, since canopy narrows it before it picks the newest. The directory
sits in the address with the other filters, so you can link to a narrowed list, and Back undoes it. Typing a directory
`exclude` names into the address gets you an empty list: the URL is not a side door.

## Finding one

The field at the top of the list finds sessions by the words in their titles, or at `text` by what they said too,
the best match first, each with the snippet that got it found. It works with the filters, not instead of them: narrow
to a directory, switch to canopy's, include the archived, and the words stay put. That's the query this page exists
for, "the one in `…/acme/infra` where I mentioned the lockfile", and the only place you can ask it. A subagent's
session that matches gets a row of its own here, marked `subagent`, since its parent may not match at all. The words
live in the address as `?q=`, so a search is a link.

Search, the box at the top of every page, finds sessions too, among everything else in the journal, 20 of each kind:
see [Search](overview#search). Each of its session panels has a `find in Sessions` link that brings the same words
here. The command line has the same list, `canopy sessions` for yours and
`canopy sessions --canopy` for canopy's, with words to find one and `--json` for scripts; at `text` it also prints each
hit's snippet, the words marked, and how many more of its messages hold them.

## What it never shows

At `titles`, a title is all canopy reads of a session for this page; at `text`, the index knows its words, but canopy
still has no reader for a session: yours reopens in the runtime, and canopy's has its run's transcript. canopy's own
sessions are never found by what canopy sent them, a prompt being the journal's text, which Search finds already. A
title is whatever the runtime made of the first words, ticket text among them, so it's shown as text and nothing in it
is a link; a snippet is the same. No agent canopy runs can list or search these: a worker never reads your other
sessions through canopy.
