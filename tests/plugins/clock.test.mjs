// The clock, the first job of the plugin canopy ships for its agent runs (DESIGN §33), under Node's own test runner:
// `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's event, whose result the hook replaces when a job adds a line to it.

import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";

import { completed, failed, mcp, plugin, sent } from "./runtime.mjs";

/** The time the run's clock starts at in these tests, in milliseconds. */
const START = 1_800_000_000_000;
const FIRST =
    " Wrap up now: finish what keeps your work (commit and push it, or record your decisions), then report your" +
    " result.";

beforeEach(() => {
    mock.timers.enable({ apis: ["Date"], now: START });
    delete process.env.CANOPY_DEADLINE;
});

afterEach(() => {
    mock.timers.reset();
    delete process.env.CANOPY_DEADLINE;
});

/** Load the plugin for a run of `minutes`, its deadline that far from now, and return its hook after a tool call. */
async function load(minutes) {
    process.env.CANOPY_DEADLINE = String(START / 1000 + minutes * 60);
    return (await plugin()).after;
}

/** Move the clock to `seconds` after the run's start. */
function at(seconds) {
    mock.timers.setTime(START + seconds * 1000);
}

test("no line before the last fifth of the run", async () => {
    const after = await load(15);
    at(12 * 60 - 1);
    assert.deepEqual(await sent(after), ["ok"]);
    assert.deepEqual(await sent(after, { result: mcp() }), ["ok"]);
});

test("the first line in a session names the minutes left and asks to wrap up", async () => {
    const after = await load(15);
    at(12 * 60);
    const said = "[canopy] 3 minutes left before canopy stops this run.";
    assert.deepEqual(await sent(after), [`${said}${FIRST}`, "ok"]);
});

test("later lines give only the minutes left, and a new session is warned in full", async () => {
    const after = await load(15);
    at(12 * 60);
    await sent(after);
    at(13 * 60 + 30);
    assert.deepEqual(await sent(after), ["[canopy] 1 minute left before canopy stops this run.", "ok"]);
    at(14 * 60 + 1);
    const said = "[canopy] less than a minute left before canopy stops this run.";
    assert.deepEqual(await sent(after), [said, "ok"]);
    assert.deepEqual(await sent(after, { session: "ses_2" }), [`${said}${FIRST}`, "ok"]);
    // Past the deadline, before the kill lands.
    at(16 * 60);
    assert.deepEqual(await sent(after), [said, "ok"]);
});

test("a long run is warned in its last 10 minutes, not its last fifth", async () => {
    const after = await load(60);
    at(50 * 60 - 1);
    assert.deepEqual(await sent(after), ["ok"]);
    at(50 * 60);
    assert.match((await sent(after))[0], /^\[canopy\] 10 minutes left /);
});

test("the line goes first in a result's content, before the tool's own, whatever the tool", async () => {
    const after = await load(10);
    at(9 * 60);
    const said = "[canopy] 1 minute left before canopy stops this run.";
    assert.deepEqual(await sent(after, { result: { output: "line\n" } }), [`${said}${FIRST}`, "line\n"]);
    assert.deepEqual(await sent(after, { result: mcp("from the server") }), [said, "from the server"]);
});

test("a failed call, or a result that cannot be read, takes no line and warns no session", async () => {
    const after = await load(10);
    at(9 * 60);
    const failure = failed();
    await assert.doesNotReject(after(failure));
    assert.deepEqual(failure.error, { _tag: "Tool.Error", message: "it failed" });
    const unreadable = Object.defineProperty(completed({}), "result", {
        get() {
            throw new Error("no result");
        },
    });
    for (const event of [completed(undefined), completed(null), unreadable]) {
        await assert.doesNotReject(after(event));
    }
    // None of those took a line, so the session's first is still to come.
    const said = "[canopy] 1 minute left before canopy stops this run.";
    assert.deepEqual(await sent(after), [`${said}${FIRST}`, "ok"]);
});

test("nothing without the variable, or with one that is not a time", async () => {
    for (const value of [undefined, "", "soon", "-1", "1.5", "1e9"]) {
        if (value === undefined) {
            delete process.env.CANOPY_DEADLINE;
        } else {
            process.env.CANOPY_DEADLINE = value;
        }
        assert.deepEqual(await sent((await plugin()).after), ["ok"], `CANOPY_DEADLINE=${value}`);
    }
});
