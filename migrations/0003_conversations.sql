-- Conversations (DESIGN §22): every ticket's messages, and the operator's start records for private tickets. Both are
-- keyed by subject, its kind and id, so a new kind of subject (a PR with M14) adds no table (D075).

-- One row per message. AUTOINCREMENT, so an id is never reused and a message cursor never passes a later message.
CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_kind  TEXT NOT NULL,                  -- ticket
    subject_id    TEXT NOT NULL,                  -- the ticket key
    at            TEXT NOT NULL,                  -- when canopy recorded it
    source        TEXT NOT NULL,                  -- worker | operator | tracker (M19)
    kind          TEXT NOT NULL,                  -- report | question (a worker's) | reply (the operator's)
    channel       TEXT NOT NULL,                  -- run | cli | web | slack | tracker
    run_id        INTEGER REFERENCES runs(id),    -- a worker's message: the run that reported it
    body          TEXT NOT NULL,                  -- bounded by its source: 2000 for a worker's, 4000 for the operator's
    answers       INTEGER REFERENCES messages(id),-- the message a reply answers, when the channel knows it
    submission    TEXT,                           -- an operator message's submission id: a retry records nothing new
    UNIQUE (subject_kind, subject_id, submission)
);
CREATE INDEX messages_subject ON messages(subject_kind, subject_id, id);

-- The operator's start record for a subject worked privately. It is the authorization: only the operator's commands
-- write it. `stop` marks it stopped and never deletes it, so a stopped ticket stays private.
CREATE TABLE starts (
    subject_kind  TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    status        TEXT NOT NULL,                  -- started | stopped
    started_at    TEXT NOT NULL,
    stopped_at    TEXT,
    channel       TEXT NOT NULL,                  -- the channel of the latest start or stop
    PRIMARY KEY (subject_kind, subject_id)
);

-- A private ticket's message cursor: the newest journal message the loop has handled. Its own, apart from the comment
-- cursor, which stays the tracker's.
ALTER TABLE tickets ADD COLUMN last_message_id INTEGER;

-- Whether a run worked a private ticket: its prompt and agent definition were the private ones (DESIGN §22).
ALTER TABLE runs ADD COLUMN private INTEGER NOT NULL DEFAULT 0;

-- Every run that ended before this migration gets the messages `_run` records now: a report, and for a `blocked` run
-- its question, so tickets worked before M18 have a conversation too. In the order the runs ended.
-- An invalid result_json reads as none: the JSON functions return NULL for NULL, where they would fail on bad JSON.
WITH ended AS (
    SELECT id, ticket_key, ended_at, status, CASE WHEN json_valid(result_json) THEN result_json END AS result
    FROM runs WHERE status != 'running' AND ended_at IS NOT NULL
)
INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, run_id, body)
SELECT 'ticket', ticket_key, at, 'worker', kind, 'run', id, body FROM (
    SELECT
        e.id, e.ticket_key, e.ended_at AS at, 0 AS seq, 'report' AS kind,
        coalesce(
            nullif(trim(json_extract(e.result, '$.summary')), ''),
            nullif(trim(json_extract(e.result, '$.harness')), ''),
            'ended ' || e.status
        ) || coalesce(
            char(10) || CASE WHEN json_type(e.result, '$.prs') = 'object' THEN (
                SELECT group_concat(p.value, char(10)) FROM json_each(e.result, '$.prs') AS p
                WHERE p.type = 'text' AND p.value != ''
            ) END,
            ''
        ) AS body
    FROM ended AS e
    UNION ALL
    SELECT e.id, e.ticket_key, e.ended_at, 1, 'question', trim(json_extract(e.result, '$.question'))
    FROM ended AS e
    WHERE e.status = 'blocked' AND json_type(e.result, '$.question') = 'text'
        AND trim(json_extract(e.result, '$.question')) != ''
)
ORDER BY at, id, seq;
