-- Decisions by ticket, newest first (DESIGN §22): a ticket's page reads its latest decisions, and the tickets list and
-- `canopy status` read each ticket's newest one. Each was a scan of every decision ever recorded, a few hundred
-- thousand rows on a journal with months of ticks, once for each ticket the list shows.

CREATE INDEX decisions_ticket ON decisions(ticket_key, id);
