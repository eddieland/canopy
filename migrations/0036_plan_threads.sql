-- The operator's comments on a ticket's plan (DESIGN §25, Commenting on a plan): each a thread on a passage, with its
-- replies, open until the operator resolves it. A thread belongs to the ticket, not to one plan, so it carries from
-- plan to plan, anchored again on each by its passage's words: `quote`, and up to 32 characters either side, whitespace
-- collapsed. Never by a position. Written only by the web channel, behind its token (TRUST_MODEL T8). A comment is the
-- operator's words and the passage it quotes; the plan's text stays in its file.

CREATE TABLE plan_threads (
    id           INTEGER PRIMARY KEY,
    ticket_key   TEXT NOT NULL REFERENCES tickets(key),
    quote        TEXT NOT NULL,
    prefix       TEXT NOT NULL,
    suffix       TEXT NOT NULL,
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    resolved_at  TEXT
);
CREATE INDEX plan_threads_ticket ON plan_threads(ticket_key, id);

CREATE TABLE plan_replies (
    id          INTEGER PRIMARY KEY,
    thread_id   INTEGER NOT NULL REFERENCES plan_threads(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX plan_replies_thread ON plan_replies(thread_id, id);
