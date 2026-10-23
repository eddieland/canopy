-- A review's draft the operator discarded (DESIGN §34): seen, and not to be posted. A discarded draft takes no edit,
-- note, or publish, and answers its PR's `review_waiting` item as a published one does. `why` names the channel.
--
-- SQLite cannot change a CHECK in place, so `review_drafts` is rebuilt with every row and column it had. Four tables
-- reference it, `review_runs` among them, whose rows cannot be set aside, so the foreign keys are checked at commit,
-- once every row is back under its old id.

PRAGMA defer_foreign_keys = ON;

CREATE TEMP TABLE review_drafts_0080 AS SELECT * FROM review_drafts;
DROP TABLE review_drafts;

CREATE TABLE review_drafts (
    id                   INTEGER PRIMARY KEY,
    review_run_id        INTEGER NOT NULL UNIQUE REFERENCES review_runs(id),
    pr_url               TEXT NOT NULL,
    -- The commit the review read, which the review is posted on.
    sha                  TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (
        status IN ('waiting', 'publishing', 'unconfirmed', 'staged', 'published', 'discarded')
    ),
    -- The harness's words for the latest change of status, such as a post GitHub refused.
    why                  TEXT,
    created_at           TEXT NOT NULL,
    -- A publish's claim: the version it posts, when it began, and through which channel.
    publish_version      INTEGER,
    publish_started_at   TEXT,
    publish_channel      TEXT CHECK (publish_channel IN ('cli', 'web')),
    -- The pending review a post reported, by its node id, which a later post deletes it by, and its id, which a read
    -- settles an unconfirmed or staged draft by.
    pending_review       TEXT,
    pending_review_id    INTEGER,
    -- What the published review became on GitHub: its id and URL, and each comment's, as a JSON list in the version's
    -- order of {"id", "url"}.
    published_at         TEXT,
    published_review_id  INTEGER,
    published_url        TEXT,
    published_comments   TEXT,
    CHECK ((status = 'published') = (published_at IS NOT NULL)),
    CHECK (status IN ('waiting', 'discarded') OR publish_version IS NOT NULL),
    CHECK (status != 'staged' OR pending_review_id IS NOT NULL)
);

INSERT INTO review_drafts (
    id, review_run_id, pr_url, sha, status, why, created_at, publish_version, publish_started_at, publish_channel,
    pending_review, pending_review_id, published_at, published_review_id, published_url, published_comments
)
SELECT
    id, review_run_id, pr_url, sha, status, why, created_at, publish_version, publish_started_at, publish_channel,
    pending_review, pending_review_id, published_at, published_review_id, published_url, published_comments
FROM temp.review_drafts_0080;
DROP TABLE temp.review_drafts_0080;

CREATE INDEX review_drafts_pr ON review_drafts(pr_url, status);
