# M41. Limits and trust settings from the web UI

REQUIREMENTS R16, DESIGN §12 and §22. Needs M20 and M49. Asked for by the operator (2026-10-14): change a pool's slots
or a trust setting from the web UI without opening a config file. Today the web channel asks for a reload and writes
no config (TRUST_MODEL T8).

- Which keys: an allowlist in code, by name, never a section's wildcard. Limits, raised or lowered: the counts in
  `capacity` (`slots_per_repo` and `repo_slots` among them), the attempt limits and the cooldown in `policy`, and
  `loop.interval_minutes` and `loop.idle_max_minutes`. Only toward stricter: `policy.stacking` to `"never"`, removing
  an entry from `trust.authorized_repliers` or `trust.trusted_reviewers`, `trust.rebase` to false, and
  `trust.commit_trailer` to true. Nothing else: `runtime.*`, `notify.*`, `chores`, `paths.*`, `review.*`, `serve.*`,
  `tracker.*`, the comment marks, and the trailer's name and email each run a command, choose a prompt or whose words
  are read, or move the listener. A key added to a section later is not editable until it is named.
- Why the stricter-only keys: a config write outlives the secret. A new secret ends every session, but a replier added
  through a stolen one would go on steering workers.
- Ceilings: no count can be raised from the page past a ceiling in code, such as `capacity.max_workers` at 8; the file
  can set any value. A raise within the ceilings outlives a new secret too; that residual is spend, and the page and
  the log show it.
- Where it writes: the workspace's private file (M49) only, never the workspace file (shared, perhaps committed, T7)
  nor the user file, which serves every workspace. A key whose value came from the user file is written to the
  private file, where it shadows the user file's for this workspace alone, and the page says so before the save.
  Edited in place, keeping the operator's comments and layout, so a TOML writer joins the runtime dependencies with
  its DECISIONS entry; `tomllib` only reads. Rejected: a file of canopy's own layered after the private file (a hand
  edit to the private file would be silently overridden), and writing the file anew with the stdlib (its comments
  lost).
- How: the request carries a hash of the private file as the page read it. The server holds a lock from reading the
  file to replacing it, so two requests cannot both pass the check on the same hash; a file whose hash differs is
  refused as `stale`, checked again just before the replace, so a hand edit is lost only if it lands in that last
  moment. The change is applied to a copy and validated by `config.load`, as any `canopy` command would read it; a
  refusal writes nothing and gives the loader's message. The file is replaced atomically, keeping its mode, and
  refused when it is a symlink or not the operator's (D053's check). Then the loop is asked to reload through the
  existing path (`loop.reread`).
- The answer says what was saved apart from what the reload did: the keys changed, whether they wait for a running
  tick to end, and that a run already running keeps the prompt and permissions it started with, so a stricter trust
  setting reaches only runs started after it. A save whose reload was not asked for, the server stopping between the
  two, takes effect at the next reload; the settings page's Reload asks again. Under `canopy loop --every`, a changed
  `loop.interval_minutes` is saved, and the answer says `--every` still sets the pace until the loop restarts.
- No CLI verb: the operator's editor is the CLI's way. A `canopy config set` would be in reach of the overseer's
  `canopy *` bash rule; the write refuses as `inside_run` when `CANOPY_TICK_ID` or `CANOPY_RUN_ID` is set regardless.
- Each change is logged with channel `web`, the key, and its old and new values.
- Slots: a changed `capacity.slots_per_repo` or `capacity.repo_slots` bounds leases from the next tick. Making or
  removing slots is still `canopy workspace sync`, which the page names; the web UI runs no sync.
- API: `GET /config`, each editable key's value, the file it came from, its ceiling, and the private file's hash;
  `PATCH /config`, the changed keys and that hash. The settings page edits them, beside Reload.
- TRUST_MODEL T8: "It cannot write config" becomes the allowlist, ceilings, and stricter-only keys above, and its
  residual gains a stolen session raising limits up to their ceilings, which outlives a new secret until the operator
  sees it. DESIGN §12 marks the keys the page edits and their ceilings,
  and §22 the routes and the settings page. DECISIONS: an entry for what the web channel may write to config (a rule
  the trust boundary relies on), and one for the TOML writer.
- Tests with the fakes: an allowed key written and reloaded, the file's comments kept; a key outside the allowlist, a
  stricter-only key loosened, a count over its ceiling, a stale hash, two requests on one hash, an invalid value, and
  a symlinked private file each refused with the file unchanged; neither the workspace file nor the user file ever
  written; Playwright for the form.
- Open: the ceilings' values; whether the page also shows the keys it cannot edit, read-only, with the file each came
  from.

Accept: the tests above pass. Live: while `canopy loop` runs, the operator changes `capacity.slots_per_repo` and
removes a trusted reviewer from the settings page; the next tick leases under the new size and reads the shorter list;
and the private file keeps its comments, with only those two values changed.

Status: not started.
