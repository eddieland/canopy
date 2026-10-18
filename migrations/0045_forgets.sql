-- Each time the operator forgot a ticket's work (DESIGN §22): when, how, the newest run and message then, and the
-- branch and PRs it dropped, which canopy never closes or deletes. The ticket's `forgotten_*` columns stay its latest
-- forget, the boundary every read of the loop's view uses; this is the history behind it, never edited.
CREATE TABLE forgets (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    at          TEXT NOT NULL,
    -- NULL, with `prs`, for a forget made before forgets were recorded: its channel and what it dropped are unknown.
    channel     TEXT CHECK (channel IN ('cli', 'web')),
    run_id      INTEGER REFERENCES runs(id),
    message_id  INTEGER REFERENCES messages(id),
    branch      TEXT,
    -- A JSON array of the URLs of the PRs its units had.
    prs         TEXT,
    CHECK ((channel IS NULL) = (prs IS NULL))
);
CREATE INDEX forgets_ticket ON forgets(ticket_key, id);

-- The latest forget of each ticket forgotten before, the one its columns remember.
INSERT INTO forgets (ticket_key, at, run_id, message_id)
SELECT key, forgotten_at, forgotten_run_id, forgotten_message_id FROM tickets WHERE forgotten_at IS NOT NULL;
