# M27. Session transcripts in the web UI

A run's and a tick's OpenCode session, its text, tool calls, and model calls, read back from its log
(`core/transcript.py`).

Status: done 2026-10-13.
Learned: closed on the operator's real use; the check against `opencode export` is SCENARIOS S30. A running run's events
reach its log only when it ends, because `procs.run` captures stdout whole.
Next: watching a run live needed the worker's stdout streamed to its log, taken on request (2026-10-15): its events
reach the log as it prints them, and its session, spend, and latest tool call its row (DESIGN §8); the live check is
SCENARIOS S38.
