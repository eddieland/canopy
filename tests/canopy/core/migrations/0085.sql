-- sha256 of 0085_review_dismissal_reasons.sql: e6881dcf4ebc1574e02760374a4c6d48b9563b2b302f907c60d34adcc522672e

-- Creates no table, so seeds no row: the dismissal 0020 seeded gains a reason.
UPDATE review_dismissals SET reason = 'wrong';
