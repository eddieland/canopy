-- Cursors become journal numbers (DESIGN §35, ROADMAP M37). Each comment, review, review comment, and completed check
-- run takes the next number when a source first observes it, and keeps it across later reads of its subject, which
-- replace the observation's row but not its number; a canopy review run takes one when it ends. "Newer than a cursor"
-- then means first observed after it, one order for every kind, so the `review` cursor needs no time form.

-- Each item ever numbered, by what it is, its subject (a ticket's key for a comment, a PR's URL for the rest), and the
-- source's id for it (canopy's own for a review run). AUTOINCREMENT keeps numbers rising, so none is ever given twice.
CREATE TABLE item_numbers (
    number       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL CHECK (kind IN ('comment', 'review', 'review_comment', 'check_run', 'review_run')),
    subject      TEXT NOT NULL,
    id           TEXT NOT NULL,
    numbered_at  TEXT NOT NULL,
    UNIQUE (subject, kind, id)
);

-- What the journal holds now is numbered in the order each cursor read it, subject by subject, so each converted cursor
-- passes what it passed before: a ticket's comments by their time and id, a PR's review items and ended review runs by
-- their time to the second (one with no time first, as no time cursor found it newer), and its check runs by run id.
INSERT INTO item_numbers (kind, subject, id, numbered_at)
SELECT 'comment', ticket, id, observed_at FROM observed_comments ORDER BY ticket, commented_at, id;

INSERT INTO item_numbers (kind, subject, id, numbered_at)
SELECT kind, subject, id, numbered_at FROM (
    SELECT CASE item WHEN 'review' THEN 'review' ELSE 'review_comment' END AS kind, pr_url AS subject,
        CAST(id AS TEXT) AS id, observed_at AS numbered_at, substr(created_at, 1, 19) AS at, 0 AS run
    FROM observed_reviews
    UNION ALL
    SELECT 'review_run', pr_url, CAST(id AS TEXT), ended_at, substr(ended_at, 1, 19), 1
    FROM review_runs WHERE ended_at IS NOT NULL
)
ORDER BY subject, at, run, kind, CAST(id AS INTEGER);

INSERT INTO item_numbers (kind, subject, id, numbered_at)
SELECT 'check_run', pr_url, CAST(run_id AS TEXT), min(observed_at) FROM (
    SELECT pr_url, run_id, observed_at FROM observed_check_runs
    UNION ALL
    SELECT pr_url, run_id, observed_at FROM observed_checks
    WHERE status = 'completed' AND run_id IS NOT NULL AND conclusion IS NOT NULL
)
GROUP BY pr_url, run_id
ORDER BY pr_url, run_id;

-- Each observation carries its item's number; NULL for a check with no completed run, and a review run not ended.
ALTER TABLE observed_comments ADD COLUMN number INTEGER;
ALTER TABLE observed_reviews ADD COLUMN number INTEGER;
ALTER TABLE observed_checks ADD COLUMN number INTEGER;
ALTER TABLE observed_check_runs ADD COLUMN number INTEGER;
ALTER TABLE review_runs ADD COLUMN number INTEGER;

UPDATE observed_comments SET number = (
    SELECT n.number FROM item_numbers n
    WHERE n.subject = observed_comments.ticket AND n.kind = 'comment' AND n.id = observed_comments.id
);
UPDATE observed_reviews SET number = (
    SELECT n.number FROM item_numbers n
    WHERE n.subject = observed_reviews.pr_url AND n.id = CAST(observed_reviews.id AS TEXT)
        AND n.kind = CASE observed_reviews.item WHEN 'review' THEN 'review' ELSE 'review_comment' END
);
UPDATE observed_checks SET number = (
    SELECT n.number FROM item_numbers n
    WHERE n.subject = observed_checks.pr_url AND n.kind = 'check_run' AND n.id = CAST(observed_checks.run_id AS TEXT)
)
WHERE status = 'completed' AND run_id IS NOT NULL AND conclusion IS NOT NULL;
UPDATE observed_check_runs SET number = (
    SELECT n.number FROM item_numbers n
    WHERE n.subject = observed_check_runs.pr_url AND n.kind = 'check_run'
        AND n.id = CAST(observed_check_runs.run_id AS TEXT)
);
UPDATE review_runs SET number = (
    SELECT n.number FROM item_numbers n
    WHERE n.subject = review_runs.pr_url AND n.kind = 'review_run' AND n.id = CAST(review_runs.id AS TEXT)
)
WHERE ended_at IS NOT NULL;

-- The cursors, as journal numbers. The old columns stay, since no migration drops a column: `last_review_id` and
-- `last_ci_run_id` unread, and `last_comment_id` the comment cursor of a ticket no tracker source observes, which has
-- no numbers to name (DESIGN §35, Open).
ALTER TABLE tickets ADD COLUMN comment_cursor INTEGER;
ALTER TABLE ticket_units ADD COLUMN review_cursor INTEGER;
ALTER TABLE ticket_units ADD COLUMN ci_cursor INTEGER;

-- A comment cursor becomes the number of the comment it names. One naming none observed, by a number, passed the
-- comments before the first whose id is a larger number; one that is not a number passed none. A ticket with no
-- comment observed keeps only its tracker id: no source may observe its tickets.
UPDATE tickets SET comment_cursor = coalesce(
    (
        SELECT o.number FROM observed_comments o
        WHERE o.ticket = tickets.key AND o.id = tickets.last_comment_id
    ),
    CASE WHEN tickets.last_comment_id NOT GLOB '*[^0-9]*' THEN (
        SELECT max(o.number) FROM observed_comments o
        WHERE o.ticket = tickets.key AND o.number < coalesce(
            (
                SELECT min(f.number) FROM observed_comments f
                WHERE f.ticket = tickets.key AND f.id NOT GLOB '*[^0-9]*' AND f.id != ''
                    AND CAST(f.id AS INTEGER) > CAST(tickets.last_comment_id AS INTEGER)
            ),
            9223372036854775807
        )
    ) END
)
WHERE last_comment_id IS NOT NULL AND last_comment_id != ''
    AND EXISTS (SELECT 1 FROM observed_comments o WHERE o.ticket = tickets.key);

-- A `ci` cursor, a check run's id, becomes the number of the newest run of its unit's PR at or behind it: the run it
-- names, where it is observed. A `review` cursor, a time, becomes the number of the newest review item or ended review
-- run of the PR at or before it, to the second. A cursor that passed nothing observed becomes 0, which still passes a
-- commit status, as a set `ci` cursor did; one in no form these read was empty to its readers, and stays so.
UPDATE ticket_units SET ci_cursor = coalesce(
    (
        SELECT max(n.number) FROM item_numbers n
        WHERE n.subject = ticket_units.pr_url AND n.kind = 'check_run'
            AND CAST(n.id AS INTEGER) <= CAST(ticket_units.last_ci_run_id AS INTEGER)
    ),
    0
)
WHERE pr_url IS NOT NULL AND last_ci_run_id != '' AND last_ci_run_id NOT GLOB '*[^0-9]*';

UPDATE ticket_units SET review_cursor = max(
    coalesce(
        (
            SELECT max(r.number) FROM observed_reviews r
            WHERE r.pr_url = ticket_units.pr_url
                AND (r.created_at IS NULL OR substr(r.created_at, 1, 19) <= substr(ticket_units.last_review_id, 1, 19))
        ),
        0
    ),
    coalesce(
        (
            SELECT max(v.number) FROM review_runs v
            WHERE v.pr_url = ticket_units.pr_url AND v.ended_at IS NOT NULL
                AND substr(v.ended_at, 1, 19) <= substr(ticket_units.last_review_id, 1, 19)
        ),
        0
    )
)
WHERE pr_url IS NOT NULL
    AND last_review_id GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*';
