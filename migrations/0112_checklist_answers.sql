-- What a worker run reminded of its repositories' checklists answered of each item (DESIGN §42): `pass`, `fixed`,
-- `held` with its reason, or `n/a`, in its own words, and `unanswered` for an item its result answered nothing of that
-- canopy could record. A row for each item of each list the run was given, so canopy counts per repository and item
-- how often it was reminded and what came of it. `item` is the list's id for it, as the run's list named it then.
CREATE TABLE checklist_answers (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    repo    TEXT NOT NULL,
    item    TEXT NOT NULL,
    answer  TEXT NOT NULL CHECK (answer IN ('pass', 'fixed', 'held', 'n/a', 'unanswered')),
    reason  TEXT,
    CHECK (answer != 'held' OR reason IS NOT NULL),
    PRIMARY KEY (run_id, repo, item)
);
