-- What a running run did last (DESIGN §8): its worker's latest tool call, as `_run` reads it from the worker's events
-- while it runs, so a page shows more than `running` until the run ends. `activity_tool` is the tool's name,
-- `activity` what the call did on one line (a shell call's command, else the runtime's title), and `activity_at` when
-- `_run` read it. NULL until the worker's first tool call, and for a template that prints no events. Left as it was
-- when the run ends: its result says what it did then.

ALTER TABLE runs ADD COLUMN activity_tool TEXT;
ALTER TABLE runs ADD COLUMN activity TEXT;
ALTER TABLE runs ADD COLUMN activity_at TEXT;
