-- A ticket's title (DESIGN §6, §13): a short human name the overseer gives it with `canopy ticket set --title`, from
-- the ticket's own title. For display, and for the session title of the ticket's runs; never read as truth. NULL until
-- named.

ALTER TABLE tickets ADD COLUMN title TEXT;
