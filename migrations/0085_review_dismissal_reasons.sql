-- Why the operator dismissed a review's finding (DESIGN §21): `wrong`, the finding does not hold; `intentional`, it
-- holds but the change means it; `not_worth_it`, it holds and is not worth fixing. It tells a reviewer's noise from
-- findings that were right but not acted on. NULL on a dismissal from before canopy asked why.
ALTER TABLE review_dismissals ADD COLUMN reason TEXT CHECK (reason IN ('wrong', 'intentional', 'not_worth_it'));
