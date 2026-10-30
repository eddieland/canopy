-- The question a running worker's, planner's, or reviewer's card asks the operator, and their answer (DESIGN §41):
-- when canopy first recorded a card asking it, kept while the cards after it ask the same; the letter of the option
-- the operator chose; and when they chose it. A card that asks another question starts it over, with no answer, and
-- one that asks none clears all three. NULL on a run whose card asks nothing, and on every run from before this
-- migration.
ALTER TABLE runs ADD COLUMN card_asked_at TEXT;
ALTER TABLE runs ADD COLUMN card_answer TEXT CHECK (card_answer IN ('A', 'B', 'C', 'D', 'E'));
ALTER TABLE runs ADD COLUMN card_answered_at TEXT;
ALTER TABLE review_runs ADD COLUMN card_asked_at TEXT;
ALTER TABLE review_runs ADD COLUMN card_answer TEXT CHECK (card_answer IN ('A', 'B', 'C', 'D', 'E'));
ALTER TABLE review_runs ADD COLUMN card_answered_at TEXT;
