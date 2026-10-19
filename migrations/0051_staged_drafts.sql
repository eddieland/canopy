-- Drafts staged on GitHub (DESIGN §29): the operator may open a pending review holding a PR's drafts, left for them to
-- finish and submit on GitHub, in place of a send. Such a draft is `staged` until a whole read of its PR finds that
-- review submitted, or gone. Its pending review's ids, and each reply's comment id, are kept as a send's are.
--
-- SQLite cannot change a CHECK in place, so `drafts` is rebuilt with every row and column it had. `draft_versions`
-- references it, so its rows are set aside and put back around the rebuild, which keeps the foreign keys whole.

CREATE TEMP TABLE drafts_0051 AS SELECT * FROM drafts;
CREATE TEMP TABLE draft_versions_0051 AS SELECT * FROM draft_versions;
DELETE FROM draft_versions;
DROP TABLE drafts;

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
        status IN (
            'unchecked', 'waiting', 'refused', 'superseded', 'dropped', 'sending', 'unconfirmed', 'staged', 'sent'
        )
    ),
    -- The harness's words for the latest change of status, such as `superseded by run 41's draft 2`.
    why              TEXT,
    basis            TEXT NOT NULL,
    superseded_by    INTEGER REFERENCES drafts(id),
    created_at       TEXT NOT NULL,
    checked_at       TEXT,
    -- A send's claim: when it began, the version it sends, and the pending review the post reported, if any, by its
    -- node id, which a later post deletes it by, and its id, which a later read settles an unconfirmed send by. A
    -- staged draft keeps its pending review's ids until a read settles it.
    send_started_at    TEXT,
    send_version       INTEGER,
    pending_review     TEXT,
    pending_review_id  INTEGER,
    -- What a sent draft became on GitHub, and through which channel the operator sent it. A staged reply's comment id
    -- is known from the start, so the loop knows it as the operator's whenever they submit it.
    sent_at          TEXT,
    sent_comment_id  INTEGER,
    sent_review_id   INTEGER,
    sent_url         TEXT,
    sent_channel     TEXT,
    -- The reaction a send added on GitHub, and when (0048).
    reacted          TEXT CHECK (reacted IN ('+1', '-1', 'laugh', 'confused', 'heart', 'hooray', 'rocket', 'eyes')),
    reacted_at       TEXT,
    UNIQUE (run_id, number),
    CHECK ((kind = 'ticket') = (pr_url IS NULL)),
    CHECK ((kind = 'ticket') = (issue_url IS NOT NULL)),
    CHECK ((kind = 'thread') = (comment_id IS NOT NULL)),
    CHECK ((kind = 'thread') = (stance IS NOT NULL)),
    CHECK ((status = 'sent') = (sent_at IS NOT NULL)),
    CHECK (status != 'staged' OR (kind != 'ticket' AND pending_review_id IS NOT NULL))
);

INSERT INTO drafts (
    id, run_id, number, ticket_key, kind, repo, pr_url, comment_id, issue_url, stance, thread_id, status, why, basis,
    superseded_by, created_at, checked_at, send_started_at, send_version, pending_review, pending_review_id, sent_at,
    sent_comment_id, sent_review_id, sent_url, sent_channel, reacted, reacted_at
)
SELECT
    id, run_id, number, ticket_key, kind, repo, pr_url, comment_id, issue_url, stance, thread_id, status, why, basis,
    superseded_by, created_at, checked_at, send_started_at, send_version, pending_review, pending_review_id, sent_at,
    sent_comment_id, sent_review_id, sent_url, sent_channel, reacted, reacted_at
FROM temp.drafts_0051;
INSERT INTO draft_versions (draft_id, version, body, author, channel, created_at, reaction)
SELECT draft_id, version, body, author, channel, created_at, reaction FROM temp.draft_versions_0051;
DROP TABLE temp.drafts_0051;
DROP TABLE temp.draft_versions_0051;

CREATE INDEX drafts_pr ON drafts(pr_url, status);
CREATE INDEX drafts_ticket ON drafts(ticket_key, status);
