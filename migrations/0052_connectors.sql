-- The connectors (DESIGN §30, ROADMAP M36): what each tick's run of a source read of the world, and each run. Every
-- observation is replaced whole on the next run that reads its subject whole (a ticket, a PR, a repository), so a
-- label, check, or branch gone from the source is gone from here; a subject not read whole keeps its rows and their
-- age. Nothing here is authority: an observation says what a connector saw and when.

-- A PR's labels, as a JSON list of names, and whether it can merge as its host says.
ALTER TABLE observed_prs ADD COLUMN labels TEXT NOT NULL DEFAULT '[]';
ALTER TABLE observed_prs ADD COLUMN mergeable_state TEXT CHECK (
    mergeable_state IN ('clean', 'behind', 'blocked', 'dirty', 'draft', 'has_hooks', 'unstable', 'unknown')
);

-- A ticket as the tracker connector last read it whole. `labels` is a JSON list of `{"name", "added_at"}`, `added_at`
-- null where the tracker does not say; `blockers` a JSON list of the keys it names as blocking it.
CREATE TABLE observed_tickets (
    key          TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('open', 'closed')),
    labels       TEXT NOT NULL,
    updated_at   TEXT,
    blockers     TEXT NOT NULL,
    observed_at  TEXT NOT NULL
);

-- Each comment the tracker connector read, once per ticket and comment id, as it first read it: an edit after is not
-- followed, as a mirrored comment's is not. Kept apart from `messages`, so no prompt carries a comment the overseer
-- did not mirror (DESIGN §30). `body` is cut at the mirror's length, `truncated` saying so; `source` is `worker` when
-- the comment carries the workers' marks (D069).
CREATE TABLE observed_comments (
    ticket        TEXT NOT NULL,
    id            TEXT NOT NULL,
    author        TEXT NOT NULL,
    commented_at  TEXT NOT NULL,
    body          TEXT NOT NULL,
    truncated     INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    source        TEXT NOT NULL CHECK (source IN ('tracker', 'worker')),
    observed_at   TEXT NOT NULL,
    PRIMARY KEY (ticket, id)
);

-- Each branch under `trust.branch_prefix` in a repository of the map, by the map's name for it.
CREATE TABLE observed_branches (
    repository   TEXT NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    observed_at  TEXT NOT NULL,
    PRIMARY KEY (repository, name)
);

-- Each named context at a PR's head, a check run or a commit status, never the combined status.
CREATE TABLE observed_checks (
    pr_url       TEXT NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (
        status IN ('requested', 'queued', 'waiting', 'pending', 'in_progress', 'completed')
    ),
    conclusion   TEXT CHECK (
        conclusion IN (
            'success', 'failure', 'error', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
            'startup_failure', 'stale'
        )
    ),
    run_id       INTEGER,
    url          TEXT,
    observed_at  TEXT NOT NULL,
    PRIMARY KEY (pr_url, name)
);

-- Each run of a source: a tick's, or the loop's poll between ticks, whose `tick_id` is NULL. `request` is what it was
-- sent, as JSON; `recorded` and `refused` count its lines of each kind, as a JSON object; `missed` is the harness's
-- words for what it did not read, NULL for an `ok` run. The query's and the review query's results, as JSON lists of
-- keys and URLs in order, are kept when the run read them to the end.
CREATE TABLE connector_runs (
    id                   INTEGER PRIMARY KEY,
    tick_id              INTEGER REFERENCES ticks(id),
    source               TEXT NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('tracker', 'vcs')),
    started_at           TEXT NOT NULL,
    ended_at             TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'failed')),
    request              TEXT NOT NULL,
    recorded             TEXT NOT NULL,
    refused              TEXT NOT NULL,
    missed               TEXT,
    stderr               TEXT NOT NULL,
    query_result         TEXT,
    review_query_result  TEXT,
    CHECK ((status = 'ok') = (missed IS NULL))
);
CREATE INDEX connector_runs_source ON connector_runs(source, id);
CREATE INDEX connector_runs_tick ON connector_runs(tick_id);
