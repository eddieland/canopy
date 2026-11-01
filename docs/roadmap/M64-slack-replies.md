# M64. Slack replies

DESIGN §20, §22, and §30, TRUST_MODEL T1, T2, and T7, D035, D072. Asked for by the operator (2026-10-23): answer a
ticket from its Slack thread as `canopy reply` answers it, without a listener. Reading a thread is an outbound call, as
posting one is, so it runs as a connector the loop already polls (§30, §6 Ticks and polls): not a listener (T8, D055),
not a background service, and no network in the harness (T2). Needs M36's sources and polls, which are built; not M37,
since a reply is recorded as the operator's own message through `conversation.reply`, as every channel's is. Two
stages, in order, each in its own PRs.

- **Stage 1, reading threads.** `canopy-connect-slack`, a second command in the `canopy-notify-slack` member,
  importing nothing from canopy, on click (D025). It reads the sink's bot token file, held to the sink's checks, and
  its threads file, and calls `conversations.replies` for each ticket's threads of the last `--days` (3, at most 7).
  It prints a `reply` line for each message one of the ids canopy asks for wrote (stage 2: the source's `operators`,
  and it refuses to run without one), nobody else's: the thread's ticket key, the Slack user
  id, the message's `ts`, and its text with Slack's escaping undone, whole, since canopy refuses an overlong reply
  (4000 characters, `conversation.MAX_OPERATOR`) rather than cut it; then §30's `end` line, naming the tickets whose
  threads were each read whole. It skips a thread's first post and any message with no user, a `bot_id`, or a
  `subtype`: its own posts, a bot posting under a person's name, and joins. An edited message is printed as it reads
  now. Review threads and the channel itself are not read.
- The sink keeps each ticket's threads for a week, not only today's, so a reply in yesterday's thread still reaches
  its ticket: the threads file's version 2, which reads version 1. Losing the file still costs nothing worse than
  replies no longer read.
- Stage 1 checks Slack's current limits on `conversations.replies` for an app installed in one workspace before it
  settles how many threads one run reads; the number goes in `docs/MEASUREMENTS.md` if a limit bounds it.
- **Stage 2, replies in the conversation.** A `slack` source kind, at most one, with `operators`, the Slack user ids
  whose replies are the operator's (private, T7). The tick and the loop's polls run it as they run the others; on stdin
  it gets the repository the sink files its threads under. Each `reply` line from a listed
  id, on a ticket canopy knows, is recorded by `conversation.reply` with `channel="slack"` and the message's `ts` as
  its submission id, so a message read again on the next poll records nothing new. Any other line is skipped and
  counted in the source's run, never recorded, not even as data. A reply ends the loop's wait as any operator message
  does; when it resumes a worker, the thread's next post, the run's `run.started`, shows the operator it was read.
- Stage 2 changes TRUST_MODEL T1 (a channel that proves the operator by Slack user ids listed in private config, read
  by a program holding the operator's token), T2 (the bot token also reads its channel's history), and §7 (give it
  only `chat:write` and the one history scope its channel needs; whoever controls a listed Slack account resumes a
  ticket's worker as the operator). DESIGN §20's "Two-way, later" and §22's channels, and D035's rejected line, say
  the same. Its PR says what the change lets the loop do.
- **Stage 3, mentions, and what came of them.** Asked for by the operator (2026-10-23): answer a ticket with no
  thread. The reader also reads the channel for a top-level message an operator wrote that starts by mentioning the
  app's bot user (`auth.test` names it), then a ticket's key, then the reply, and prints it as a `reply` line with
  `via` `mention`, recorded as a thread's reply is; one naming no key prints with none. A `replies` event group:
  `reply.recorded` for a mention, in the transaction that records it, and `reply.refused` for any operator's reply
  canopy took nothing from, once per Slack message. The sink acknowledges a mention in the ticket's thread, starting
  one, and answers a refusal under the operator's own message. TRUST_MODEL T1 says the same.
- Not in this milestone: plans approved, tickets started or stopped, tasks, chores, or reviews answered from Slack;
  replies from people not listed, as data; a reply edited after it was recorded; Socket Mode; the overseer reading
  Slack through MCP.
- Tests with the fakes: a fake Web API whose threads hold the operator's reply, a coworker's, a bot's under the
  operator's name, a join, and an edit, and the bot's and the join are not printed; yesterday's thread is read and
  the fourth day's is not; a thread Slack refuses leaves its ticket out of the `end` line; a version 1 threads file
  is read; a listed id's reply resumes a blocked ticket with the reply as its instruction, and the same line on the
  next poll records nothing; an unlisted id's line, and one for a ticket canopy does not know, record nothing and are
  counted; a reply recorded by a poll ends the loop's wait.

## Config

```toml
[connect.sources.slack]  # private (TRUST_MODEL T7)
kind = "slack"
cmd = "canopy-connect-slack --channel C0123ABCD --days 3"  # the sink's own --channel
operators = ["U0123ABCD"]  # Slack user ids whose thread replies are the operator's
```

Accept: the tests above. Live, on a real channel with the sink on `--threads`: a worker's question posts in its
ticket's thread; the operator's reply there resumes the worker within `connect.every_minutes` of a waiting loop, with
the reply as its instruction, recorded in the journal with the channel `slack`; a coworker's reply in the thread
records nothing; a reply in the previous day's thread reaches its ticket; `@canopy KEY reply` on a ticket with no
thread reaches it and is acknowledged in a thread the sink starts for it, and one naming a key canopy does not know is
answered under the message with why.

Status: deferred 2026-11-01. The operator cannot get their Slack app read access to its channel, so Accept's live
check cannot run; the three stages stay built. Stage 1 is built (2026-10-23): `canopy-connect-slack` prints the
replies people wrote in the sink's ticket threads, and the sink keeps a week of each ticket's threads. Stage 2 is built
(2026-10-23): the `slack` source kind and its `operators`, a listed id's reply recorded as the operator's message on
the channel `slack`, on the tick's and the poll's runs alike, none in a dry run; a thread Slack no longer has reads as
one with no replies. Stage 3 is built (2026-10-23): a mention of canopy's bot answers any ticket canopy knows, and the
`replies` events tell the operator in Slack what came of a mention or a refused reply.
