// The message, the plugin's job that tells a worker, planner, or task's worker that a message from the operator waits
// (DESIGN §44), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's event, whose result the hook replaces when a job adds a line to it. canopy writes the messages
// and their mark to the run's answers directory, which the test writes as canopy would.

import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, test } from "node:test";
import path from "node:path";

import { failed, mcp, plugin, sent } from "./runtime.mjs";

const TOLD =
    "[canopy] The operator sent you a message while you work: call canopy_run_messages to read it, then go on as it" +
    " says.";
const WORDS = "Drop the web half of the ticket: only the parser.";

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

/** Send the run messages, up to the one numbered `newest`, as canopy writes them: their text, then the mark. */
async function messaged(newest) {
    const messages = [{ id: newest, at: "2026-11-06T10:00:00.000Z", text: WORDS }];
    await writeFile(path.join(answers, "messages.json"), JSON.stringify({ messages }) + "\n");
    await writeFile(path.join(answers, "message.json"), JSON.stringify({ newest }) + "\n");
}

test("no message yet tells nothing", async () => {
    const { after } = await plugin();
    assert.deepEqual(await sent(after), ["ok"]);
});

test("a message is told once a session, first in the result's content", async () => {
    const { after } = await plugin();
    await messaged(12);
    assert.deepEqual(await sent(after, { result: { output: "line\n" } }), [TOLD, "line\n"]);
    assert.deepEqual(await sent(after), ["ok"]);
    // Another session in the run hears of it too, once.
    assert.deepEqual(await sent(after, { session: "ses_2", result: mcp("from the server") }), [
        TOLD,
        "from the server",
    ]);
    assert.deepEqual(await sent(after, { session: "ses_2", result: mcp() }), ["ok"]);
    // A later message is told in turn.
    await messaged(14);
    assert.deepEqual(await sent(after), [TOLD, "ok"]);
});

test("the line carries none of the message's words, whatever the files hold", async () => {
    const { after } = await plugin();
    await messaged(12);
    await writeFile(path.join(answers, "message.json"), JSON.stringify({ newest: 12, text: WORDS }) + "\n");
    const told = await sent(after);
    assert.deepEqual(told, [TOLD, "ok"]);
    assert.ok(!told.join("\n").includes("parser"));
});

test("a failed call, with no result to tell, leaves the message for the next", async () => {
    const { after } = await plugin();
    await messaged(12);
    await after(failed());
    assert.deepEqual(await sent(after), [TOLD, "ok"]);
});

test("a file that is not canopy's mark tells nothing", async () => {
    const long = `{"newest": 3, "pad": "${"x".repeat(5000)}"}`;
    for (const text of ["", "not json", "null", "{}", '{"newest": 0}', '{"newest": "3"}', '{"newest": 1.5}', long]) {
        await writeFile(path.join(answers, "message.json"), text);
        assert.deepEqual(await sent((await plugin()).after), ["ok"], text.slice(0, 20));
    }
});

test("a task's run hears of one; a review's, a chore's, or one with no answers directory is told none", async () => {
    await messaged(12);
    process.env.CANOPY_RUN_ID = "task-3";
    assert.deepEqual(await sent((await plugin()).after), [TOLD, "ok"]);
    // A review's run keeps progress but takes no message; a chore's keeps none.
    for (const run of ["review-7", "chore-3"]) {
        process.env.CANOPY_RUN_ID = run;
        assert.deepEqual(await sent((await plugin()).after), ["ok"], run);
    }
    process.env.CANOPY_RUN_ID = "7";
    delete process.env.CANOPY_ANSWERS;
    assert.deepEqual(await sent((await plugin()).after), ["ok"]);
    process.env.CANOPY_ANSWERS = "relative/dir";
    assert.deepEqual(await sent((await plugin()).after), ["ok"]);
});
