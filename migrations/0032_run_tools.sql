-- What each agent run's tool calls put into its context (DESIGN §13): one row per run and tool, rolled up from the
-- run's `tool_use` events when it reports what it cost. `run_table` and `run_id` name the run: a tick's overseer, a
-- worker or split run, a chore run, or a review run. `tool` is the tool's name as the runtime gives it, an MCP server's
-- prefixed with the server's; `calls` how many of its calls ended, `errors` how many of those ended in an error, and
-- `result_chars` the characters of what they returned, output or error, which each later model call reads again. No
-- row for a run whose template prints no events, nor for any run from before this migration. Without a rowid, since
-- every read is by its key, which would otherwise be stored again in an index of its own.

CREATE TABLE run_tools (
    run_table     TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id        INTEGER NOT NULL,
    tool          TEXT NOT NULL,
    calls         INTEGER NOT NULL,
    errors        INTEGER NOT NULL,
    result_chars  INTEGER NOT NULL,
    PRIMARY KEY (run_table, run_id, tool)
) WITHOUT ROWID;
