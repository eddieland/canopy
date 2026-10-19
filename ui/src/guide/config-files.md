# Config files

Every key canopy reads, in the two example files that ship with it: each key at its default, with a comment saying
what it does. Copy what you need and leave out the rest; a key you don't set keeps its default.

## Where they live

canopy reads three files, each overriding the one before it, key by key:

1. `canopy-workspace.toml`, at the workspace's root: the map of the workspace, its repositories and its tracker's
   query. It's the one file meant to be shared, and committed if the workspace is.
2. `~/.config/canopy/config.toml` (under `$XDG_CONFIG_HOME`, if you set it): yours, for every workspace. What holds
   everywhere goes here, such as the runtime templates and your notification sinks.
3. `.canopy/config.toml`, under the workspace's root: yours, for this workspace alone. `canopy init` writes your
   queue label and your trust lists here.

Some keys are yours alone, such as your queue label and who may resume your work: canopy refuses to run if the
workspace file sets one, and the error names the key and where it belongs. Anyone who can commit to a shared file
shouldn't get to choose who your loop takes orders from.

## Changing them

The loop reads the files when it starts. **Reload** in [Settings](settings#config) reads them again, as `kill -HUP`
on the loop does, and says which changes wait for a restart. An unknown key is an error in every file, so a typo
stops the loop rather than quietly doing nothing. The same goes for a key from a newer canopy than the one you run.

## The workspace file

A workspace of two repositories, `api` and `web`, as `canopy init` would leave it once you'd filled it in.

```toml examples/canopy-workspace.toml
```

## Your file

Every other key, most at its default. It reads the same in either of your two files.

```toml examples/config.toml
```

Chore prompts to start from, and ideas for more, are in
[examples/chores](https://github.com/eddieland/canopy/tree/main/examples/chores) in canopy's repository.
