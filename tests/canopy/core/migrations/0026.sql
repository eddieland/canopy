-- sha256 of 0026_unasked_items.sql: 3c88127c86ca87868d077d3566ed5eff0fb6e2e2a900b63c26b9c527a26d46ab

-- Rebuilds `checklist_answers` and creates no table; an item no push asked shows the new answer is taken.
INSERT INTO checklist_answers (run_id, repo, item, answer)
VALUES ((SELECT min(id) FROM runs), 'repo', 'narrow-except', 'unasked');
