-- The web UI's write requests (TRUST_MODEL T8, DESIGN §22): each request of a method but GET and HEAD that the server
-- let through, a sign-in or a write whose session, token, and Origin it accepted, however the verb then answered it,
-- so the operator can see what a holder of the listener secret did. `path` is the request's own, without its query, at
-- most 512 characters; `code` the HTTP status it was answered with; `client` the peer's address; `session` a
-- fingerprint of the session, NULL on the mock server, which signs nobody in. Never the request's body, headers,
-- query, cookie, or token. Written only by the server once it has answered, so `id` order may differ from `at` order;
-- rows are never deleted.
CREATE TABLE web_writes (
    id       INTEGER PRIMARY KEY,
    at       TEXT NOT NULL,
    method   TEXT NOT NULL,
    path     TEXT NOT NULL,
    code     INTEGER NOT NULL,
    client   TEXT,
    session  TEXT
);
