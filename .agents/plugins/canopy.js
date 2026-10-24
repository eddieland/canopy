// canopy's plugin for a running agent: each job canopy asks of the agent process, as hooks the runtime calls. Its
// first job is the clock (DESIGN §33): near the end of the run's time, one line on each tool call's result tells the
// agent the minutes left before canopy stops the run, so it keeps its work before the kill. Its second is the split
// (§33): it cuts the system prompt after the agent's body, so that the tools and the body are a prefix the provider
// caches for the agent's unsandboxed runs, whatever directory each starts in; a sandboxed run's tools name its own
// temporary directory, so they share none. It is OpenCode 1's alone: 2 already caches the tools and the body apart from
// the environment, a sandboxed run's included.
//
// The agent runtime loads it from canopy's snapshot of its definitions, inside every agent process, sandboxed or not
// (TRUST_MODEL T4). So it is plain JavaScript with no imports, which loads with no network, and each job does as
// little as it can: it reads only what it is handed for that job (the clock, CANOPY_DEADLINE and the time; the split,
// the system prompt), changes only what its hook is handed, refuses no call, and grants no tool. Each job's hooks run
// in its own try, in the order of `JOBS`, so a job that throws neither fails a call that has already run nor keeps the
// jobs after it from theirs.
//
// Under OpenCode 2 it has one job more, its own: a session's first prompt waits until the tools of its MCP servers are
// registered, which 2 does only after the server connects, so that the first model call is sent them (`mcpTools`).
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
/** @typedef {{ name: string, status: { status: string } }} McpServer2 */
/** @typedef {Exclude<Result2["content"], string | undefined>[number]} Content2 */

/** The share of the time the run had when the clock loaded that it warns in: its last fifth. */
const SHARE = 5;
/** The most seconds before the deadline the clock warns from, however long the run. */
const MOST_SECONDS = 600;
/** What every line of canopy's starts with, as the prompts name it. */
const MARK = "[canopy]";
/** The longest a session's first prompt waits on MCP servers still connecting, in milliseconds. */
const MCP_WAIT_MS = 30_000;
/** The longest it waits, once none is connecting, for a connected server's tools to be registered. */
const MCP_SETTLE_MS = 2_000;
/** How often it asks the runtime again while it waits. */
const MCP_POLL_MS = 50;
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
const JOBS = [clock, split];

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
 * 2 hands `execute.after` every call, failed ones too, with the result as the tool returned it; it truncates the
 * result after the hook, keeping its head, whatever the tool. So the jobs get each successful call's result as 1 hands
 * them an MCP tool's, its content as a list (`contentOf`), and the hook puts that list back only when a job changed it.
 *
 * @param {Context2} ctx
 * @returns {Promise<void>}
 */
async function setup(ctx) {
    await ctx.session.hook("prompt", mcpTools(ctx));
    const after = hooksOfJobs()["tool.execute.after"];
    if (after === undefined) {
        return;
    }
    await ctx.tool.hook("execute.after", async (event) => {
        try {
            if (event.status !== "completed") {
                return;
            }
            const content = contentOf(event.result);
            const before = content.length;
            const input = { tool: event.tool, sessionID: event.sessionID, callID: event.id, args: event.input };
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
