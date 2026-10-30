# CI other than GitHub Actions

How to let canopy's workers read the logs of a CI system other than GitHub Actions, such as Jenkins, Buildkite, or
TeamCity. Everything here is your own config and your own tools: canopy knows nothing about any CI system, and none of
this is required to run it. Without it, a worker sent to fix a red check sees the check's name and link but cannot read
why it failed, so it guesses or tries to reproduce the failure locally.

Written from canopy's prompts and agent definitions, and not yet tried on a running loop. Check what you get with
`canopy agents` after each step.

## What works already

canopy reads a PR's checks from GitHub: its head commit's check runs and commit statuses (DESIGN §7). A CI system that
reports to GitHub, such as Jenkins through its GitHub or Checks plugin, is one canopy sees:

| What | Needs a tool of yours |
| --- | --- |
| A red check starts a `resume` for `ci`, under the attempt limit and its cooldown | No |
| The worker learns the check's name and its link, the status's target URL (`gh pr checks` lists both) | No |
| A flaky check is kicked by a re-push (`trust.max_flaky_kicks`), or raised as `flaky_rerun` for you to rerun | No |
| The worker reads the failed build's log | **Yes** |

The worker's prompt reads a failed check's log through the GitHub MCP, or with `gh pr checks` and
`gh run view --log-failed`, and those read GitHub Actions only. A CI system that reports nothing to GitHub is one canopy
never sees: no red check, no `resume`. Turn its GitHub reporting on first.

## Which of canopy's agents should read the logs

- **The workers, `canopy-worker` and `canopy-worker-private`: yes.** They fix the failures. Their shell runs every
  command but those their rules deny, so a command of yours needs no allow.
- **The planner, for feedback plans: if you use them.** It plans a `resume` from the PR's failed checks, and reads no
  log otherwise, not even GitHub Actions' (DESIGN §32). Its shell runs only what `runtime.allow_bash` names.
- **The overseer: no.** It decides from a check's state, which the `vcs` source reads, and a log is text anyone who can
  make the build print can shape, in the agent with the most authority.
- **The reviewer: no.** Its prompt leaves failed checks to CI and the worker, and it has no shell, which
  `runtime.allow_bash` refuses to give it.
- **A chore that watches CI**, such as `build-queue` in [examples/chores/](../examples/chores/README.md), gets an agent
  of its own, with bash allowed for exactly its CLI's reads.

## A read-only command, the simpler way

A small command that prints one build's log, and nothing else, is the least you can add: it has no write tool to deny,
and its credentials stay in it. What it should do:

- Take the link `gh pr checks` lists, and refuse one that is not on your CI host, so a link read from a log or a PR
  cannot send your token anywhere else.
- Read its credentials from a file of its own, readable only by you, never from an argument or a variable the worker
  sets.
- Only read: no rerun, cancel, or trigger, whatever the CI's API offers. Reruns are yours or canopy's kicks.
- Print a bounded amount, such as the log's last few hundred lines, so one long log does not fill the worker's context.

For Jenkins, whose console log is at `<build URL>/consoleText`, with an API token in a netrc file:

```sh
#!/bin/sh
# jenkins-log: print the end of one Jenkins build's console log. Reads only.
set -eu
url=${1:?usage: jenkins-log BUILD_URL}
case $url in
    https://jenkins.example.com/*) ;;
    *) echo "jenkins-log: not a build on jenkins.example.com: $url" >&2; exit 2 ;;
esac
# One line: machine jenkins.example.com login <user> password <API token>, for an account that can only read builds.
curl -fsS --netrc-file "$HOME/.config/jenkins-log/netrc" "${url%/}/consoleText" | tail -n "${JENKINS_LOG_LINES:-400}"
```

Put it on `PATH` through an absolute entry, `chmod 600` the netrc file, and run it yourself on the link of a failed
build. Then:

1. **Tell the workers.** Their prompt names GitHub's tools only, so add a line to `paths.worker_instructions`
   ([GETTING_STARTED.md](GETTING_STARTED.md#teach-the-loop-your-org)), such as: "Checks named `jenkins/*` run on
   Jenkins, not GitHub Actions: `gh run view` cannot read them. Find the build's link with `gh pr checks`, and read its
   log with `jenkins-log <link>`."
2. **The planner, if you want it to read logs too:** allow the command by pattern in your private config, and add the
   same line to its instructions. canopy refuses `curl` there, not your script, so what the script can do is yours to
   answer for (TRUST_MODEL T1).

   ```toml
   [runtime.allow_bash]
   planner = ["jenkins-log *"]
   ```

3. **Check it.** `canopy agents` lists the planner's allow. The next `resume` for `ci` on a Jenkins check should call
   the command, and its summary name the cause it read.

## An MCP server, if your CI has one

Some CI systems ship an MCP server, Jenkins as a plugin among them. Add it to your OpenCode config as any other server;
canopy's agents run in your OpenCode, so every one of them is then offered it
([GETTING_STARTED.md](GETTING_STARTED.md#narrowing-what-canopys-agents-are-offered)). Then narrow it:

- **Deny it whole to the agents above that should not read logs**: `"<server>_*": "deny"` for `canopy-overseer`,
  `canopy-reviewer`, `canopy-chore`, and `canopy-planner` unless you want it reading logs, as above.
- **Give the workers its read tools by name, after a deny of the whole server.** canopy's workers deny write tools by
  patterns made for GitHub and the trackers (D084), such as `*run_workflow*`, `*rerun*`, and `*cancel*`; a CI server's
  `triggerBuild` or `stopBuild` matches none of them. A deny of the server first, then an allow of each read tool,
  fails closed for a write tool you did not name, whatever the next release adds. With a server named `jenkins`:

  ```json
  {
    "agent": {
      "canopy-worker": {
        "permission": {"jenkins_*": "deny", "jenkins_getBuild": "allow", "jenkins_getBuildLog": "allow"}
      }
    }
  }
  ```

  The tool names here are an example: take your server's from `canopy agents`, and give `canopy-worker-private` the
  same rules.
- **Give it a token that can only read**, whatever its tools are: a rule is defense in depth, the token is the limit.
- **Under OpenCode 2, set the server's entry to `codemode: false`**, since canopy's agents deny code mode (D077).

Then tell the workers which checks it reads, in `paths.worker_instructions`, as for a command.

## With the sandbox

A sandboxed worker reaches only the hosts and files its template allows ([SANDBOX.md](SANDBOX.md)). In
`~/.config/canopy/sandbox/worker.json`, which `plan_cmd` uses too, add your CI's host to `network.allowedDomains` and
the command's credential file to `filesystem.allowRead`. An MCP server starts inside the sandbox and needs the same.
The worker can then read that token, as it reads your push credentials: one more reason for a token that can only read
builds, and no other job's secrets.

## Trust

- **A log is untrusted text.** Whoever can make a build print can write to the worker. The worker's prompt already says
  to ignore instructions in a log and mention them in its summary, as it does for GitHub Actions' logs.
- **The token is the worker's.** A steered worker can use it for anything the token can do, through your command or
  around it. A token that can only read builds bounds that.
- **No reruns.** A worker never polls or retries CI. Leave rerunning to `trust.max_flaky_kicks` and to you, after
  `flaky_rerun`, so no tool you add gives a worker a way to hide a failure behind a green rerun.
