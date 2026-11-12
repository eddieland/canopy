-- Each agent run's session, by index (DESIGN §13): whether one of the runtime's sessions is canopy's is asked of each
-- run table by the session's id, for the sessions a window or a list holds alone, so reading what the sessions outside
-- canopy cost, or listing them, never reads every run the journal has recorded.
CREATE INDEX ticks_session ON ticks(session_id) WHERE session_id IS NOT NULL;

CREATE INDEX runs_session ON runs(session_id) WHERE session_id IS NOT NULL;

CREATE INDEX chore_runs_session ON chore_runs(session_id) WHERE session_id IS NOT NULL;

CREATE INDEX review_runs_session ON review_runs(session_id) WHERE session_id IS NOT NULL;

CREATE INDEX task_runs_session ON task_runs(session_id) WHERE session_id IS NOT NULL;

CREATE INDEX epic_runs_session ON epic_runs(session_id) WHERE session_id IS NOT NULL;
