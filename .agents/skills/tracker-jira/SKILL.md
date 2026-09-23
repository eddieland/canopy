---
name: tracker-jira
description: How canopy agents use Jira through the Atlassian MCP server. Load when the tracker provider is jira.
---

# Jira for canopy agents

canopy's tracker contract (DESIGN §17) is the same for every tracker. This
skill only covers what is specific to Jira. If a tool name here does not match
what your Atlassian MCP server exposes, use the closest equivalent.

## Keys

The ticket key is the Jira issue key as-is: `PROJ-123`.

## Finding tickets

`tracker.query` is JQL. Run it through the server's JQL search tool. Atlassian
remote MCP tools usually need a cloud id; if they ask for one, resolve it once
per run from the accessible-resources tool and reuse it.

The query only finds tickets. Read each result and confirm the label is in its
`labels` field before treating it as a candidate.

## Closed

A ticket is closed when its status category is Done. Do not match on status
names; they differ per project and workflow.

## Identities

Comment authors are identified by `accountId`. Compare
`trust.authorized_repliers` against `accountId` exactly. Display names and
email addresses are not identities; two people can share a display name.

## Labels

Jira labels cannot contain spaces. Changing labels through an issue edit may
replace the whole list: read the current labels, add or remove one, write the
full list back. Never drop labels you did not mean to touch.

When a label was added is in the issue changelog. If the server cannot read
the changelog, use the timestamp of the worker's question comment instead.

## Comments and ordering

Order comments by their created timestamp. Use the comment id as the cursor.
Keep comments plain text; the server converts them to Jira's format.

## Blockers

Blockers are issue links of type "Blocks", read from the inward side ("is
blocked by"). A blocker is resolved when its status category is Done. Other
link types ("relates to", "clones") are not blockers.

## Text that acts

Jira smart commits run commands found in commit messages: `PROJ-123 #done`,
`#resolve`, `#close`, `#comment`, `#time`, or any `#<transition-name>`. Never
write `#` followed by a word after an issue key in a commit message, PR title,
or PR body. Mention the key plainly (`PROJ-123: add retry to uploader`).
