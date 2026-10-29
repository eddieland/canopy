// The nudge, the plugin's job that asks a worker, planner, or reviewer for its card once it has gone a while without
// one (DESIGN §41), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's input and its result, which the hook changes in place.

import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const { default: canopy } = await import(pathToFileURL(plugin).href);

const STATUS = "canopy_run_status";
const ASKED =
    "[canopy] 20 tool calls since your last card: call canopy_run_status with where your work stands now, then go on.";

beforeEach(() => {
    delete process.env.CANOPY_DEADLINE;
    process.env.CANOPY_RUN_ID = "7";
});

afterEach(() => {
    delete process.env.CANOPY_RUN_ID;
});

/** A built-in tool's result, as its hook gets it. */
function builtin(text = "ok") {
    return { title: "bash", output: text, metadata: {} };
}

/** An MCP tool's result, as its hook gets it. */
function mcp(text = "ok") {
    return { content: [{ type: "text", text }] };
}

async function after(hooks, output, { tool = "bash", session = "ses_1" } = {}) {
    await hooks["tool.execute.after"]({ tool, sessionID: session, callID: "call_1", args: {} }, output);
    return output;
}

/** Make `count` tool calls in `session` whose results take no line. */
async function calls(hooks, count, session = "ses_1") {
    for (let n = 0; n < count; n++) {
        assert.equal((await after(hooks, builtin(), { session })).output, "ok");
    }
}

test("the 20th call with no card asks for one, after a built-in's output and first in an MCP tool's", async () => {
    const hooks = await canopy.server({});
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin("line\n"))).output, `line\n${ASKED}`);

    const other = await canopy.server({});
    await calls(other, 19);
    const result = await after(other, mcp("from the server"));
    assert.deepEqual(result.content, [
        { type: "text", text: ASKED },
        { type: "text", text: "from the server" },
    ]);
});

test("it asks once per lapse, and a status call starts the count again", async () => {
    const hooks = await canopy.server({});
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin())).output, `ok\n${ASKED}`);
    await calls(hooks, 30);
    await after(hooks, mcp(), { tool: STATUS });
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin())).output, `ok\n${ASKED}`);
});

test("each session counts its own calls", async () => {
    const hooks = await canopy.server({});
    await calls(hooks, 19, "ses_1");
    await calls(hooks, 19, "ses_2");
    await after(hooks, mcp(), { tool: STATUS, session: "ses_2" });
    assert.equal((await after(hooks, builtin(), { session: "ses_1" })).output, `ok\n${ASKED}`);
    assert.equal((await after(hooks, builtin(), { session: "ses_2" })).output, "ok");
});

test("a result that cannot take the line is asked again on the next call", async () => {
    const hooks = await canopy.server({});
    await calls(hooks, 19);
    await assert.doesNotReject(after(hooks, { output: 3 }));
    const said = (await after(hooks, builtin())).output;
    assert.equal(said, `ok\n${ASKED.replace("20 tool calls", "21 tool calls")}`);
});

test("a run that keeps no card, or names none, gets no nudge", async () => {
    for (const run of [undefined, "chore-2", "task-1", "try:build-health", "7x", "review-"]) {
        if (run === undefined) {
            delete process.env.CANOPY_RUN_ID;
        } else {
            process.env.CANOPY_RUN_ID = run;
        }
        const hooks = await canopy.server({});
        assert.equal(hooks["tool.execute.after"], undefined, String(run));
    }
    process.env.CANOPY_RUN_ID = "review-3";
    const reviewer = await canopy.server({});
    await calls(reviewer, 19);
    assert.equal((await after(reviewer, builtin())).output, `ok\n${ASKED}`);
});

test("under OpenCode 2, the line goes first in the result's content", async () => {
    /** @type {Record<string, (event: object) => Promise<void>>} */
    const tool = {};
    const registered = async () => ({ dispose: async () => {} });
    await canopy.setup({
        tool: {
            hook: async (name, callback) => {
                tool[name] = callback;
                return { dispose: async () => {} };
            },
            list: async () => [],
        },
        session: { hook: registered },
        mcp: { list: async () => ({ data: [] }) },
    });
    const event = (name, result) => ({
        tool: name,
        sessionID: "ses_1",
        agent: "a",
        messageID: "m",
        id: "call_1",
        input: {},
        status: "completed",
        result,
    });
    for (let n = 0; n < 19; n++) {
        const quiet = event("read", { output: "ok" });
        await tool["execute.after"](quiet);
        assert.deepEqual(quiet.result, { output: "ok" });
    }
    const asked = event("read", { output: "ok" });
    await tool["execute.after"](asked);
    assert.deepEqual(asked.result.content, [
        { type: "text", text: ASKED },
        { type: "text", text: "ok" },
    ]);
});
