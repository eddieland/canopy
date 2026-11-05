-- What the loop reads on every step of its wait, at every tick, and at every spawn, by index (DESIGN §6). On a journal
-- of a year's work across a handful of repositories, tens of thousands of tickets, runs, reviews, and chore runs, and
-- hundreds of thousands of messages and decisions, each of these was a scan of every row ever recorded. A wait's probe
-- that finds nothing, as an idle wait's do, reads to the end of its table, twice a second.

-- The wait: the newest operator message to a ticket, and whether a run ended, a ticket was started or stopped, or a
-- review was requested, since the tick read the journal.
CREATE INDEX messages_operator ON messages(subject_kind) WHERE source = 'operator';

CREATE INDEX chore_runs_ended ON chore_runs(ended_at);

CREATE INDEX task_runs_ended ON task_runs(ended_at);

CREATE INDEX epic_runs_started ON epic_runs(started_at);

CREATE INDEX epic_runs_ended ON epic_runs(ended_at);

CREATE INDEX starts_started ON starts(started_at);

CREATE INDEX starts_stopped ON starts(stopped_at);

CREATE INDEX review_requests_created ON review_requests(created_at);

-- A tick: the open tickets and the done ones, those marked done lately (each done ticket's newest `done` decision),
-- each ticket's attempts of a kind, the newest comment the tracker reported on each ticket, the PRs last seen open, and
-- the ticks and overseer runs a dead tick process left running.
CREATE INDEX tickets_done ON tickets(done, key);

CREATE INDEX decisions_done ON decisions(ticket_key, id) WHERE action = 'done';

CREATE INDEX runs_ticket_kind ON runs(ticket_key, kind);

CREATE INDEX observed_comments_newest ON observed_comments(ticket, commented_at);

CREATE INDEX observed_prs_state ON observed_prs(state);

CREATE INDEX ticks_running ON ticks(status) WHERE status = 'running';

CREATE INDEX overseer_runs_running ON overseer_runs(status) WHERE status = 'running';

-- A spawn: the runs the overseer asked for that wait to start, and the ticket a branch is already claimed for.
CREATE INDEX recorded_runs_waiting ON recorded_runs(status) WHERE status = 'recorded';

CREATE INDEX tickets_branch ON tickets(branch) WHERE branch IS NOT NULL;

-- A run's own messages, read back after it ends and on its page, and a review run's answers.
CREATE INDEX messages_run ON messages(run_id) WHERE run_id IS NOT NULL;

CREATE INDEX messages_task_run ON messages(task_run_id) WHERE task_run_id IS NOT NULL;

CREATE INDEX review_answers_review ON review_answers(review_run_id);
