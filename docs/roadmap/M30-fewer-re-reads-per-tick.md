# M30. Fewer re-reads per tick

The probe's facts in the state block, so the overseer read a PR or a ticket in full only when one changed
(MEASUREMENTS 2026-10-12 F6; 2026-10-13 F14).

Status: superseded by M37 (2026-10-15). M37 puts the connectors' observations in the state block instead of a probe's
facts and drops the overseer's reads, so an unchanged PR or a stopped ticket is read only while its observations are
stale, and it checks authorized repliers against comment authors in code, the question this milestone left open.
