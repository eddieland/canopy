# M10. Notification sinks

Per-sink delivery with cursors and digests (DESIGN §20, D035), a desktop sink, a Slack sink as a uv workspace member,
`loop.failing`, and `canopy notify test`.

Status: done 2026-10-13.
Learned: closed on the operator's real use; the live desktop and Slack checks are SCENARIOS S24 and S25. DESIGN §15's
three-failure item is `loop.failing` alone, since the attention list is the latest `ok` tick's.
