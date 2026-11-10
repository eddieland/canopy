-- A proposal made again (DESIGN §28): a run that proposes under a pending proposal's key and repository, or in its
-- words, seconds it rather than writing a row of its own. A row per ticket whose runs seconded the proposal, naming the
-- first such run, so one ticket's runs count once; the ticket that made the proposal never seconds it. Kept once the
-- proposal is promoted, rejected, or lapses.
CREATE TABLE proposal_seconds (
    memory_id   INTEGER NOT NULL REFERENCES memories(id),
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    PRIMARY KEY (memory_id, ticket_key)
);
