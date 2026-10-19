# M18. Private tickets

Tickets the operator starts privately (DESIGN §22, D072, D075): `canopy start`, `stop`, `reply`, and `show`, the
`messages` table, a private worker that only reads the tracker, and `awaiting_reply`.

Status: done 2026-10-13.
Learned: closed on the operator's real use: the first live session's tickets were all started privately. The full run is
SCENARIOS S16, and OpenCode's wildcard deny, confirmed only in its source, is S3. Atlassian's MCP server needs
`?tools=all` in its URL for a private worker to read comments.
Next: a start does not end the loop's wait (MEASUREMENTS F3); M28 takes it.
