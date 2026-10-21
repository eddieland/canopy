-- The operator's choices for one of a ticket's agents, each in force until cleared (DESIGN §31): one row a ticket,
-- agent, and kind of choice. `persona` names the persona the agent's runs for the ticket write in, in place of its
-- default in `[personas]`; `model` is reserved for the model the operator chooses per ticket (DESIGN §13, ROADMAP
-- M58), which nothing sets yet. Set only by the operator, from `canopy persona` or the ticket's page, and never by an
-- agent. A ticket canopy has not seen may have one, so the key references no table; `canopy forget` keeps it. A clear
-- deletes the row.
CREATE TABLE ticket_overrides (
    ticket_key  TEXT NOT NULL,
    agent       TEXT NOT NULL CHECK (agent IN ('worker', 'planner', 'reviewer')),
    kind        TEXT NOT NULL CHECK (kind IN ('persona', 'model')),
    -- What the operator chose: a persona's name, or a `provider/model` id.
    value       TEXT NOT NULL,
    channel     TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    set_at      TEXT NOT NULL,
    PRIMARY KEY (ticket_key, agent, kind)
);
