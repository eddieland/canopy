// canopy's plugin for a running agent: each job canopy asks of the agent process, as hooks the runtime calls. Its
// first job is the clock (DESIGN §33): near the end of the run's time, one line on each tool call's result tells the
// agent the minutes left before canopy stops the run, so it keeps its work before the kill. Its second is the split
// (§33): it cuts the system prompt after the agent's body, so that the tools and the body are a prefix the provider
// caches for the agent's unsandboxed runs, whatever directory each starts in; a sandboxed run's tools name its own
// temporary directory, so they share none. It is OpenCode 1's alone: 2 already caches the tools and the body apart from
// the environment, a sandboxed run's included.
//
// The agent runtime loads it from canopy's snapshot of its definitions, inside every agent process, sandboxed or not
// (TRUST_MODEL T4). So it is plain JavaScript that imports nothing but the runtime's own `node:fs`, and that only when
// the answer reads its file, so it loads with no network; and each job does as little as it can: it reads only what it
// is handed for that job (the clock, CANOPY_DEADLINE and the time; the split, the system prompt; the nudge,
// CANOPY_RUN_ID and each call's tool and session, and in a run that follows a plan, CANOPY_PLAN and the steps of each
// `status` call; the answer and the wrap-up, CANOPY_RUN_ID and each its one file canopy writes in the directory
// CANOPY_ANSWERS names; the directory, a shell call's command and working directory; under OpenCode 2, the refusal, a
// refused call's permission and resources), changes only what its
// hook is handed, writes no file, refuses no call, and grants no tool. Each job's hooks run in its own try, in the
// order of `JOBS`, so a job that throws neither fails a call that has already run nor keeps the jobs after it from
// theirs.
//
// Its third is the nudge (DESIGN §41): in a worker's, planner's, reviewer's, or one-off task's run, after a number of
// tool calls with no call of canopy's `status` tool, one line on the next tool call's result asks the agent to post an
// update of its progress; in a worker's run that follows an approved plan, the line also names the plan's file and the
// steps the worker last reported working and next.
//
// Its fourth is the answer (DESIGN §41): in a run that keeps its progress, when the operator has answered the question
// it asks, one line on the next tool call's result tells the agent the letter and the option it names, once.
//
// Its fifth is the directory (DESIGN §33): a shell command that opens with `cd <dir> &&` runs with that directory as
// its working directory instead, which the runtime checks as it checks the `cd`, so the rest of the command is checked
// from where it runs.
//
// Its sixth is the wrap-up (DESIGN §22): in a run that keeps its progress, once the operator stops its ticket and asks
// it to wrap up, one line on the next tool call's result asks the agent to keep its work and print its result line.
//
// Under OpenCode 2 it has two jobs more, its own. A session's first prompt waits until the tools of its MCP servers are
// registered, which 2 does only after the server connects, so that the first model call is sent them (`mcpTools`).
// And a call the run's permission rules refuse, which 2 reports to the agent as no more than `Permission denied:` and
// the permission, also says what it asked for and that the refusal is on purpose, not to be tried another way
// (`explain`); it reads the refusal's permission and resources, and changes only the reason the agent is told.
//
// Both of OpenCode's major versions load it, so its one export, the default, holds an entry point for each, and each
// version reads only its own: OpenCode 1 calls `server` for the jobs' hooks, and OpenCode 2 calls `setup`, which
// registers the same hooks under 2's names. Each needs the `id`. Neither calls any other export, so it has none.
//
// Its types are JSDoc, checked by `make lint` against each pinned runtime's own plugin types (tests/plugins/): a type
// import in a comment is no import at all, so the file stays one the runtime loads with nothing installed.

// @ts-check

/** @typedef {import("@opencode-ai/plugin").Hooks} Hooks */
/** @typedef {Parameters<NonNullable<Hooks["tool.execute.after"]>>[0]} AfterInput */
/** @typedef {Parameters<NonNullable<Hooks["tool.execute.after"]>>[1]} BuiltinResult */
/**
 * An MCP tool's result, which the runtime hands `tool.execute.after` in place of a built-in tool's (DESIGN §33). The
 * runtime's published types leave it out, so canopy names the part it writes.
 *
 * @typedef {{ content: Array<{ type: string, text?: string }> }} McpResult
 */
/** @typedef {Parameters<NonNullable<Hooks["experimental.chat.system.transform"]>>[1]} SystemOutput */
/** @typedef {(...args: any[]) => Promise<void>} AnyHook */
/** @typedef {import("@opencode/plugin").Plugin.Context} Context2 */
/** @typedef {Parameters<Parameters<Context2["tool"]["hook"]>[1]>[0]} ToolEvent2 */
/** @typedef {Extract<ToolEvent2, { status: "completed" }>["result"]} Result2 */
/** @typedef {Extract<ToolEvent2, { status: string }>} AfterEvent2 */
/** @typedef {{ name: string, status: { status: string } }} McpServer2 */
/** @typedef {Exclude<Result2["content"], string | undefined>[number]} Content2 */

/** The share of the time the run had when the clock loaded that it warns in: its last fifth. */
const SHARE = 5;
/** The most seconds before the deadline the clock warns from, however long the run. */
const MOST_SECONDS = 600;
/** What every line of canopy's starts with, as the prompts name it. */
const MARK = "[canopy]";
/** A run that keeps progress, as CANOPY_RUN_ID names it: a worker's or a planner's id, a review's, `review-7`, or a
 * task's, `task-3`. */
const CARD_RUN = /^(?:review-|task-)?[0-9]{1,18}$/;
/** One whose progress may ask the operator a question: any of those but a task's, which asks in its final line. */
const ASKING_RUN = /^(?:review-)?[0-9]{1,18}$/;
/** canopy's tool that posts an update of the run's progress, as the runtime names it. */
const STATUS_TOOL = "canopy_run_status";
/** How many tool calls a session makes before its first `status` call, before the nudge asks for one. */
const FIRST_CALLS = 8;
/** How many tool calls a session makes with no `status` call after its first, and after each time the nudge asked,
 * before the nudge asks again. */
const STALE_CALLS = 20;
/** The path of a worker's copy of its plan, as CANOPY_PLAN names it: absolute, on one line, and not too long. */
const PLAN_PATH = /^\/[^\x00-\x1f\x7f]{0,4095}$/;
/** The most steps a `status` call may carry, and the longest title one may have, as canopy's server holds them. */
const MOST_STEPS = 40;
const MOST_TITLE = 200;
/** The file in a run's answers directory that holds the operator's latest answer. */
const ANSWER_FILE = "answer.json";
/** The file in it that asks the agent to wrap up. */
const WRAP_UP_FILE = "wrap_up.json";
/** The most of a file in it that is read: one longer is not canopy's. */
const FILE_BYTES = 4096;
/** The wrap-up's line, which the file asks for. */
const WRAP_UP =
    `${MARK} The operator stopped this ticket and asks you to wrap up now: finish what keeps your work (commit and` +
    " push it, or record your decisions), start nothing new, then print your result line, its summary naming what" +
    " remains.";
/** The letter of a question's option. */
const LETTER = /^[A-E]$/;
/** The shell tool, as OpenCode 1 names it and as OpenCode 2 does. */
const SHELL_TOOLS = new Set(["bash", "shell"]);
/**
 * A command's leading `cd` and the `&&` after it: its directory written plainly, in single quotes, or in double quotes
 * with nothing the shell would expand, and the space after the `&&`, a newline included.
 */
const LEADING_CD = /^\s*cd[ \t]+(?:([\w./@%+=:,][\w./@%+=:,-]*)|'([^'\n]*)'|"([^"$`\\\n]*)")[ \t]*&&\s*/;
/** The longest a session's first prompt waits on MCP servers still connecting, in milliseconds. */
const MCP_WAIT_MS = 30_000;
/** The longest it waits, once none is connecting, for a connected server's tools to be registered. */
const MCP_SETTLE_MS = 2_000;
/** How often it asks the runtime again while it waits. */
const MCP_POLL_MS = 50;
/** The tag of the error OpenCode 2 fails a call with when the run's permission rules refuse it. */
const BLOCKED = "Permission.BlockedError";
/** The most of a refused call's resources the reason names, and the longest each is named, in characters. */
const MOST_RESOURCES = 3;
const MOST_RESOURCE = 200;
/** What the reason adds for a permission whose refusal says more than the line every refusal ends with. */
const REFUSED = new Map([
    ["external_directory", "It is outside the directories this run may reach."],
    ["webfetch", "This agent has no web tools."],
    ["websearch", "This agent has no web tools."],
    ["codesearch", "This agent has no web tools."],
    ["execute", "This agent has no code mode, which can reach the web."],
    ["task", "This agent starts no subagents."],
]);
/**
 * Where OpenCode 1's environment starts in its system prompt, right after the agent's body: the newline that joins
 * them, the line naming the model, and the head of `<env>`, whose working directory is the first thing two runs of one
 * agent differ by.
 */
const ENVIRONMENT = new RegExp(
    "\nYou are powered by the model named [^\n]*\n" +
        "Here is some useful information about the environment you are running in:\n" +
        "<env>\n  Working directory: ",
);

/**
 * Each job the plugin does, in the order its hooks run: a function that returns its hooks, by the runtime's names.
 *
 * @type {Array<() => Hooks>}
 */
const JOBS = [clock, split, nudge, answer, workdir, wrapUp];

/**
 * The plugin, as each major version of OpenCode reads it: its id, and its entry point for each.
 *
 * @type {import("@opencode-ai/plugin").PluginModule & import("@opencode/plugin").Plugin.Plugin}
 */
export default { id: "canopy", server: async () => hooksOfJobs(), setup };

/**
 * Every job's hooks, by OpenCode 1's names, joined so that each hook the runtime calls runs each job's in turn.
 *
 * @returns {Hooks}
 */
function hooksOfJobs() {
    /** @type {Record<string, AnyHook[]>} */
    const hooks = {};
    for (const job of JOBS) {
        let own;
        try {
            own = job();
        } catch {
            continue;
        }
        for (const [name, hook] of Object.entries(own)) {
            (hooks[name] ??= []).push(/** @type {AnyHook} */ (hook));
        }
    }
    return /** @type {Hooks} */ (Object.fromEntries(Object.entries(hooks).map(([name, each]) => [name, joined(each)])));
}

/**
 * OpenCode 2's entry point: the jobs' hooks, each registered under 2's name for it.
 *
 * 2 hands `execute.before` each call's input, which a job changes in place, as 1 hands it `args`. 2 hands
 * `execute.after` every call, failed ones too, with the result as the tool returned it; it truncates the
 * result after the hook, keeping its head, whatever the tool. So the jobs get each successful call's result as 1 hands
 * them an MCP tool's, its content as a list (`contentOf`), and the hook puts that list back only when a job changed it.
 * A failed call reaches them with no result, so the nudge counts it and no job writes to it. One the permission rules
 * refused is first explained (`explain`), as 1 has no hook to.
 *
 * @param {Context2} ctx
 * @returns {Promise<void>}
 */
async function setup(ctx) {
    await ctx.session.hook("prompt", mcpTools(ctx));
    const hooks = hooksOfJobs();
    const before = hooks["tool.execute.before"];
    if (before !== undefined) {
        await ctx.tool.hook("execute.before", async (event) => {
            try {
                // 2 hands the hook the call's input to change, as 1 hands it `args`.
                await before({ tool: event.tool, sessionID: event.sessionID, callID: event.id }, { args: event.input });
            } catch {
                // A hook that throws refuses the call.
            }
        });
    }
    const after = hooks["tool.execute.after"];
    await ctx.tool.hook("execute.after", async (event) => {
        try {
            explain(event);
        } catch {
            // The refusal is told as the runtime words it, and the jobs still run.
        }
        if (after === undefined) {
            return;
        }
        try {
            const input = { tool: event.tool, sessionID: event.sessionID, callID: event.id, args: event.input };
            if (event.status !== "completed") {
                // A failed call has no result a job may write to, but the nudge counts it.
                await after(input, /** @type {any} */ (null));
                return;
            }
            const content = contentOf(event.result);
            const before = content.length;
            await after(input, /** @type {any} */ ({ content }));
            if (content.length !== before) {
                event.result = { ...event.result, content };
            }
        } catch {
            // A hook that throws fails the call it runs after.
        }
    });
}

/**
 * OpenCode 2's job of its own: the hook that holds a session's first prompt until its MCP servers' tools register.
 *
 * 2 connects a session's MCP servers as it starts, and registers a server's tools only after the server connects; the
 * first model call is sent the tools registered when it is made, so without the wait it is sent none of them, and the
 * overseer, which acts only through canopy's MCP tools (DESIGN §27), would have nothing to call. The prompt hook runs
 * before that call, and 2 waits on it. It waits while a server is still connecting, at most `MCP_WAIT_MS`, then while
 * a connected server has no tool registered, at most `MCP_SETTLE_MS` more, since a server may have none; then the
 * prompt goes on, as it would have. It reads the servers' names and states and the tools' names, and changes nothing.
 * Later prompts wait for nothing.
 *
 * @param {Context2} ctx
 * @returns {() => Promise<void>}
 */
function mcpTools(ctx) {
    let waited = false;
    return async () => {
        if (waited) {
            return;
        }
        waited = true;
        try {
            await untilRegistered(ctx);
        } catch {
            // A hook that throws fails the prompt; without the wait, it goes on as it would have.
        }
    };
}

/**
 * Wait until no MCP server is connecting and each connected one has a tool registered, or the time is up.
 *
 * A server's tools are registered under its name, each character but a letter, a digit, `_`, and `-` made `_`, then
 * `_` and the tool's name, as OpenCode 2 names them.
 *
 * @param {Context2} ctx
 * @returns {Promise<void>}
 */
async function untilRegistered(ctx) {
    const start = Date.now();
    let settling = null;
    while (Date.now() - start < MCP_WAIT_MS) {
        /** @type {readonly McpServer2[]} */
        const servers = (await ctx.mcp.list()).data;
        const ids = (await ctx.tool.list()).map((tool) => tool.id);
        const connecting = servers.some((server) => server.status.status === "pending");
        const unregistered = servers.some(
            (server) =>
                server.status.status === "connected" &&
                !ids.some((id) => id.startsWith(`${server.name.replace(/[^a-zA-Z0-9_-]/g, "_")}_`)),
        );
        if (!connecting && !unregistered) {
            return;
        }
        if (!connecting) {
            settling ??= Date.now();
            if (Date.now() - settling >= MCP_SETTLE_MS) {
                return;
            }
        }
        await new Promise((resolve) => setTimeout(resolve, MCP_POLL_MS));
    }
}

/**
 * OpenCode 2's job of its own: tell an agent why a call was refused, in the reason the runtime tells it.
 *
 * 2 fails a call its permission rules refuse with a `Permission.BlockedError` inside the call's error, and tells the
 * agent that error's reason, or, with none, `Permission denied:` and the permission alone: not what it asked for, nor
 * that the refusal is meant. An agent told only that tries the same another way, through another command or tool, and
 * spends its run on it. So the job sets the reason to the runtime's own words, the resources the call asked for, and
 * one line of canopy's: that the rules refuse it on purpose, not to try it another way, and to say in the result line
 * what remains if the work cannot go on without it. It changes nothing else of the error, so the call stays refused as
 * the runtime refused it, and leaves an error of any other kind, or one already explained, as it is. A rule the
 * repository or the operator set (TRUST_MODEL T7) is explained as canopy's are: the line names the rules the run is
 * under, not whose they are. OpenCode 1 tells the agent the rules that refused it, and has no hook after a call that
 * fails (§33), so it is 2's alone.
 *
 * @param {AfterEvent2} event
 * @returns {void}
 */
function explain(event) {
    if (event.status !== "error") {
        return;
    }
    const blocked = /** @type {unknown} */ (event.error.error);
    if (blocked === null || typeof blocked !== "object" || !("_tag" in blocked) || blocked._tag !== BLOCKED) {
        return;
    }
    const refused = /** @type {{ message?: unknown, permission?: unknown, resources?: unknown, reason?: unknown }} */ (
        blocked
    );
    const said = typeof refused.message === "string" ? refused.message : "Permission denied.";
    if (said.includes(MARK)) {
        return;
    }
    const permission = typeof refused.permission === "string" ? refused.permission : "";
    refused.reason = `${said}${askedFor(refused.resources)}\n${refusal(permission)}`;
}

/**
 * What a refused call asked for, as the reason names it: up to `MOST_RESOURCES` of its resources, each on one line and
 * cut at `MOST_RESOURCE` characters, or nothing when it names none but the wildcard an MCP tool's call asks for.
 *
 * @param {unknown} resources
 * @returns {string}
 */
function askedFor(resources) {
    if (!Array.isArray(resources)) {
        return "";
    }
    const named = resources
        .filter((resource) => typeof resource === "string" && resource !== "" && resource !== "*")
        .map((resource) => {
            const line = oneLine(resource);
            return line.length > MOST_RESOURCE ? `${line.slice(0, MOST_RESOURCE)}…` : line;
        });
    if (named.length === 0) {
        return "";
    }
    const more = named.length > MOST_RESOURCES ? `, and ${named.length - MOST_RESOURCES} more` : "";
    return ` (${named
        .slice(0, MOST_RESOURCES)
        .map((resource) => `\`${resource}\``)
        .join(", ")}${more})`;
}

/**
 * canopy's line on a refusal of `permission`: what that permission's refusal means, when it says more, and what every
 * refusal asks of the agent.
 *
 * @param {string} permission
 * @returns {string}
 */
function refusal(permission) {
    const means = REFUSED.get(permission);
    return (
        `${MARK} ${means === undefined ? "" : `${means} `}The rules this run is under refuse it on purpose; it is not` +
        " a fault to fix. Do not try it another way, through another command, a script, or another tool. If your" +
        " work cannot go on without it, finish what you can and say what remains in your result line."
    );
}

/**
 * A result's content as OpenCode 2 sends it to the model: a string as one text, a list as it is, and, without either,
 * the output as text, a string as it is and anything else as JSON.
 *
 * @param {Result2} result
 * @returns {Content2[]}
 */
function contentOf(result) {
    const { content, output } = result;
    if (typeof content === "string") {
        return [{ type: "text", text: content }];
    }
    if (content !== undefined && content.length > 0) {
        return [...content];
    }
    let text;
    try {
        text = typeof output === "string" ? output : (JSON.stringify(output) ?? String(output));
    } catch {
        text = String(output);
    }
    return [{ type: "text", text }];
}

/**
 * One hook that runs each job's in turn, each in its own try: a hook that throws must not fail the call.
 *
 * @param {AnyHook[]} each
 * @returns {AnyHook}
 */
function joined(each) {
    return async (...args) => {
        for (const hook of each) {
            try {
                await hook(...args);
            } catch {
                // The next job's hook still runs.
            }
        }
    };
}

/**
 * The clock's hooks: the one that tells a tool call's result the minutes left, or none without a deadline.
 *
 * It counts the warning's start from its own load, at the session's start, so it needs no second variable.
 *
 * @returns {Hooks} The clock's hooks.
 */
function clock() {
    const deadline = readDeadline();
    if (deadline === null) {
        return {};
    }
    const loaded = Date.now() / 1000;
    const warnFrom = deadline - Math.min(Math.max(deadline - loaded, 0) / SHARE, MOST_SECONDS);
    /** @type {Set<string | undefined>} */
    const warned = new Set();
    return {
        /**
         * @param {AfterInput | undefined} input
         * @param {BuiltinResult | McpResult | null | undefined} output
         */
        "tool.execute.after": async (input, output) => {
            const now = Date.now() / 1000;
            if (now < warnFrom) {
                return;
            }
            const session = input?.sessionID;
            if (tell(output, line(deadline - now, !warned.has(session)))) {
                warned.add(session);
            }
        },
    };
}

/**
 * The deadline in Unix seconds, or null when the variable is unset or not a whole number of seconds.
 *
 * @returns {number | null}
 */
function readDeadline() {
    const raw = process.env.CANOPY_DEADLINE;
    if (typeof raw !== "string" || !/^[0-9]{1,15}$/.test(raw)) {
        return null;
    }
    return Number(raw);
}

/**
 * The line for `left` seconds before the deadline: the minutes left, and the first time, what to do with them.
 *
 * @param {number} left
 * @param {boolean} first
 * @returns {string}
 */
function line(left, first) {
    const minutes = Math.floor(left / 60);
    const amount = minutes < 1 ? "less than a minute" : minutes === 1 ? "1 minute" : `${minutes} minutes`;
    const said = `${MARK} ${amount} left before canopy stops this run.`;
    if (!first) {
        return said;
    }
    return (
        `${said} Wrap up now: finish what keeps your work (commit and push it, or record your decisions), then print` +
        " your result line."
    );
}

/**
 * Add `text` to a tool call's result, in place, and return whether it could.
 *
 * An MCP tool's result is truncated after the hook keeping its head, so the line goes first in its `content`. A
 * built-in tool's goes after its `output`. A result of any other shape, whatever its type says, is left as it is.
 *
 * @param {unknown} output
 * @param {string} text
 * @returns {boolean}
 */
function tell(output, text) {
    if (output === null || typeof output !== "object") {
        return false;
    }
    if ("content" in output && Array.isArray(output.content)) {
        output.content.unshift({ type: "text", text });
        return true;
    }
    if ("output" in output && typeof output.output === "string") {
        const before = output.output;
        output.output = before === "" || before.endsWith("\n") ? `${before}${text}` : `${before}\n${text}`;
        return true;
    }
    return false;
}

/**
 * The split's hooks: the one that cuts OpenCode 1's system prompt in two, the agent's body and all after it.
 *
 * OpenCode 1 joins the body, the environment, the instructions, the MCP servers' instructions, and the skills into one
 * system message, and the provider caches at the end of the first two system messages only; so with one, the cached
 * prefix ends past the working directory, and two runs in two directories share none of it, not even the tools before
 * it (MEASUREMENTS 2026-10-19, F47 and F48). Two messages give the body a breakpoint of its own (F50). OpenCode keeps
 * the array it hands the hook, not the object around it, so the hook changes that array in place; and the two parts
 * joined by a newline, as a provider that takes one system string joins them, are the prompt as it was. A prompt in
 * which the environment cannot be found, or one already in parts, is left as it is. OpenCode 2 builds its request
 * otherwise, unmeasured, and `setup` registers nothing for this hook. Under the sandbox the shell tool's description
 * names each run's own temporary directory, so no two sandboxed runs share even the tools, and the split gains them
 * nothing until that path is stable (§33, Open).
 *
 * @returns {Hooks} The split's hooks.
 */
function split() {
    return {
        /**
         * @param {unknown} _input
         * @param {SystemOutput | null | undefined} output
         */
        "experimental.chat.system.transform": async (_input, output) => {
            const system = output?.system;
            if (!Array.isArray(system) || system.length !== 1 || typeof system[0] !== "string") {
                return;
            }
            const text = system[0];
            const at = text.search(ENVIRONMENT);
            if (at <= 0) {
                return;
            }
            system.splice(0, 1, text.slice(0, at), text.slice(at + 1));
        },
    };
}

/**
 * The steps a session last reported working and next, by the titles it gave them, either null when it reported none.
 *
 * @typedef {{ working: string | null, next: string | null }} Reported
 */

/**
 * The nudge's hooks: the one that asks for an update once a session has gone a while without one.
 *
 * A worker, a planner, a reviewer, or a task's worker keeps its progress, where its work stands, for the operator
 * (DESIGN §41), through canopy's `status` tool; one that forgets leaves the operator progress that says less each call,
 * or none at all. The nudge counts each session's tool calls since its last successful `status` call, or since it
 * started, and adds one line to a call's result asking for an update, the way the clock adds its line, so the agent
 * hears it between calls and never mid-thought: at `FIRST_CALLS` for a session that has posted none yet, so the
 * operator hears early what the work is, and at `STALE_CALLS` after its last. An agent that goes on without one is
 * asked again each `STALE_CALLS` calls after. It keeps, per session, the count, whether it has updated, and when it
 * last asked, and in a run that follows a plan the two steps below, and nothing else; in any other run, as
 * CANOPY_RUN_ID names it, it has no hook.
 *
 * A worker that follows an approved plan is told once, in its prompt, to take its steps from it (DESIGN §25); canopy
 * names its copy of the plan in CANOPY_PLAN. There the line also names that file, and the steps the session's last
 * successful `status` call reported working and next, by the titles it gave them, so the plan is restated through a
 * long run rather than read once. The line carries canopy's own words and the titles the worker itself reported, and a
 * forged one could only restate a step, so it fails safe as the ask does.
 *
 * @returns {Hooks} The nudge's hooks.
 */
function nudge() {
    const run = process.env.CANOPY_RUN_ID;
    if (typeof run !== "string" || !CARD_RUN.test(run)) {
        return {};
    }
    /** @type {Map<string | undefined, number>} */
    const since = new Map();
    /** @type {Set<string | undefined>} */
    const updated = new Set();
    /** @type {Map<string | undefined, number>} */
    const askedAt = new Map();
    const raw = process.env.CANOPY_PLAN;
    const plan = typeof raw === "string" && PLAN_PATH.test(raw) ? raw : null;
    /** @type {Map<string | undefined, Reported>} */
    const reported = new Map();
    return {
        /**
         * @param {AfterInput | undefined} input
         * @param {BuiltinResult | McpResult | null | undefined} output
         */
        "tool.execute.after": async (input, output) => {
            const session = input?.sessionID;
            // A `status` call the server refused, which has no result, leaves the last update as old as it was.
            if (input?.tool === STATUS_TOOL && output !== null && output !== undefined) {
                since.delete(session);
                askedAt.delete(session);
                updated.add(session);
                if (plan !== null) {
                    reported.set(session, stepsOf(input.args));
                }
                return;
            }
            const calls = (since.get(session) ?? 0) + 1;
            since.set(session, calls);
            const first = !updated.has(session);
            const last = askedAt.get(session);
            const due = last === undefined ? calls >= (first ? FIRST_CALLS : STALE_CALLS) : calls - last >= STALE_CALLS;
            if (due && tell(output, stale(calls, first) + planned(plan, reported.get(session)))) {
                askedAt.set(session, calls);
            }
        },
    };
}

/**
 * The nudge's line, after `calls` tool calls with no `status` call, `first` when the session has made none yet.
 *
 * @param {number} calls
 * @param {boolean} first
 * @returns {string}
 */
function stale(calls, first) {
    const lapse = first ? `${calls} tool calls and no update yet` : `${calls} tool calls since your last update`;
    return `${MARK} ${lapse}: call ${STATUS_TOOL} with where your work stands now, then go on.`;
}

/**
 * What the nudge's line adds in a run that follows a plan: the plan's file, and the steps last reported, if any; in
 * any other run, nothing.
 *
 * @param {string | null} plan
 * @param {Reported | undefined} steps
 * @returns {string}
 */
function planned(plan, steps) {
    if (plan === null) {
        return "";
    }
    const said = [];
    if (steps?.working) {
        said.push(`step "${steps.working}" working`);
    }
    if (steps?.next) {
        said.push(`step "${steps.next}" next`);
    }
    if (said.length === 0) {
        return ` Your plan is \`${plan}\`: take your steps from it.`;
    }
    return ` Your plan is \`${plan}\`; your last update had ${said.join(" and ")}.`;
}

/**
 * The steps a `status` call's arguments report working and next: the first step working, and the first not started
 * after it, or the first not started when none is working. A call whose steps canopy's server would refuse, too many
 * or a title too long, reports none, and a title is one line, as the server makes it.
 *
 * @param {unknown} args
 * @returns {Reported}
 */
function stepsOf(args) {
    /** @type {Reported} */
    const none = { working: null, next: null };
    const steps = args !== null && typeof args === "object" && "steps" in args ? args.steps : undefined;
    if (!Array.isArray(steps) || steps.length > MOST_STEPS) {
        return none;
    }
    /** @type {Array<{ title: string, status: unknown }>} */
    const found = [];
    for (const step of steps) {
        const title = step !== null && typeof step === "object" ? step.title : undefined;
        if (typeof title !== "string" || title.length > MOST_TITLE) {
            return none;
        }
        found.push({ title: oneLine(title), status: step.status });
    }
    const at = found.findIndex((step) => step.status === "working");
    const next = found.find((step, index) => index > at && step.status === "not_started");
    return { working: found[at]?.title || null, next: next?.title || null };
}

/**
 * A title as one line, as canopy's server makes each line of an update: what is not printable made a space, and the
 * spaces collapsed.
 *
 * @param {string} title
 * @returns {string}
 */
function oneLine(title) {
    return title.replace(/\p{C}/gu, " ").split(/\s+/u).filter(Boolean).join(" ");
}

/**
 * The answer's hooks: the one that tells a tool call's result the operator's answer to the question the run asks.
 *
 * A worker, a planner, or a reviewer may ask the operator a question in its progress, with lettered options, and work
 * around it meanwhile (DESIGN §41). canopy writes the operator's answer, a letter, to a file in the run's answers
 * directory, which CANOPY_ANSWERS names and a sandboxed run may read but not write. After each tool call, the job
 * reads that file and, for an answer this session has not been told, adds one line to the call's result, the way the
 * clock adds its line, so the agent hears it between calls. A later answer, to the same question or another, is told
 * in turn. It keeps what it last told each session, and nothing else; without the variable, or in a run whose progress
 * asks nothing, it has no hook. A file it cannot read, or that is not an answer, tells nothing.
 *
 * @returns {Hooks} The answer's hooks.
 */
function answer() {
    const file = answersFile(ANSWER_FILE);
    if (file === null) {
        return {};
    }
    /** @type {Map<string | undefined, string>} */
    const told = new Map();
    return {
        /**
         * @param {AfterInput | undefined} input
         * @param {BuiltinResult | McpResult | null | undefined} output
         */
        "tool.execute.after": async (input, output) => {
            const said = answerLine(await readOwn(file));
            const session = input?.sessionID;
            if (said !== null && told.get(session) !== said && tell(output, said)) {
                told.set(session, said);
            }
        },
    };
}

/**
 * The path of the file `name` in the run's answers directory, or null in a run that has none: without CANOPY_ANSWERS,
 * or in a run whose progress asks nothing, as CANOPY_RUN_ID names it.
 *
 * @param {string} name
 * @returns {string | null}
 */
function answersFile(name) {
    const dir = process.env.CANOPY_ANSWERS;
    const run = process.env.CANOPY_RUN_ID;
    if (typeof dir !== "string" || !dir.startsWith("/") || typeof run !== "string" || !ASKING_RUN.test(run)) {
        return null;
    }
    return `${dir.replace(/\/+$/, "")}/${name}`;
}

/**
 * The text of a file canopy writes in the answers directory, or null when there is none to read, or it is too long to
 * be canopy's.
 *
 * @param {string} file
 * @returns {Promise<string | null>}
 */
async function readOwn(file) {
    try {
        const { readFile } = await import("node:fs/promises");
        const text = await readFile(file, "utf8");
        return text.length <= FILE_BYTES ? text : null;
    } catch {
        return null;
    }
}

/**
 * The line that tells the agent the answer in `text`, or null when `text` is no answer canopy writes.
 *
 * @param {string | null} text
 * @returns {string | null}
 */
function answerLine(text) {
    if (text === null) {
        return null;
    }
    let found;
    try {
        found = JSON.parse(text);
    } catch {
        return null;
    }
    if (found === null || typeof found !== "object") {
        return null;
    }
    const { ask, letter, option } = found;
    if (typeof ask !== "string" || typeof option !== "string" || typeof letter !== "string" || !LETTER.test(letter)) {
        return null;
    }
    return (
        `${MARK} The operator answers your question "${ask}": ${letter}, ${option}. Go on with it, and drop the` +
        " question from your next update."
    );
}

/**
 * The directory's hooks: the one that moves a shell command's leading `cd` into the call's working directory.
 *
 * Each shell call starts in the agent's directory, and the runtime checks every `cd` in it from there, not from where
 * an earlier `cd` in the same command went; so `cd app && cd ../lib`, which stays inside, is refused as leaving it, and
 * the refusal does not say why. A command that opens with `cd <dir> &&` runs the rest in that directory, as one with
 * that working directory does, so the job makes it one: it takes the leading `cd`s off the command and joins their
 * directories onto the call's working directory, and the runtime checks that directory, and the rest of the command
 * from it, as it checks any call's. So it reaches nothing the `cd` could not, and a `cd` out of the agent's directory
 * is refused as before. Only a directory written plainly moves, letters, digits, and `._/@%+=:,-`, or quoted with none
 * of `$`, `` ` ``, `\`, or a quote inside; anything else, `cd -`, `cd ~`, and a `cd` with an option among them, leaves
 * the command as it is. It reads and changes only the shell call's command and working directory.
 *
 * @returns {Hooks} The directory's hooks.
 */
function workdir() {
    return {
        /**
         * @param {{ tool?: string } | undefined} input
         * @param {{ args?: unknown } | undefined} output
         */
        "tool.execute.before": async (input, output) => {
            const args = output?.args;
            if (!SHELL_TOOLS.has(input?.tool ?? "") || args === null || typeof args !== "object") {
                return;
            }
            const call = /** @type {{ command?: unknown, workdir?: unknown }} */ (args);
            if (typeof call.command !== "string") {
                return;
            }
            const moved = leadingCd(call.command);
            if (moved === null) {
                return;
            }
            let dir = typeof call.workdir === "string" && call.workdir !== "" ? call.workdir : null;
            for (const each of moved.dirs) {
                dir = dir === null || each.startsWith("/") ? each : `${dir.replace(/\/+$/, "")}/${each}`;
            }
            call.command = moved.rest;
            call.workdir = dir;
        },
    };
}

/**
 * The directories of a command's leading `cd`s, each joined by `&&`, and the command after them, or null when it opens
 * with none the job moves, or nothing follows them.
 *
 * @param {string} command
 * @returns {{ dirs: string[], rest: string } | null}
 */
function leadingCd(command) {
    /** @type {string[]} */
    const dirs = [];
    let rest = command;
    for (let found = LEADING_CD.exec(rest); found !== null; found = LEADING_CD.exec(rest)) {
        const [whole, plain, single, double] = found;
        dirs.push(plain ?? single ?? double ?? "");
        rest = rest.slice(whole.length);
    }
    if (dirs.length === 0 || rest.trim() === "" || dirs.includes("")) {
        return null;
    }
    return { dirs, rest };
}

/**
 * The wrap-up's hooks: the one that asks the agent to wrap up, once the operator stops its ticket so.
 *
 * `canopy stop --wrap-up` stops a ticket and asks the run working it to end soon, keeping its work, rather than finish
 * all of it or be killed with what it has not pushed (DESIGN §22). canopy writes when it asked to a file in the run's
 * answers directory, as it writes an answer; after each tool call, the job reads that file and, for an ask this
 * session has not been told, adds one line to the call's result, the way the clock adds its line. It keeps when it
 * last told each session, and nothing else; without the variable, or in a run whose progress asks nothing, it has no
 * hook. A file it cannot read, or that is not canopy's, tells nothing. A forged one could only ask the agent to end
 * early, which leaves its work kept, so it fails safe as the clock's line does (§33).
 *
 * @returns {Hooks} The wrap-up's hooks.
 */
function wrapUp() {
    const file = answersFile(WRAP_UP_FILE);
    if (file === null) {
        return {};
    }
    /** @type {Map<string | undefined, string>} */
    const told = new Map();
    return {
        /**
         * @param {AfterInput | undefined} input
         * @param {BuiltinResult | McpResult | null | undefined} output
         */
        "tool.execute.after": async (input, output) => {
            const asked = askedAt(await readOwn(file));
            const session = input?.sessionID;
            if (asked !== null && told.get(session) !== asked && tell(output, WRAP_UP)) {
                told.set(session, asked);
            }
        },
    };
}

/**
 * When the wrap-up file in `text` was asked, as canopy writes it, or null when `text` is no ask of canopy's.
 *
 * @param {string | null} text
 * @returns {string | null}
 */
function askedAt(text) {
    if (text === null) {
        return null;
    }
    let found;
    try {
        found = JSON.parse(text);
    } catch {
        return null;
    }
    if (found === null || typeof found !== "object" || typeof found.asked !== "string" || found.asked === "") {
        return null;
    }
    return found.asked;
}
