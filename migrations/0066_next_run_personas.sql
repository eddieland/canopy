-- The persona the operator chose for the next run alone of one of a ticket's agents (DESIGN §31), in place of the
-- ticket's override and `[personas]`: one row a ticket and agent. Set only by the operator, with
-- `canopy persona KEY NAME --next`, `canopy start KEY --persona`, or `canopy plan KEY --persona`, and never by an
-- agent. The dispatch that records the agent's next run for the ticket deletes it in the same transaction, so it
-- reaches that run alone; the run records the persona it ran in. A ticket canopy has not seen may have one.
CREATE TABLE next_run_personas (
    ticket_key  TEXT NOT NULL,
    agent       TEXT NOT NULL CHECK (agent IN ('worker', 'planner')),
    persona     TEXT NOT NULL,
    channel     TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    set_at      TEXT NOT NULL,
    PRIMARY KEY (ticket_key, agent)
);
