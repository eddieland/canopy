// A stand-in for the agent runtime, OpenCode, for the tests of the plugin canopy ships for its agent runs (DESIGN §33).
// It loads the plugin as the runtime does, through its `setup`, and hands back the hooks it registered, to be called
// with the events the runtime hands them. Each job's tests import it; it holds no test of its own, so `make
// test-plugin` does not run it.

import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const file = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");

/** The plugin's module, as the runtime imports it. */
export const module = await import(pathToFileURL(file).href);
/** The plugin: the module's default export. */
export const canopy = module.default;

/**
 * Load the plugin as the runtime does, with the run's environment as it is now, and return the hooks it registered.
 *
 * @param {object} [answers] what the runtime answers the plugin when it asks.
 * @param {() => Promise<{ data: object[] }>} [answers.servers] its MCP servers, each with its name and status.
 * @param {() => Promise<object[]>} [answers.tools] its registered tools, each with its id.
 * @returns the hook before a session's `prompt` goes on, the one `before` a tool call, the one `after` it, and the
 *     names of every hook `registered`, sorted.
 */
export async function plugin({ servers = async () => ({ data: [] }), tools = async () => [] } = {}) {
    /** @type {Record<string, (event?: object) => Promise<void>>} */
    const hooks = {};
    const hook = (domain) => async (name, callback) => {
        hooks[`${domain}.${name}`] = callback;
        return { dispose: async () => {} };
    };
    await canopy.setup({
        session: { hook: hook("session") },
        tool: { hook: hook("tool"), list: tools },
        mcp: { list: servers },
    });
    return {
        prompt: hooks["session.prompt"],
        before: hooks["tool.execute.before"],
        after: hooks["tool.execute.after"],
        registered: Object.keys(hooks).sort(),
    };
}

/** A call of `tool` in `session` with `input`, as the runtime hands the hook before it. */
export function call(tool = "shell", { session = "ses_1", input = {} } = {}) {
    return { tool, sessionID: session, agent: "canopy-worker", messageID: "msg_1", id: "call_1", input };
}

/** A call that completed with `result`, as the runtime hands the hook after it. */
export function completed(result, { tool, ...options } = {}) {
    return { ...call(tool, options), status: "completed", result };
}

/** A call that failed with `error`, as the runtime hands the hook after it: it has no result. */
export function failed(error = { _tag: "Tool.Error", message: "it failed" }, { tool, ...options } = {}) {
    return { ...call(tool, options), status: "error", error };
}

/** A result with the content an MCP tool returns, one text. */
export function mcp(text = "ok") {
    return { content: [{ type: "text", text }] };
}

/**
 * Run a call that completed with `result` through `after`, and return what the agent is sent of it: each text of its
 * content in order, so canopy's lines, which go first, then the tool's own.
 *
 * @param {(event: object) => Promise<void>} after the plugin's hook after a tool call.
 * @param {object} [of] the call: its `tool`, `session`, and `input`, and its `result`, a tool's output alone unless
 *     given.
 */
export async function sent(after, { result = { output: "ok" }, ...options } = {}) {
    const event = completed(result, options);
    await after(event);
    return texts(event.result);
}

/** The texts the runtime sends the model of `result`: its content's, or, with none, its output. */
export function texts(result) {
    const { content, output } = result;
    if (typeof content === "string") {
        return [content];
    }
    if (Array.isArray(content) && content.length > 0) {
        return content.map((part) => part.text);
    }
    return [typeof output === "string" ? output : JSON.stringify(output)];
}
