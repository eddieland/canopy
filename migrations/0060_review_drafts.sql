-- A review's draft (DESIGN §34, ROADMAP M43): a `done` review of a PR the loop does not own, as the comment review the
-- operator may publish on it in their own name. One draft a review run, made as the review ends `done`; a review that
-- names a ticket, or of a PR a ticket's unit holds, has none. Its versions are each exactly what would post. A draft
-- publishes, or stages, one version at most once: `publishing` while a post holds it, `unconfirmed` when the post
-- ended without saying whether it submitted, `staged` while a pending review holding it waits on the operator on
-- GitHub, and `published` once a review holding it is submitted. A whole read of the PR settles the two between.
CREATE TABLE review_drafts (
    id                   INTEGER PRIMARY KEY,
    review_run_id        INTEGER NOT NULL UNIQUE REFERENCES review_runs(id),
    pr_url               TEXT NOT NULL,
    -- The commit the review read, which the review is posted on.
    sha                  TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (
        status IN ('waiting', 'publishing', 'unconfirmed', 'staged', 'published')
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
    CHECK (status = 'waiting' OR publish_version IS NOT NULL),
    CHECK (status != 'staged' OR pending_review_id IS NOT NULL)
);
CREATE INDEX review_drafts_pr ON review_drafts(pr_url, status);

-- A version of a review's draft: the review's body, and its comments as a JSON list of {"path", "line", "text"} on
-- lines of the diff the review kept, a comment made from a finding naming it as "finding". The reviewer's is the first;
-- each of the operator's edits, drops, additions, and dismissals is a new one, `change` saying which in the harness's
-- words. `refused` is a JSON list of what canopy left out as it made the version, and why, in the harness's words.
CREATE TABLE review_draft_versions (
    draft_id    INTEGER NOT NULL REFERENCES review_drafts(id),
    version     INTEGER NOT NULL CHECK (version > 0),
    body        TEXT NOT NULL,
    comments    TEXT NOT NULL,
    author      TEXT NOT NULL CHECK (author IN ('reviewer', 'reviser', 'operator')),
    channel     TEXT CHECK (channel IN ('cli', 'web')),
    change      TEXT NOT NULL,
    refused     TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (draft_id, version),
    CHECK ((author = 'operator') = (channel IS NOT NULL))
);
