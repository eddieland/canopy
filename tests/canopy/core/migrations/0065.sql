-- sha256 of 0065_review_request_personas.sql: e7da6a60dfe581f4fc11def1e2169a8b38815dd4a3ab2f0160acc4c2c01f6f66

INSERT INTO review_request_personas (request_id, persona)
VALUES ((SELECT min(id) FROM review_requests), 'skeptic');
