-- The breakdown entries each member of an initiative fulfils (DESIGN §43), as the operator registered them: one or
-- more `B<n>` of the plan approved when they did, or none, for a ticket the breakdown did not foresee. A registration
-- replaces the member's entries; the ids are data, never instructions, checked against the approved plan as written.
CREATE TABLE initiative_member_entries (
    member_id  INTEGER NOT NULL REFERENCES initiative_members(id),
    entry      TEXT NOT NULL CHECK (entry GLOB 'B[1-9]*'),
    PRIMARY KEY (member_id, entry)
);
