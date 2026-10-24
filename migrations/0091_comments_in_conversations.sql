-- Comments reach the conversation in code (DESIGN §35, ROADMAP M37): the overseer's mirror is retired, and each comment
-- the tracker source observes is recorded in its ticket's conversation when first observed, with the observation's
-- text, author, time, and source. Each comment observed before this migration that the overseer had not mirrored is
-- recorded now, oldest first, at the time it was observed. One it mirrored keeps the message it was mirrored as, found
-- by its comment id as `messages_comment` keys it. `tickets.last_mirrored_id`, the mirror's cursor, stays unread.
INSERT INTO messages (
    subject_kind, subject_id, at, source, kind, channel, body, comment_id, author, commented_at, truncated
)
SELECT 'ticket', o.ticket, o.observed_at, o.source, 'comment', 'tracker', o.body, o.id, o.author, o.commented_at,
    o.truncated
FROM observed_comments o
WHERE NOT EXISTS (
    SELECT 1 FROM messages m WHERE m.subject_kind = 'ticket' AND m.subject_id = o.ticket AND m.comment_id = o.id
)
ORDER BY o.commented_at, o.ticket, o.id;
