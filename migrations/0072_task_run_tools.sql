-- A task's runs (DESIGN §36) have their tool calls rolled up as every other agent run's are (DESIGN §13). SQLite
-- cannot change a CHECK in place, so `run_tools` is rebuilt with every row it had, its `run_table` naming `task_runs`
-- too; nothing references it.
CREATE TABLE run_tools_0072 (
    run_table     TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs')),
    run_id        INTEGER NOT NULL,
    tool          TEXT NOT NULL,
    calls         INTEGER NOT NULL,
    errors        INTEGER NOT NULL,
    result_chars  INTEGER NOT NULL,
    PRIMARY KEY (run_table, run_id, tool)
) WITHOUT ROWID;
INSERT INTO run_tools_0072 (run_table, run_id, tool, calls, errors, result_chars)
    SELECT run_table, run_id, tool, calls, errors, result_chars FROM run_tools;
DROP TABLE run_tools;
ALTER TABLE run_tools_0072 RENAME TO run_tools;
