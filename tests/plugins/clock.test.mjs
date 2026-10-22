// The clock, the first job of the plugin canopy ships for its agent runs (DESIGN §33), under Node's own test runner:
// `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's input and its result, which the hook changes in place.

import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const { default: canopy } = await import(pathToFileURL(plugin).href);
/** The plugin's hooks as OpenCode 1 gets them; `canopy.test.mjs` drives them through OpenCode 2's entry point too. */
const Canopy = canopy.server;

/** The time the run's clock starts at in these tests, in milliseconds. */
const START = 1_800_000_000_000;
const FIRST =
    " Wrap up now: finish what keeps your work (commit and push it, or record your decisions), then print your result" +
    " line.";

beforeEach(() => {
    mock.timers.enable({ apis: ["Date"], now: START });
    delete process.env.CANOPY_DEADLINE;
});

afterEach(() => {
    mock.timers.reset();
    delete process.env.CANOPY_DEADLINE;
});

/** Load the plugin for a run of `minutes`, its deadline that far from now. */
async function load(minutes) {
    process.env.CANOPY_DEADLINE = String(START / 1000 + minutes * 60);
    return Canopy({});
}

/** Move the clock to `seconds` after the run's start. */
function at(seconds) {
    mock.timers.setTime(START + seconds * 1000);
}

/** A built-in tool's result, as its hook gets it. */
function builtin(text = "ok") {
    return { title: "bash", output: text, metadata: {} };
}

/** An MCP tool's result, as its hook gets it. */
function mcp(text = "ok") {
    return { content: [{ type: "text", text }] };
}

async function after(hooks, output, session = "ses_1") {
    await hooks["tool.execute.after"]({ tool: "bash", sessionID: session, callID: "call_1", args: {} }, output);
    return output;
}

test("no line before the last fifth of the run", async () => {
    const hooks = await load(15);
    at(12 * 60 - 1);
    assert.equal((await after(hooks, builtin())).output, "ok");
    assert.deepEqual((await after(hooks, mcp())).content, [{ type: "text", text: "ok" }]);
});

test("the first line in a session names the minutes left and asks to wrap up", async () => {
    const hooks = await load(15);
    at(12 * 60);
    const said = "[canopy] 3 minutes left before canopy stops this run.";
    assert.equal((await after(hooks, builtin())).output, `ok\n${said}${FIRST}`);
});

test("later lines give only the minutes left, and a new session is warned in full", async () => {
    const hooks = await load(15);
    at(12 * 60);
    await after(hooks, builtin());
    at(13 * 60 + 30);
    assert.equal((await after(hooks, builtin())).output, "ok\n[canopy] 1 minute left before canopy stops this run.");
    at(14 * 60 + 1);
    const said = "[canopy] less than a minute left before canopy stops this run.";
    assert.equal((await after(hooks, builtin())).output, `ok\n${said}`);
    assert.equal((await after(hooks, builtin(), "ses_2")).output, `ok\n${said}${FIRST}`);
    // Past the deadline, before the kill lands.
    at(16 * 60);
    assert.equal((await after(hooks, builtin())).output, `ok\n${said}`);
});

test("a long run is warned in its last 10 minutes, not its last fifth", async () => {
    const hooks = await load(60);
    at(50 * 60 - 1);
    assert.equal((await after(hooks, builtin())).output, "ok");
    at(50 * 60);
    assert.match((await after(hooks, builtin())).output, /^ok\n\[canopy\] 10 minutes left /);
});

test("the line goes after a built-in tool's output, and first in an MCP tool's content", async () => {
    const hooks = await load(10);
    at(9 * 60);
    const said = "[canopy] 1 minute left before canopy stops this run.";
    assert.equal((await after(hooks, builtin("line\n"))).output, `line\n${said}${FIRST}`);
    assert.equal((await after(hooks, builtin(""))).output, said);
    const result = await after(hooks, mcp("from the server"));
    assert.deepEqual(result.content, [
        { type: "text", text: said },
        { type: "text", text: "from the server" },
    ]);
});

test("no throw on a result of either shape or none, and a session not warned until a line lands", async () => {
    const hooks = await load(10);
    at(9 * 60);
    const odd = [
        undefined,
        null,
        "text",
        {},
        { output: 3 },
        { content: "not a list" },
        Object.freeze({ output: "frozen" }),
        Object.freeze({ content: Object.freeze([]) }),
        {
            get output() {
                throw new Error("no output");
            },
        },
    ];
    for (const output of odd) {
        await assert.doesNotReject(hooks["tool.execute.after"]({ sessionID: "ses_1" }, output));
    }
    await assert.doesNotReject(hooks["tool.execute.after"](undefined, builtin()));
    // None of those took a line, so the session's first is still to come.
    const said = "[canopy] 1 minute left before canopy stops this run.";
    assert.equal((await after(hooks, builtin())).output, `ok\n${said}${FIRST}`);
});

test("nothing without the variable, or with one that is not a time", async () => {
    for (const value of [undefined, "", "soon", "-1", "1.5", "1e9"]) {
        if (value === undefined) {
            delete process.env.CANOPY_DEADLINE;
        } else {
            process.env.CANOPY_DEADLINE = value;
        }
        assert.deepEqual(await Canopy({}), {}, `CANOPY_DEADLINE=${value}`);
    }
});
