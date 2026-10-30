// The answer, the plugin's job that tells a worker, planner, or reviewer the operator's answer to the question it asks
// (DESIGN §41), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's input and its result, which the hook changes in place. canopy writes the answer to a file in the
// run's answers directory, which the test writes as canopy would.

import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const { default: canopy } = await import(pathToFileURL(plugin).href);

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

test("no answer yet tells nothing", async () => {
    const hooks = await canopy.server({});
    assert.equal((await after(hooks, builtin())).output, "ok");
});

test("an answer is told once, after a built-in's output and first in an MCP tool's, and a new one again", async () => {
    const hooks = await canopy.server({});
    await answered("B", "remove it now");
    assert.equal((await after(hooks, builtin("line\n"))).output, `line\n${TOLD_B}`);
    assert.equal((await after(hooks, builtin())).output, "ok");
    // Another session in the run hears it too, once.
    assert.deepEqual((await after(hooks, mcp("from the server"), "ses_2")).content, [
        { type: "text", text: TOLD_B },
        { type: "text", text: "from the server" },
    ]);
    // The operator changes their mind.
    await answered("A", "keep it, deprecated");
    assert.match((await after(hooks, builtin())).output, /: A, keep it, deprecated\. Go on with it/);
});

test("a failed call, with no result to tell, leaves the answer for the next", async () => {
    const hooks = await canopy.server({});
    await answered("B", "remove it now");
    await after(hooks, null);
    assert.equal((await after(hooks, builtin())).output, `ok\n${TOLD_B}`);
});

test("a file that is no answer of canopy's tells nothing", async () => {
    const hooks = await canopy.server({});
    for (const text of ["not json", "null", '{"ask": "a", "letter": "F", "option": "o"}', '{"letter": "A"}']) {
        await writeFile(path.join(answers, "answer.json"), text);
        assert.equal((await after(hooks, builtin())).output, "ok");
    }
    await writeFile(path.join(answers, "answer.json"), "x".repeat(5000));
    assert.equal((await after(hooks, builtin())).output, "ok");
});

test("a run whose progress asks nothing, or that names no answers directory, has no answer job", async () => {
    await answered("B", "remove it now");
    process.env.CANOPY_RUN_ID = "chore-3";
    assert.equal((await canopy.server({}))["tool.execute.after"], undefined);
    // A task's run keeps progress, so the nudge has its hook, but asks nothing, so it is told no answer.
    process.env.CANOPY_RUN_ID = "task-3";
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
    process.env.CANOPY_RUN_ID = "review-7";
    delete process.env.CANOPY_ANSWERS;
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
    process.env.CANOPY_ANSWERS = "relative/dir";
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
});
