-- A running tick's overseer's latest tool call, as `runs` keeps its worker's (0028, DESIGN §8): the tool's name, what
-- the call did on one line (a shell call's command, else the runtime's title), and when canopy read it from the events
-- the overseer printed. Shown to the operator while the tick runs. NULL before the overseer's first tool call, for a
-- template that prints no events, and on every tick from before this migration.
ALTER TABLE ticks ADD COLUMN activity_tool TEXT;
ALTER TABLE ticks ADD COLUMN activity TEXT;
ALTER TABLE ticks ADD COLUMN activity_at TEXT;
