-- `canopy memory search` (DESIGN §28, ROADMAP M50 stage 3): a full-text index over each memory's key and body,
-- ranked with bm25(). It holds no text of its own: `memories` is its content, and these triggers keep the index in
-- step with every insert, update, and delete there, so a forgotten or purged body leaves the index with the row.
-- Needs SQLite built with FTS5, which `make install-check` checks.

CREATE VIRTUAL TABLE memories_fts USING fts5(
    key, body, content = 'memories', content_rowid = 'id', tokenize = 'porter unicode61'
);

CREATE TRIGGER memories_fts_insert AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (rowid, key, body) VALUES (new.id, new.key, new.body);
END;

CREATE TRIGGER memories_fts_delete AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, key, body) VALUES ('delete', old.id, old.key, old.body);
END;

CREATE TRIGGER memories_fts_update AFTER UPDATE OF key, body ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, key, body) VALUES ('delete', old.id, old.key, old.body);
    INSERT INTO memories_fts (rowid, key, body) VALUES (new.id, new.key, new.body);
END;

-- What the journal already holds.
INSERT INTO memories_fts (memories_fts) VALUES ('rebuild');
