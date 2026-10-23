-- A PR's title as canopy's reader last read it (DESIGN §30): the PR author's text, one line, cut and marked past 200
-- characters, for display only, never into a prompt. NULL on a PR read before canopy read titles, and from a connector
-- that prints none.
ALTER TABLE observed_prs ADD COLUMN title TEXT;
