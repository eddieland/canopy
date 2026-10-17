-- Memory by scope and status (DESIGN §28): the proposals waiting, the lessons in force, and the tickets with notes in
-- force, which every tick and the memory page read, found without a scan of every row retention keeps.
CREATE INDEX memories_scope ON memories(scope, status, ticket_key);
