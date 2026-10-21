---
name: tracker-jira
description: How canopy agents use Jira through the Atlassian MCP server. Load when the tracker provider is jira.
---

# Jira for canopy agents

What is specific to Jira as canopy's tracker. Where a tool named here differs from what your Atlassian MCP server
exposes, use the closest equivalent.

## Keys

The ticket key is the Jira issue key as-is: `PROJ-123`.

## Finding tickets

`tracker.query` is JQL: run it through the server's JQL search tool. Atlassian remote MCP tools usually need a cloud
id; if they ask for one, resolve it once per run from the accessible-resources tool and reuse it. The query only finds
tickets: confirm the label is in each result's `labels` field before treating it as a candidate.

## Closed

A ticket is closed when its status category is Done. Do not match on status names; they differ per project and workflow.

## Identities

Comment authors are identified by `accountId`. Compare `trust.authorized_repliers` against it exactly. Display names
and email addresses are not identities; two people can share a display name.

## Labels

Jira labels cannot contain spaces. Set them with the issue edit tool (on Atlassian's remote server, `editJiraIssue`
with only `labels` in its fields), never with a command-line client, and pass no other field. Editing fields cannot
change an issue's status; that takes a transition, which canopy agents never make. An edit may replace the whole list:
read the current labels immediately before the edit, not earlier in the run, add or remove only the one you mean to,
and write the full list back, dropping or re-adding no other label.

When a label was added is in the issue changelog; if the server cannot read the changelog, use the timestamp of the
worker's question comment.

## Creating tickets

Only an `implement` or `resume` worker creates issues, the follow-ups its prompt allows. Create each in the parent's
project, with the parent's issue type unless that type cannot be created, with an empty `labels` field and no assignee.
Link it to the parent with a "relates to" link, not as a subtask; a private ticket's worker, which has the create tool
and no link tool, names the parent in the body instead, on a line of its own, `Part of <parent key>`. Order the new
issues with "Blocks" links: the earlier one blocks the later one. The new issue's key is the key Jira returns.

## Comments and ordering

Order comments by their created timestamp, and use the comment id as the cursor. Write comments in plain text; the
server converts them to Jira's format.

## Blockers

Blockers are issue links of type "Blocks", read from the inward side ("is blocked by"). A blocker is resolved when its
status category is Done. Other link types ("relates to", "clones") and parent or subtask relations are not blockers.
A blocker's PR is found on GitHub by its head branch, `<branch prefix><KEY>-*`, not from links in the issue.

## Text that acts

Jira smart commits run commands found in commit messages: `PROJ-123 #done`, `#resolve`, `#close`, `#comment`, `#time`,
or any `#<transition-name>`. Never write `#` followed by a word after an issue key in a commit message, PR title, or PR
body. Mention the key plainly (`PROJ-123: add retry to uploader`).
