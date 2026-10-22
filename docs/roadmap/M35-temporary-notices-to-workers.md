# M35. Temporary notices to workers

`canopy notice 'TEXT' [--for DURATION]`, and the web UI's settings page and banner, set and clear one notice at a
time, a journal fact that lapses on its own (`core/notice.py`): `implement`, `fix-ci`, and `resume` workers and
reviews hear it as `{{NOTICE}}`, chores as `notice` in their `## Run` object, and splits not at all; the overseer reads
the recent ones and holds a failed check the notice explains, raising `notice_rerun` once it ends; setting or clearing
one wakes the loop, and its lapse is a gate (DESIGN §6, §8, §14, §22; TRUST_MODEL T1, T8).

Status: done 2026-10-15.
Learned: closed on the operator's request with the tests with the fakes passing, before the live check during an
outage, which is SCENARIOS S37. The open questions settled small: 1 KiB, four hours by default and seven days at most,
and no repository scoping until real use asks for it (DESIGN §8, Open). A lapse commits nothing, so the web UI's
stream, which reads again only on a commit, watches the lapse of the notice it sent.
