-- Units and joint runs (DESIGN §18, ROADMAP M7). A ticket's work is divided into units, one per repository it changes,
-- each with its own branch, PR, phase, and review and ci cursors; the comment cursor and the ticket's own phase stay on
-- `tickets`. A run may lease a slot in several repositories, one `run_slots` row each.
--
-- `repo` is NULL in both tables only on rows carried over from runs made before workspaces (migration 0004): those were
-- in a workspace of one, whose only repository they are. canopy renames a workspace of one's unit to the repository's
-- current name the next time it writes it.

CREATE TABLE ticket_units (
    ticket_key      TEXT NOT NULL REFERENCES tickets(key),
    repo            TEXT,
    branch          TEXT,
    pr_url          TEXT,
    phase           TEXT,
    last_review_id  TEXT,
    last_ci_run_id  TEXT,
    UNIQUE (ticket_key, repo)
);

CREATE TABLE run_slots (
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    repo          TEXT,
    slot_path     TEXT NOT NULL,
    lease_id      TEXT NOT NULL,
    lease_holder  TEXT NOT NULL,
    base_branch   TEXT,
    UNIQUE (run_id, repo)
);
CREATE INDEX run_slots_lease ON run_slots(lease_id);

-- Every run so far held one slot, in the repository `runs.repo` names.
INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch)
    SELECT id, repo, slot_path, lease_id, lease_holder, base_branch FROM runs;

-- Every ticket so far had at most one unit: the repository of its latest run. A phase about its PR, `pushed_no_pr`
-- to `merged` in the overseer's phase table, is the unit's now, and moves to it.
CREATE TEMP TABLE pr_phases (phase TEXT PRIMARY KEY);
INSERT INTO pr_phases VALUES
    ('pushed_no_pr'), ('ci_running'), ('ci_red'), ('changes_requested'), ('green_unreviewed'), ('approved'), ('merged');

INSERT INTO ticket_units (ticket_key, repo, branch, pr_url, phase, last_review_id, last_ci_run_id)
    SELECT t.key,
           (SELECT r.repo FROM runs r WHERE r.ticket_key = t.key ORDER BY r.id DESC LIMIT 1),
           t.branch, t.pr_url, (SELECT p.phase FROM pr_phases p WHERE p.phase = t.phase),
           t.last_review_id, t.last_ci_run_id
    FROM tickets t
    WHERE t.branch IS NOT NULL OR t.pr_url IS NOT NULL OR t.last_review_id IS NOT NULL OR t.last_ci_run_id IS NOT NULL
       OR t.phase IN (SELECT phase FROM pr_phases);

UPDATE tickets SET phase = NULL WHERE phase IN (SELECT phase FROM pr_phases);
DROP TABLE pr_phases;

ALTER TABLE runs DROP COLUMN slot_path;
ALTER TABLE runs DROP COLUMN lease_id;
ALTER TABLE runs DROP COLUMN lease_holder;
ALTER TABLE runs DROP COLUMN base_branch;
ALTER TABLE runs DROP COLUMN repo;

-- `tickets.branch` stays: the ticket's branch name, fixed by its first implement and the same in every unit.
ALTER TABLE tickets DROP COLUMN pr_url;
ALTER TABLE tickets DROP COLUMN last_review_id;
ALTER TABLE tickets DROP COLUMN last_ci_run_id;
