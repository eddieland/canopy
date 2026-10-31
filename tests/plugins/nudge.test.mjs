// The nudge, the plugin's job that asks a worker, planner, or reviewer for an update once it has gone a while without
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
const TAIL = ": call canopy_run_status with where your work stands now, then go on.";
const FIRST = `[canopy] 8 tool calls and no update yet${TAIL}`;
const ASKED = `[canopy] 20 tool calls since your last update${TAIL}`;

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

/** A session's first update, which the nudge asks for at its 8th call; any later one is asked for at the 20th. */
async function updates(hooks, session = "ses_1") {
    await after(hooks, mcp(), { tool: STATUS, session });
}

test("the 8th call with no update yet asks for one, after a built-in's output and first in an MCP tool's", async () => {
    const hooks = await canopy.server({});
    await calls(hooks, 7);
    assert.equal((await after(hooks, builtin("line\n"))).output, `line\n${FIRST}`);

    const other = await canopy.server({});
    await calls(other, 7);
    const result = await after(other, mcp("from the server"));
    assert.deepEqual(result.content, [
        { type: "text", text: FIRST },
        { type: "text", text: "from the server" },
    ]);
});

test("after an update, the 20th call with no other asks for one", async () => {
    const hooks = await canopy.server({});
    await updates(hooks);
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin())).output, `ok\n${ASKED}`);
});

test("it asks again each 20 calls it goes unanswered, and a status call starts the count again", async () => {
    const hooks = await canopy.server({});
    await calls(hooks, 7);
    assert.equal((await after(hooks, builtin())).output, `ok\n${FIRST}`);
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin())).output, `ok\n${FIRST.replace("8 tool calls", "28 tool calls")}`);
    await updates(hooks);
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin())).output, `ok\n${ASKED}`);
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin())).output, `ok\n${ASKED.replace("20 tool calls", "40 tool calls")}`);
    await updates(hooks);
    await calls(hooks, 19);
    assert.equal((await after(hooks, builtin())).output, `ok\n${ASKED}`);
});

test("each session counts its own calls", async () => {
    const hooks = await canopy.server({});
    await updates(hooks, "ses_1");
    await calls(hooks, 19, "ses_1");
    await calls(hooks, 7, "ses_2");
    await updates(hooks, "ses_2");
    assert.equal((await after(hooks, builtin(), { session: "ses_1" })).output, `ok\n${ASKED}`);
    assert.equal((await after(hooks, builtin(), { session: "ses_2" })).output, "ok");
});

test("a result that cannot take the line is asked again on the next call", async () => {
    const hooks = await canopy.server({});
    await calls(hooks, 7);
    await assert.doesNotReject(after(hooks, { output: 3 }));
    const said = (await after(hooks, builtin())).output;
    assert.equal(said, `ok\n${FIRST.replace("8 tool calls", "9 tool calls")}`);
});

test("a run that keeps no progress, or names none, gets no nudge; a review's and a task's do", async () => {
    for (const run of [undefined, "chore-2", "task-", "try:build-health", "7x", "review-"]) {
        if (run === undefined) {
            delete process.env.CANOPY_RUN_ID;
        } else {
            process.env.CANOPY_RUN_ID = run;
        }
        const hooks = await canopy.server({});
        assert.equal(hooks["tool.execute.after"], undefined, String(run));
    }
    for (const run of ["review-3", "task-1"]) {
        process.env.CANOPY_RUN_ID = run;
        const hooks = await canopy.server({});
        await calls(hooks, 7);
        assert.equal((await after(hooks, builtin())).output, `ok\n${FIRST}`, run);
    }
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
    for (let n = 0; n < 7; n++) {
        const quiet = event("read", { output: "ok" });
        await tool["execute.after"](quiet);
        assert.deepEqual(quiet.result, { output: "ok" });
    }
    const asked = event("read", { output: "ok" });
    await tool["execute.after"](asked);
    assert.deepEqual(asked.result.content, [
        { type: "text", text: FIRST },
        { type: "text", text: "ok" },
    ]);
});

test("under OpenCode 2, a failed call counts toward the nudge, and a refused status call resets nothing", async () => {
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
    const call = { sessionID: "ses_1", agent: "a", messageID: "m", id: "call_1", input: {} };
    for (let n = 0; n < 6; n++) {
        await tool["execute.after"]({ ...call, tool: "read", status: "error", error: { message: "no" } });
    }
    await tool["execute.after"]({ ...call, tool: STATUS, status: "error", error: { message: "refused" } });
    const asked = { ...call, tool: "read", status: "completed", result: { output: "ok" } };
    await tool["execute.after"](asked);
    assert.deepEqual(asked.result.content, [
        { type: "text", text: FIRST },
        { type: "text", text: "ok" },
    ]);
});
