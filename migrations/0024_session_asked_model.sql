-- The model a session of the runtime's was set to run on, as `provider/model[@variant]`, where the runtime records one
-- (DESIGN §13): what was asked for. A session's replies name the models that wrote them, so one set to a router, such
-- as `github-copilot/auto`, names only what it was routed to, and what asked for the router could not be told. NULL
-- for a session read before canopy kept it, or one the runtime records no model for.
ALTER TABLE runtime_sessions ADD COLUMN asked_model TEXT;
