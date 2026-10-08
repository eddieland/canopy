-- Tracker comments in the journal (DESIGN §22, M19): the overseer mirrors each ticket's comments into `messages` with
-- `canopy mirror`, so the journal holds every ticket's conversation, public or private. A mirrored comment authorizes
-- nothing.

-- A mirrored comment's tracker id, its author's account id, and when the tracker says it was written. NULL for every
-- other message.
ALTER TABLE messages ADD COLUMN comment_id TEXT;
ALTER TABLE messages ADD COLUMN author TEXT;
ALTER TABLE messages ADD COLUMN commented_at TEXT;
-- Whether the body was cut to its bound (2000 characters for a mirrored comment).
ALTER TABLE messages ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0;
-- A comment is mirrored once per subject, however often the overseer records it.
CREATE UNIQUE INDEX messages_comment ON messages(subject_kind, subject_id, comment_id) WHERE comment_id IS NOT NULL;

-- A ticket's mirror cursor: the newest tracker comment mirrored. Its own, apart from the comment cursor the phases use,
-- and empty to start, so a ticket's first mirror covers its whole comment history.
ALTER TABLE tickets ADD COLUMN last_mirrored_id TEXT;
