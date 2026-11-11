// The nudge, the plugin's job that asks a worker, planner, or reviewer for an update once it has gone a while without
// one (DESIGN §41), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's event, whose result the hook replaces when a job adds a line to it.

import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { failed, mcp, plugin, sent } from "./runtime.mjs";

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

/** Make `count` tool calls in `session` whose results take no line. */
async function calls(after, count, session = "ses_1") {
    for (let n = 0; n < count; n++) {
        assert.deepEqual(await sent(after, { session }), ["ok"]);
    }
}

/** A session's first update, which the nudge asks for at its 8th call; any later one is asked for at the 20th. */
async function updates(after, session = "ses_1") {
    await sent(after, { tool: STATUS, session, result: mcp() });
}

test("the 8th call with no update yet asks for one, first in the result's content", async () => {
    const { after } = await plugin();
    await calls(after, 7);
    assert.deepEqual(await sent(after, { result: { output: "line\n" } }), [FIRST, "line\n"]);

    const other = (await plugin()).after;
    await calls(other, 7);
    assert.deepEqual(await sent(other, { result: mcp("from the server") }), [FIRST, "from the server"]);
});

test("after an update, the 20th call with no other asks for one", async () => {
    const { after } = await plugin();
    await updates(after);
    await calls(after, 19);
    assert.deepEqual(await sent(after), [ASKED, "ok"]);
});

test("it asks again each 20 calls it goes unanswered, and a status call starts the count again", async () => {
    const { after } = await plugin();
    await calls(after, 7);
    assert.deepEqual(await sent(after), [FIRST, "ok"]);
    await calls(after, 19);
    assert.deepEqual(await sent(after), [FIRST.replace("8 tool calls", "28 tool calls"), "ok"]);
    await updates(after);
    await calls(after, 19);
    assert.deepEqual(await sent(after), [ASKED, "ok"]);
    await calls(after, 19);
    assert.deepEqual(await sent(after), [ASKED.replace("20 tool calls", "40 tool calls"), "ok"]);
    await updates(after);
    await calls(after, 19);
    assert.deepEqual(await sent(after), [ASKED, "ok"]);
});

test("each session counts its own calls", async () => {
    const { after } = await plugin();
    await updates(after, "ses_1");
    await calls(after, 19, "ses_1");
    await calls(after, 7, "ses_2");
    await updates(after, "ses_2");
    assert.deepEqual(await sent(after, { session: "ses_1" }), [ASKED, "ok"]);
    assert.deepEqual(await sent(after, { session: "ses_2" }), ["ok"]);
});

test("a failed call, which has no result to take the line, leaves the ask for the next call", async () => {
    const { after } = await plugin();
    await calls(after, 7);
    await assert.doesNotReject(after(failed()));
    assert.deepEqual(await sent(after), [FIRST.replace("8 tool calls", "9 tool calls"), "ok"]);
});

test("a failed call counts toward the nudge, and a refused status call resets nothing", async () => {
    const { after } = await plugin();
    for (let n = 0; n < 6; n++) {
        await after(failed(undefined, { tool: "read" }));
    }
    await after(failed({ _tag: "Tool.Error", message: "refused" }, { tool: STATUS }));
    assert.deepEqual(await sent(after, { tool: "read" }), [FIRST, "ok"]);
});

test("a run that keeps no progress, or names none, gets no nudge; a review's and a task's do", async () => {
    for (const run of [undefined, "chore-2", "task-", "try:build-health", "7x", "review-"]) {
        if (run === undefined) {
            delete process.env.CANOPY_RUN_ID;
        } else {
            process.env.CANOPY_RUN_ID = run;
        }
        await calls((await plugin()).after, 9);
    }
    for (const run of ["review-3", "task-1"]) {
        process.env.CANOPY_RUN_ID = run;
        const { after } = await plugin();
        await calls(after, 7);
        assert.deepEqual(await sent(after), [FIRST, "ok"], run);
    }
});

/** A worker's update that reports `steps`, each `[title, status]`. */
async function reports(after, steps, session = "ses_1") {
    const input = { summary: "s", now: "n", steps: steps.map(([title, status]) => ({ title, status })) };
    await sent(after, { tool: STATUS, session, input, result: mcp() });
}

const COPY = "/work/slot/.canopy-plan.md";
const ONLY_FILE = ` Your plan is \`${COPY}\`: take your steps from it.`;

test("following a plan, the line names its file, and the steps last reported working and next", async () => {
    process.env.CANOPY_PLAN = COPY;
    try {
        const { after } = await plugin();
        await calls(after, 7);
        assert.deepEqual(await sent(after), [`${FIRST}${ONLY_FILE}`, "ok"]);
        await reports(after, [
            ["Add the endpoint", "done"],
            ["Wire the  button\n", "working"],
            ["Old tests", "skipped"],
            ["Write the tests", "not_started"],
            ["Docs", "not_started"],
        ]);
        await calls(after, 19);
        assert.deepEqual(await sent(after), [
            `${ASKED} Your plan is \`${COPY}\`; your last update had step "Wire the button" working and step` +
                ` "Write the tests" next.`,
            "ok",
        ]);
        // An update with none working names the first not started; one with no steps, the file alone.
        await reports(after, [["Write the tests", "not_started"]]);
        await calls(after, 19);
        const next = `${ASKED} Your plan is \`${COPY}\`; your last update had step "Write the tests" next.`;
        assert.deepEqual(await sent(after), [next, "ok"]);
        await reports(after, []);
        await calls(after, 19);
        assert.deepEqual(await sent(after), [`${ASKED}${ONLY_FILE}`, "ok"]);
    } finally {
        delete process.env.CANOPY_PLAN;
    }
});

test("each session's steps are its own, and steps the server would refuse are none", async () => {
    process.env.CANOPY_PLAN = COPY;
    try {
        const { after } = await plugin();
        await reports(after, [["Mine", "working"]], "ses_1");
        await reports(after, [["x".repeat(201), "working"]], "ses_2");
        await calls(after, 19, "ses_1");
        await calls(after, 19, "ses_2");
        const mine = `${ASKED} Your plan is \`${COPY}\`; your last update had step "Mine" working.`;
        assert.deepEqual(await sent(after, { session: "ses_1" }), [mine, "ok"]);
        assert.deepEqual(await sent(after, { session: "ses_2" }), [`${ASKED}${ONLY_FILE}`, "ok"]);
    } finally {
        delete process.env.CANOPY_PLAN;
    }
});

test("with no plan, or a path that is not one, the line names no plan and no steps", async () => {
    for (const plan of [undefined, "", "relative/.canopy-plan.md", "/two\nlines"]) {
        if (plan === undefined) {
            delete process.env.CANOPY_PLAN;
        } else {
            process.env.CANOPY_PLAN = plan;
        }
        const { after } = await plugin();
        await reports(after, [["Mine", "working"]]);
        await calls(after, 19);
        assert.deepEqual(await sent(after), [ASKED, "ok"], String(plan));
    }
    delete process.env.CANOPY_PLAN;
});
