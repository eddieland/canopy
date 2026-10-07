-- Split tickets (DESIGN §18, ROADMAP M8). A split run creates one child ticket per repository in the tracker; `_run`
-- records each child it reported, after validating the result, with the repository it covers. A child is dispatched only
-- in that repository. The child is an ordinary ticket of the tracker's and may never appear in `tickets`, so it has no
-- foreign key; the parent does, since its dispatch recorded it.
CREATE TABLE split_children (
    child_key   TEXT PRIMARY KEY,
    parent_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT NOT NULL,
    run_id      INTEGER NOT NULL REFERENCES runs(id)
);
CREATE INDEX split_children_parent ON split_children(parent_key);
