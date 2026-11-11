// The answer, the plugin's job that tells a worker, planner, or reviewer the operator's answer to the question it asks
// (DESIGN §41), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's event, whose result the hook replaces when a job adds a line to it. canopy writes the answer to
// a file in the run's answers directory, which the test writes as canopy would.

import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, test } from "node:test";
import path from "node:path";

import { failed, mcp, plugin, sent } from "./runtime.mjs";

const ASK = "Keep the old endpoint for the mobile app, or remove it?";
const TOLD_B =
    `[canopy] The operator answers your question "${ASK}": B, remove it now. Go on with it, and drop the question` +
    " from your next update.";

let answers;

beforeEach(async () => {
    delete process.env.CANOPY_DEADLINE;
    answers = await mkdtemp(path.join(tmpdir(), "answers-"));
    process.env.CANOPY_RUN_ID = "7";
    process.env.CANOPY_ANSWERS = answers;
});

afterEach(async () => {
    delete process.env.CANOPY_RUN_ID;
    delete process.env.CANOPY_ANSWERS;
    await rm(answers, { recursive: true, force: true });
});

/** Write the operator's answer as canopy writes it. */
async function answered(letter, option, ask = ASK) {
    const data = { asked: "2026-10-29T10:00:00.000Z", ask, letter, option };
    await writeFile(path.join(answers, "answer.json"), JSON.stringify(data) + "\n");
}

test("no answer yet tells nothing", async () => {
    const { after } = await plugin();
    assert.deepEqual(await sent(after), ["ok"]);
});

test("an answer is told once, first in the result's content, and a new one again", async () => {
    const { after } = await plugin();
    await answered("B", "remove it now");
    assert.deepEqual(await sent(after, { result: { output: "line\n" } }), [TOLD_B, "line\n"]);
    assert.deepEqual(await sent(after), ["ok"]);
    // Another session in the run hears it too, once.
    assert.deepEqual(await sent(after, { session: "ses_2", result: mcp("from the server") }), [
        TOLD_B,
        "from the server",
    ]);
    // The operator changes their mind.
    await answered("A", "keep it, deprecated");
    assert.match((await sent(after))[0], /: A, keep it, deprecated\. Go on with it/);
});

test("a failed call, with no result to tell, leaves the answer for the next", async () => {
    const { after } = await plugin();
    await answered("B", "remove it now");
    await after(failed());
    assert.deepEqual(await sent(after), [TOLD_B, "ok"]);
});

test("a file that is no answer of canopy's tells nothing", async () => {
    const { after } = await plugin();
    for (const text of ["not json", "null", '{"ask": "a", "letter": "F", "option": "o"}', '{"letter": "A"}']) {
        await writeFile(path.join(answers, "answer.json"), text);
        assert.deepEqual(await sent(after), ["ok"]);
    }
    await writeFile(path.join(answers, "answer.json"), "x".repeat(5000));
    assert.deepEqual(await sent(after), ["ok"]);
});

test("a run whose progress asks nothing, or that names no answers directory, is told no answer", async () => {
    await answered("B", "remove it now");
    // A chore's run keeps no progress; a task's keeps it but asks nothing.
    for (const run of ["chore-3", "task-3"]) {
        process.env.CANOPY_RUN_ID = run;
        assert.deepEqual(await sent((await plugin()).after), ["ok"], run);
    }
    process.env.CANOPY_RUN_ID = "review-7";
    delete process.env.CANOPY_ANSWERS;
    assert.deepEqual(await sent((await plugin()).after), ["ok"]);
    process.env.CANOPY_ANSWERS = "relative/dir";
    assert.deepEqual(await sent((await plugin()).after), ["ok"]);
});
