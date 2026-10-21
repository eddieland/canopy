-- The personas the operator chose for a review request (DESIGN §31): the voice its review is written in, in place of
-- `[personas] reviewer`. A request with no row here gets that default. Set only by the operator, with
-- `canopy start URL --review --persona` or `canopy persona URL`, and never by an agent; asking again with a persona
-- replaces the request's set.
CREATE TABLE review_request_personas (
    request_id  INTEGER NOT NULL REFERENCES review_requests(id),
    persona     TEXT NOT NULL,
    PRIMARY KEY (request_id, persona)
);
