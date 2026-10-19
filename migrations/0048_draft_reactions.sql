-- Reactions staged with drafts (DESIGN §29): a thread's draft may carry one of the reactions GitHub offers, on the
-- review comment it names, beside its reply or alone. The reaction is part of each version, as the text is, so an edit
-- of either is a new version and a send names both.

-- A version with a reaction may have no text: it sends the reaction alone. One without a reaction needs its text.
ALTER TABLE draft_versions ADD COLUMN reaction TEXT CHECK (
    COALESCE(reaction IN ('+1', '-1', 'laugh', 'confused', 'heart', 'hooray', 'rocket', 'eyes'), body != '')
);

-- The reaction a send added on GitHub, and when. A send adds its reactions before its review, so one whose review then
-- failed keeps them here: they stay on GitHub, and sending again adds nothing more.
ALTER TABLE drafts ADD COLUMN reacted TEXT CHECK (
    reacted IN ('+1', '-1', 'laugh', 'confused', 'heart', 'hooray', 'rocket', 'eyes')
);
ALTER TABLE drafts ADD COLUMN reacted_at TEXT;
