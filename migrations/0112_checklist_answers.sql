-- What a worker run answered of each item of its repositories' checklists (DESIGN §42): `pass`, `fixed`, `held` with
-- its reason, or `n/a`, the worker's word, untrusted; and `unanswered`, the harness's, for an item the run was given
-- and its result said nothing of. A row for every item of every list the run was given, and none for one it was not:
-- an answer to an item or a repository the run's lists do not hold is dropped. Counted per repository and item, so an
-- item earns its place or is dropped.
CREATE TABLE checklist_answers (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    repo    TEXT NOT NULL,
    item    TEXT NOT NULL,
    answer  TEXT NOT NULL CHECK (answer IN ('pass', 'fixed', 'held', 'n/a', 'unanswered')),
    reason  TEXT,
    CHECK ((answer = 'held') = (reason IS NOT NULL)),
    PRIMARY KEY (run_id, repo, item)
);
