# Agentic quick start

Let your own coding agent set canopy up with you. It interviews you, one question at a time, and does the work of
README's install steps and the first stages of [GETTING_STARTED.md](GETTING_STARTED.md): it installs treehouse and
canopy, makes the workspace and clones your repositories, sizes and sets up their worktree slots, offers the sandbox and
checks it, and ends on one dry tick you read together. It asks before it runs anything with `sudo`, changes anything
outside the workspace and your config directories, or spends a model call on a tick.

Prefer to do it by hand? README's [Install](../README.md#install-target-five-steps-no-more) is the same path, five
steps.

## 1. Make the workspace directory

canopy runs from a workspace: a directory of its own, holding a clone of each repository it works in. Make an empty
one, on your fast disk if you have one (its worktree pools live inside it), and not inside a git checkout:

```sh
mkdir ~/canopy && cd ~/canopy
```

## 2. Start your agent there

Any agent that can run shell commands works: Claude Code (`claude`), OpenCode (`opencode`), Codex, and the like. Start
it in the workspace directory. Whichever runs the interview, canopy's own runs use OpenCode, so the interview installs
OpenCode too if it is missing.

## 3. Paste this prompt

```text
Set up canopy (https://github.com/eddieland/canopy) with me. This directory is my new canopy workspace. Fetch the setup interview with `curl -fsSL https://raw.githubusercontent.com/eddieland/canopy/main/docs/SETUP_INTERVIEW.md`, read all of it, and follow it: interview me one question at a time, and ask before anything that needs sudo, changes something outside this directory and my config directories, or spends a model call.
```

If your agent cannot run `curl`, paste the whole of [SETUP_INTERVIEW.md](SETUP_INTERVIEW.md) instead.

## What you will be asked

Have these ready; the interview finds the rest on your machine:

- your tracker (Jira, GitHub Issues, Linear, ...) and the query that finds your candidate tickets;
- the HTTPS clone URL of each repository canopy should work in;
- your tracker account id (for Jira, your accountId) and your GitHub login;
- whether a fresh checkout of each repository builds and tests as it is, or needs local files or an install first;
- whether you want workers in a sandbox ([SANDBOX.md](SANDBOX.md)): opt-in, Linux or macOS, and not yet proven.

Signing in is yours alone. You connect OpenCode to your model provider and its MCP servers to GitHub and your tracker;
the agent never sees or handles a token. It shows you the branch protection canopy relies on, and does not change your
repositories or your tracker on its own.

## When it is done

It leaves you with a workspace that loads, slots that are made, and a dry tick's plan for one ticket you labeled. It
does not start the loop. Run `canopy loop` yourself once you trust the plan, and go on from README's
[Daily surface](../README.md#daily-surface). It ends with a summary of what it installed and changed, and anything left
to do.

Run the interview again any time, in the same workspace: it checks what is already set up and picks up from there.
