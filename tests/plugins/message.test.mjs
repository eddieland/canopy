// The message, the plugin's job that tells a worker, planner, or task's worker that a message from the operator waits
// (DESIGN §44), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's input and its result, which the hook changes in place. canopy writes the messages and their mark
// to the run's answers directory, which the test writes as canopy would.

import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const { default: canopy } = await import(pathToFileURL(plugin).href);

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
async function sent(newest) {
    const messages = [{ id: newest, at: "2026-11-06T10:00:00.000Z", text: WORDS }];
    await writeFile(path.join(answers, "messages.json"), JSON.stringify({ messages }) + "\n");
    await writeFile(path.join(answers, "message.json"), JSON.stringify({ newest }) + "\n");
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

test("no message yet tells nothing", async () => {
    const hooks = await canopy.server({});
    assert.equal((await after(hooks, builtin())).output, "ok");
});

test("a message is told once a session, after a built-in's output and first in an MCP tool's", async () => {
    const hooks = await canopy.server({});
    await sent(12);
    assert.equal((await after(hooks, builtin("line\n"))).output, `line\n${TOLD}`);
    assert.equal((await after(hooks, builtin())).output, "ok");
    // Another session in the run hears of it too, once.
    assert.deepEqual((await after(hooks, mcp("from the server"), "ses_2")).content, [
        { type: "text", text: TOLD },
        { type: "text", text: "from the server" },
    ]);
    assert.deepEqual((await after(hooks, mcp(), "ses_2")).content, [{ type: "text", text: "ok" }]);
    // A later message is told in turn.
    await sent(14);
    assert.equal((await after(hooks, builtin())).output, `ok\n${TOLD}`);
});

test("the line carries none of the message's words, whatever the files hold", async () => {
    const hooks = await canopy.server({});
    await sent(12);
    await writeFile(path.join(answers, "message.json"), JSON.stringify({ newest: 12, text: WORDS }) + "\n");
    const told = (await after(hooks, builtin())).output;
    assert.equal(told, `ok\n${TOLD}`);
    assert.ok(!told.includes("parser"));
});

test("a failed call, with no result to tell, leaves the message for the next", async () => {
    const hooks = await canopy.server({});
    await sent(12);
    await after(hooks, null);
    assert.equal((await after(hooks, builtin())).output, `ok\n${TOLD}`);
});

test("a file that is not canopy's mark tells nothing", async () => {
    const long = `{"newest": 3, "pad": "${"x".repeat(5000)}"}`;
    for (const text of ["", "not json", "null", "{}", '{"newest": 0}', '{"newest": "3"}', '{"newest": 1.5}', long]) {
        await writeFile(path.join(answers, "message.json"), text);
        assert.equal((await after(await canopy.server({}), builtin())).output, "ok", text.slice(0, 20));
    }
});

test("a task's run hears of one; a review's, a chore's, or one with no answers directory is told none", async () => {
    await sent(12);
    process.env.CANOPY_RUN_ID = "task-3";
    assert.equal((await after(await canopy.server({}), builtin())).output, `ok\n${TOLD}`);
    // A review's run keeps progress, so the nudge has its hook, but takes no message.
    process.env.CANOPY_RUN_ID = "review-7";
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
    process.env.CANOPY_RUN_ID = "chore-3";
    assert.equal((await canopy.server({}))["tool.execute.after"], undefined);
    process.env.CANOPY_RUN_ID = "7";
    delete process.env.CANOPY_ANSWERS;
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
    process.env.CANOPY_ANSWERS = "relative/dir";
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
});
