-- Who made each decision (DESIGN §37, ROADMAP M38, TRUST_MODEL T5): the overseer, through one of its verbs, or the
-- harness on its own, in code, which now records decisions that need no judgment before the overseer runs. NULL on a
-- decision recorded before the journal said, since a reason the harness raises today the overseer may have recorded
-- then.
ALTER TABLE decisions ADD COLUMN decider TEXT CHECK (decider IN ('overseer', 'harness'));
