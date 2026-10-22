# Using codebase-memory-mcp

How to give canopy's workers [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp), an MCP server
that indexes a repository into a graph of its functions, calls, and routes, and keep it from the agents that should not
have it. Everything here is your own OpenCode config: canopy has no setting for it, and none of this is required to run
it. canopy's agents run in your OpenCode, so once you install the server, every one of them is offered it, as
[GETTING_STARTED.md](GETTING_STARTED.md#narrowing-what-canopys-agents-are-offered) explains.

Written from codebase-memory-mcp's source at [10ab613](https://github.com/DeusData/codebase-memory-mcp/commit/10ab613)
(2026-10-22), and not yet tried on a running loop. Check what you get with `canopy agents` after each step.

## What its installer adds to your OpenCode

The installer finds OpenCode and writes to its global config, `~/.config/opencode/`, which canopy's agents load as
yours do:

| What | Where | What canopy's agents get |
| --- | --- | --- |
| The MCP server, `codebase-memory-mcp` | `opencode.json` or `opencode.jsonc`, under `mcp` | Its 17 tools, in every agent, until a rule denies them |
| A "Codebase Memory" section, telling an agent to prefer graph tools to grep | `AGENTS.md` | In every agent's instructions, the overseer's too |
| The `codebase-memory` skill | `skills/` | Offered where skills are, as your other skills are |
| Three read-only subagents | `agents/codebase-memory-*.md` | Nothing: canopy's agents deny `task` |
| A plugin, `cbm-augment.ts` | `plugins/` | Graph context added to every grep, glob, and read result, and to a session's first tool result |

The plugin runs in every OpenCode process, canopy's included, and no permission rule turns it off. Updates re-run the
installer, which writes all of these again; pass `--skip-config` to update the binary alone.

## Which of canopy's agents should have it

- **The workers, `canopy-worker` and `canopy-worker-private`: yes.** A worker starts in its slot, the repository's
  checkout, and codebase-memory-mcp indexes and watches the directory a session starts in, so the graph is of the
  worker's own slot.
- **The reviewer and the planner: no.** Each starts in a directory of canopy's that links to the checkout, and reads
  only through that link (DESIGN §21, §25). codebase-memory-mcp skips symlinks when it indexes, so it finds nothing
  there; and an MCP server is not bound by OpenCode's `external_directory` rule, so it would let them read any project
  indexed on your machine.
- **The overseer and the chores: no.** They do not read code, and each tool's schema is sent with every model call.

A joint run, a worker across several repositories, starts in a desk of links (DESIGN §18), so it gets no index either.

## Setup

1. **Install it** as its README says. To keep its plugin and instructions out of canopy's agents, delete
   `~/.config/opencode/plugins/cbm-augment.ts` and the "Codebase Memory" section of `~/.config/opencode/AGENTS.md`,
   and keep the skill: an agent reads a skill only when it loads it. That takes them from your own sessions too.
2. **Add rules for canopy's agents** to the `agent` block of `~/.config/opencode/opencode.json`, beside any you have.
   The workers get the server's read tools and `index_repository`, allowed by name after a deny of the whole server,
   so a tool a later release adds is not offered until you add it. `manage_adr` and `ingest_traces` write to an index
   that later runs and your own sessions read, and `delete_project` drops one, so no worker gets them:

   ```json
   {
     "agent": {
       "canopy-overseer": {"permission": {"codebase-memory-mcp_*": "deny"}},
       "canopy-planner": {"permission": {"codebase-memory-mcp_*": "deny", "skill": {"codebase-memory": "deny"}}},
       "canopy-reviewer": {"permission": {"codebase-memory-mcp_*": "deny", "skill": {"codebase-memory": "deny"}}},
       "canopy-chore": {"permission": {"codebase-memory-mcp_*": "deny", "skill": {"codebase-memory": "deny"}}},
       "canopy-worker": {
         "permission": {
           "codebase-memory-mcp_*": "deny",
           "codebase-memory-mcp_index_repository": "allow",
           "codebase-memory-mcp_index_status": "allow",
           "codebase-memory-mcp_check_index_coverage": "allow",
           "codebase-memory-mcp_list_projects": "allow",
           "codebase-memory-mcp_search_graph": "allow",
           "codebase-memory-mcp_search_code": "allow",
           "codebase-memory-mcp_trace_path": "allow",
           "codebase-memory-mcp_get_code_snippet": "allow",
           "codebase-memory-mcp_get_architecture": "allow",
           "codebase-memory-mcp_query_graph": "allow",
           "codebase-memory-mcp_get_graph_schema": "allow",
           "codebase-memory-mcp_detect_changes": "allow"
         }
       }
     }
   }
   ```

   Give `canopy-worker-private` the same rules as `canopy-worker`, and each chore agent of your own, such as
   `canopy-introspect`, the same rules as `canopy-chore`: a rule reaches only the agent it names. The read tools are
   the eleven of the server's own `analysis` profile. The skill is denied by name, so canopy's own skill rules keep
   their order; the overseer needs no such rule, since with Jira or GitHub as the tracker it is sent no skill tool.
3. **Tell the workers when to use it**, if the skill alone does not. A line in your `worker_instructions` file
   ([GETTING_STARTED.md](GETTING_STARTED.md#teach-the-loop-your-org)) reaches every worker, such as: "Before changing a
   function, find its callers with `trace_path`. Index the slot with `index_repository` first if `index_status` says it
   is not indexed." A line about one repository goes in its `AGENTS.md` instead.
4. **Check** with `canopy agents`: the workers list the server's tools and the skill, and the other agents neither. A
   chore's own agent is checked as GETTING_STARTED shows.

## Indexes and slots

- **One index per slot.** codebase-memory-mcp keys a project by its path, and each slot keeps its path from run to
  run, so a pool of four slots builds four indexes of the repository, under `~/.cache/codebase-memory-mcp/`.
  `canopy gc` never removes them; `codebase-memory-mcp cli list_projects` lists them, and removing a pool leaves
  its indexes behind.
- **The first run in a slot pays for the index**, inside its own time limit. For a large repository, index each slot
  once from your shell, `codebase-memory-mcp cli index_repository --repo-path <slot>`, for each slot directory under
  the workspace's `.treehouse/`.
- **A later run finds the index of another branch.** The slot was reset and checked out since, and the server's watcher
  syncs a project from git only while a session started there is open. Have a worker check `index_status` and
  `check_index_coverage` before it trusts what the graph says, as the shipped skill does.
- **Keep the index out of the repository.** `index_repository` writes `.codebase-memory/` into the checkout only with
  `persistence: true`; if a worker passes it, the directory is one more untracked file a commit can pick up. Add
  `.codebase-memory/` to your global gitignore to be sure.

## Trust

- **The server reads what your user can read.** A worker steered by text in a ticket can index another directory and
  read it through the graph, and query every project already indexed on your machine. Without the sandbox a worker's
  shell reads the same files, so this adds nothing there. `CBM_ALLOWED_ROOT`, set in the server's `environment` in
  your OpenCode config, confines indexing to one directory, your own sessions' included; it does not hide indexes
  already built.
- **Not under the sandbox, yet.** The shipped templates (SANDBOX.md) refuse `~/.cache`, where the indexes live, and
  codebase-memory-mcp does its indexing in one daemon per account, shared by every session. Whether a sandboxed run
  reaches a daemon you started outside it is untested. Until it is, deny the server to the agents of each role you
  sandbox, as to the overseer. A rule names an agent, not a sandbox, so it takes the server from every run of that
  agent: with the workers sandboxed, no worker has it.
- **Network:** the server makes no request of its own, and sends no telemetry; its optional graph UI listens on
  loopback only when you start it.
