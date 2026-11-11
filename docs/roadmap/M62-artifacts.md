# M62. Artifacts, and comments on them back to the ticket

REQUIREMENTS R26, DESIGN §38, TRUST_MODEL T1, T6, T7, and T8. Workers publish artifacts people comment on, to Louvre
or to the local store canopy ships (`canopy-artifacts`, whose README is the contract both serve), through the same MCP
tools: `[artifacts]` in the private file, the public worker alone allowed the tools, the `artifacts` source reading the
store's feed each tick and poll, each comment reaching its ticket's conversation, a listed author's as authority and
anyone else's an attention item, and canopy setting an artifact's ticket per run.

Status: done 2026-11-11.
Learned: closed on the operator's own use, before the checks in Accept ran one by one. Authority is decided in code,
which the tests with the fakes hold; the round trip against a real store, and its feed, which the fakes stand in for,
is SCENARIOS S78. A fourth stage, plans as artifacts, was dropped at the operator's word (2026-10-24): a plan stays
§25's file.
Next: whether buy-in on an artifact holds the `implement` in code, or is asked as a Louvre decision, waits on that
being tried on a real ticket.
