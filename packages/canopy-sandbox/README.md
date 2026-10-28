# canopy-sandbox

canopy's sandbox wrapper (DESIGN §24): `canopy-sandbox` runs an agent command inside `srt`, Anthropic's sandbox
runtime, with a policy made for that run. It is a prefix on a command template in canopy's user config, a program of
its own that canopy never imports: the harness sees only the command (D041). Stdlib only.

It is installed beside canopy: `uv tool install` puts it on `PATH`. [docs/SANDBOX.md](../../docs/SANDBOX.md) is the
operator's guide: what the sandbox stops, the host setup on Linux and macOS, `canopy sandbox setup`, which installs
`srt` and the policy templates, the config, and what to do when a run fails in it.

```sh
canopy-sandbox ROLE [--read PATH]... [--] COMMAND [ARG]...
```

```toml
worker_cmd_prefix = 'canopy-sandbox worker --read {definitions_dir} --'
```

- `ROLE` is `worker`, `setup`, `chore`, `review`, or `overseer`, and picks the policy template `ROLE.json` in
  `$XDG_CONFIG_HOME/canopy/sandbox/`.
- `--read PATH`, repeated, is a path the command may read: pass `{definitions_dir}`, so the agent can load canopy's
  agent definitions.
- `COMMAND` and its arguments reach `srt` unchanged, after a `--`, so none is read as an option.

For each run it:

1. Scrubs its environment of what would point git at another repository, relative `PATH` entries, and `BASH_ENV` and
   `ENV`.
2. Finds the worktrees the run works in and their git directories (none for a chore or the overseer).
3. Fills the template's placeholders (`@CWD@`, `@WORKTREES@`, `@GIT_SHARED@`, `@TMPDIR@`, and the rest the module
   docstring lists) with those paths, and writes the policy to a private directory of the run's own, beside its temp
   directory. The policy denies reading the directory that holds every run's, and the one that holds every role's
   cache, on top of the template's `denyRead`. Since `srt` binds an `allowRead` or `allowWrite` path back under a
   denied one, a template that names one of these or a directory that holds it, such as a chore's cwd of `~`, is
   refused.
4. Points the command's caches at the role's own cache directory, `$XDG_CACHE_HOME/canopy/sandbox/ROLE/`, never the
   operator's, since a cache a run can write is code the host may run later. Setup shares the worker's, which it
   warms.
5. For a worker or setup, puts a `git` of its own first on `PATH`. In one of the run's worktrees, it points git at the
   run's object directory; anywhere else, as in a repository a tool keeps in its cache or one `git clone` makes, it
   runs git unchanged. A git run by its absolute path skips it, and in a worktree cannot write objects at all.
6. Runs `srt --settings POLICY -- COMMAND...`, removes the run's directory, and exits with `srt`'s status.

It refuses a template with an unknown placeholder, no `filesystem.denyRead`, or no `network.allowedDomains`, since
`srt` would run such a command with no sandbox at all. The `srt` it runs is the one `canopy sandbox setup` installed
in `$XDG_DATA_HOME/canopy/sandbox-runtime/`, or else the first on `PATH`. The policy templates canopy ships are in
[templates/](src/canopy_sandbox/templates/).
