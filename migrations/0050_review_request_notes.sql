-- The operator's notes on a review request (DESIGN §21): what they want the reviewer to know or look at, such as what
-- the author asked for or the part of the change that worries them. The reviewer's prompt carries them. NULL when the
-- request has none; asking again with notes replaces them on the open request.
ALTER TABLE review_requests ADD COLUMN notes TEXT;
