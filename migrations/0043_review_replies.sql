-- Review replies the operator sends (DESIGN §29, ROADMAP M53): what canopy's GitHub reader saw of a PR, the drafts a
-- run wrote in place of the comments it would have posted, each version of a draft's text, and the setting a run was
-- rendered under. Every row the reader writes is replaced on the next whole read of its PR, as ROADMAP M36's
-- observations are; a draft is never edited in place but for its status: its text is its versions.

-- A PR as the reader last read it whole.
CREATE TABLE observed_prs (
    url          TEXT PRIMARY KEY,
    repository   TEXT NOT NULL,
    number       INTEGER NOT NULL,
    head_sha     TEXT,
    base_ref     TEXT,
    state        TEXT CHECK (state IN ('open', 'merged', 'closed')),
    draft        INTEGER NOT NULL,
    mergeable    TEXT,
    author       TEXT,
    observed_at  TEXT NOT NULL
);

-- Each review and review comment of a PR, keyed by GitHub's id, with a comment's thread. Bodies are cut as a mirrored
-- comment's are (DESIGN §22).
CREATE TABLE observed_reviews (
    pr_url       TEXT NOT NULL,
    item         TEXT NOT NULL CHECK (item IN ('review', 'comment')),
    id           INTEGER NOT NULL,
    author       TEXT,
    bot          INTEGER NOT NULL,
    -- A review's state; NULL for a comment.
    state        TEXT CHECK (state IN ('pending', 'commented', 'approved', 'changes_requested', 'dismissed')),
    created_at   TEXT,
    body         TEXT NOT NULL,
    url          TEXT,
    -- A comment's review, and its thread: GitHub's node id, where it is, and whether it is outdated or resolved.
    review_id    INTEGER,
    thread_id    TEXT,
    path         TEXT,
    line         INTEGER,
    side         TEXT CHECK (side IN ('left', 'right')),
    outdated     INTEGER,
    resolved     INTEGER,
    observed_at  TEXT NOT NULL,
    PRIMARY KEY (pr_url, item, id),
    CHECK ((item = 'comment') = (thread_id IS NOT NULL)),
    CHECK (item = 'review' OR state IS NULL)
);
CREATE INDEX observed_reviews_thread ON observed_reviews(thread_id);

-- A comment a run would have posted, waiting on the operator. `number` is its place in the run's result, 1 to 30, as
-- a review's findings are numbered (DESIGN §21). `basis` is the time a comment on its thread must be newer than to
-- refuse a send as `thread_changed`: the run's start, then the newest comment a refusal showed.
CREATE TABLE drafts (
    id               INTEGER PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES runs(id),
    number           INTEGER NOT NULL CHECK (number BETWEEN 1 AND 30),
    ticket_key       TEXT NOT NULL REFERENCES tickets(key),
    kind             TEXT NOT NULL CHECK (kind IN ('thread', 'pr', 'ticket')),
    -- A thread's or a PR's draft: the unit's repository and its PR; a thread's, the review comment it names.
    repo             TEXT,
    pr_url           TEXT,
    comment_id       INTEGER,
    -- A ticket's draft: the issue it goes to, as the worker named it.
    issue_url        TEXT,
    stance           TEXT CHECK (stance IN ('changed', 'declined', 'answered')),
    -- The thread the reader found the comment on, once a whole read checked the draft.
    thread_id        TEXT,
    status           TEXT NOT NULL CHECK (
        status IN ('unchecked', 'waiting', 'refused', 'superseded', 'dropped', 'sending', 'unconfirmed', 'sent')
    ),
    -- The harness's words for the latest change of status, such as `superseded by run 41's draft 2`.
    why              TEXT,
    basis            TEXT NOT NULL,
    superseded_by    INTEGER REFERENCES drafts(id),
    created_at       TEXT NOT NULL,
    checked_at       TEXT,
    -- A send's claim: when it began, the version it sends, and the pending review the post reported, if any, by its
    -- node id, which a later post deletes it by, and its id, which a later read settles an unconfirmed send by.
    send_started_at    TEXT,
    send_version       INTEGER,
    pending_review     TEXT,
    pending_review_id  INTEGER,
    -- What a sent draft became on GitHub, and through which channel the operator sent it.
    sent_at          TEXT,
    sent_comment_id  INTEGER,
    sent_review_id   INTEGER,
    sent_url         TEXT,
    sent_channel     TEXT,
    UNIQUE (run_id, number),
    CHECK ((kind = 'ticket') = (pr_url IS NULL)),
    CHECK ((kind = 'ticket') = (issue_url IS NOT NULL)),
    CHECK ((kind = 'thread') = (comment_id IS NOT NULL)),
    CHECK ((kind = 'thread') = (stance IS NOT NULL)),
    CHECK ((status = 'sent') = (sent_at IS NOT NULL))
);
CREATE INDEX drafts_pr ON drafts(pr_url, status);
CREATE INDEX drafts_ticket ON drafts(ticket_key, status);

-- Each version of a draft's text: the run's own first, then each of the operator's edits.
CREATE TABLE draft_versions (
    draft_id    INTEGER NOT NULL REFERENCES drafts(id),
    version     INTEGER NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT NOT NULL CHECK (author IN ('worker', 'operator')),
    channel     TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (draft_id, version),
    CHECK ((author = 'worker') = (version = 1))
);

-- The `trust.review_replies` a run of a kind that comments was rendered under, whether its prompt asked for a ticket's
-- draft (only with a tracker source that posts, and never on a private ticket), and the drafts `_run` refused from its
-- result in the harness's words, as a JSON list. A run with no row was rendered before the setting existed.
CREATE TABLE run_replies (
    run_id         INTEGER PRIMARY KEY REFERENCES runs(id),
    mode           TEXT NOT NULL CHECK (mode IN ('approve', 'post')),
    ticket_drafts  INTEGER NOT NULL,
    refused        TEXT NOT NULL DEFAULT '[]'
);
