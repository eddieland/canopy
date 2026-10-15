-- What the web UI reads on every journal commit, by index (DESIGN §22). On a journal with a year of history, a hundred
-- thousand ticks, tens of thousands of runs, and hundreds of thousands of decisions, each read was a scan of every row
-- ever recorded, and every open event stream made them all again on each commit.

-- The runs list: the runs that ended last.
CREATE INDEX runs_ended ON runs(ended_at);

-- The spend: what every agent run started since a time cost, read from the index alone.
CREATE INDEX runs_spent ON runs(started_at, cost_usd);
CREATE INDEX chore_runs_spent ON chore_runs(started_at, cost_usd);
CREATE INDEX review_runs_spent ON review_runs(started_at, cost_usd);
CREATE INDEX ticks_spent ON ticks(started_at, cost_usd);

-- The tickets list: the tickets a tick saw last, the tickets with the newest messages, each one's newest message, and
-- the newest starts and stops. Without the third, SQLite read a ticket's newest message through the second, from the
-- newest message of any ticket.
CREATE INDEX tickets_seen ON tickets(last_seen_at);
CREATE INDEX messages_at ON messages(subject_kind, at);
CREATE INDEX messages_subject_at ON messages(subject_kind, subject_id, at);
CREATE INDEX starts_at ON starts(subject_kind, coalesce(stopped_at, started_at));

-- The PRs list: the review runs that ended last, and the unit that has each PR. A PR's page: its latest decisions.
-- Most decisions name no PR, so only those that do are indexed.
CREATE INDEX review_runs_ended ON review_runs(ended_at);
CREATE INDEX ticket_units_pr ON ticket_units(pr_url);
CREATE INDEX decisions_pr ON decisions(pr, id) WHERE pr IS NOT NULL;

-- A ticket's page: what the review runs naming it cost.
CREATE INDEX review_runs_ticket ON review_runs(ticket_key);

-- A chore's runs, newest first, for its page and its findings. Its runs by start served that by sorting them all.
CREATE INDEX chore_runs_newest ON chore_runs(chore, id);
