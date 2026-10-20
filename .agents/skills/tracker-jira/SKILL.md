---
name: tracker-jira
description: How canopy agents use Jira through the Atlassian MCP server. Load when the tracker provider is jira.
---

# Jira for canopy agents

canopy's tracker contract (DESIGN §17) is the same for every tracker. This skill only covers what is specific to Jira.
If a tool name here does not match what your Atlassian MCP server exposes, use the closest equivalent.

## Keys

The ticket key is the Jira issue key as-is: `PROJ-123`.

## Finding tickets

`tracker.query` is JQL. Run it through the server's JQL search tool. Atlassian remote MCP tools usually need a cloud id;
if they ask for one, resolve it once per run from the accessible-resources tool and reuse it.

The search (`searchJiraIssuesUsingJql` on Atlassian's server) returns one page of issues a call. While its response
names a next page, by a page token or a start offset past the issues returned so far, call it again with the same JQL
and that token or offset. The result is complete when a response names no next page or returns no issues.

The query only finds tickets. Read each result and confirm the label is in its `labels` field before treating it as a
candidate.

## Closed

A ticket is closed when its status category is Done. Do not match on status names; they differ per project and workflow.

## Identities

Comment authors are identified by `accountId`. Compare `trust.authorized_repliers` against `accountId` exactly. Display
names and email addresses are not identities; two people can share a display name.

## Labels

Jira labels cannot contain spaces. Set them with the issue edit tool (on Atlassian's remote server, `editJiraIssue`
with only `labels` in its fields), never with a command-line client. Editing fields cannot change an issue's status;
that takes a transition, which canopy agents never make. An edit may replace the whole list: read the current labels
immediately before the edit, not earlier in the run, add or remove only the one you mean to, and write the full list
back. Never drop or re-add labels you did not mean to touch, and never pass other fields.

When a label was added is in the issue changelog. If the server cannot read the changelog, use the timestamp of the
worker's question comment instead.

## Creating tickets

An `implement` or `resume` worker creates the follow-ups its prompt allows (DESIGN §18); no other agent creates
issues. Create each in the parent's project, with the parent's issue type unless that type
cannot be created, with an empty `labels` field and no assignee. Link it to the parent with a "relates to" link, not as
a subtask; a private ticket's worker, which has the create tool and no link tool, names the parent in the body instead,
on a line of its own, `Part of <parent key>`. Order the new issues with "Blocks" links: the earlier one blocks the later
one. The new issue's key is the key Jira returns for the created issue.

## Comments and ordering

Order comments by their created timestamp. Use the comment id as the cursor. Keep comments plain text; the server
converts them to Jira's format.

## Blockers

Blockers are issue links of type "Blocks", read from the inward side ("is blocked by"). A blocker is resolved when its
status category is Done. Other link types ("relates to", "clones") and parent or subtask relations are not blockers.
A blocker's PR is found on GitHub by its head branch, `<branch prefix><KEY>-*`, not from links in the issue.

## Text that acts

Jira smart commits run commands found in commit messages: `PROJ-123 #done`, `#resolve`, `#close`, `#comment`, `#time`,
or any `#<transition-name>`. Never write `#` followed by a word after an issue key in a commit message, PR title, or PR
body. Mention the key plainly (`PROJ-123: add retry to uploader`).
