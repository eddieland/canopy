-- What a new approval of an epic's plan left for its members (DESIGN §43, When its plan changes). `changed_ids` is a
-- member's pending notice: the ids, space-separated, of every change of its epic's plan that reached it since its work
-- last took one in, which its next plan run is told and the operator's approval of its plan clears; while it is set,
-- an approved plan's `implement` on a ticket with no branch is refused, `epic_changed`. `epic_changed_ids` marks a
-- plan still `proposed` that an approval superseded as stale, naming the ids that reached it. NULL for none, and for
-- every row from before this migration.
ALTER TABLE epic_members ADD COLUMN changed_ids TEXT;
ALTER TABLE plans ADD COLUMN epic_changed_ids TEXT;
