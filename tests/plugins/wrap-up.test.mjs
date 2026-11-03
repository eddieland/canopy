// The wrap-up, the plugin's job that asks a run to keep its work and end once the operator stops its ticket so (DESIGN
// §22), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's input and its result, which the hook changes in place. canopy writes the ask to a file in the
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

const TOLD =
    "[canopy] The operator stopped this ticket and asks you to wrap up now: finish what keeps your work (commit and" +
    " push it, or record your decisions), start nothing new, then print your result line, its summary naming what" +
    " remains.";

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

/** Ask the run to wrap up as canopy does, at `asked`. */
async function asked(at = "2026-11-03T10:00:00.000Z") {
    await writeFile(path.join(answers, "wrap_up.json"), JSON.stringify({ asked: at }) + "\n");
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

test("nothing is said until canopy asks", async () => {
    const hooks = await canopy.server({});
    assert.equal((await after(hooks, builtin())).output, "ok");
});

test("an ask is told once a session, after a built-in's output and first in an MCP tool's", async () => {
    const hooks = await canopy.server({});
    await asked();
    assert.equal((await after(hooks, builtin("line\n"))).output, `line\n${TOLD}`);
    assert.equal((await after(hooks, builtin())).output, "ok");
    assert.deepEqual((await after(hooks, mcp("from the server"), "ses_2")).content, [
        { type: "text", text: TOLD },
        { type: "text", text: "from the server" },
    ]);
    // Asked again, after the ticket is started and stopped once more, it is told again.
    await asked("2026-11-03T11:00:00.000Z");
    assert.equal((await after(hooks, builtin())).output, `ok\n${TOLD}`);
});

test("a failed call, with no result to tell, leaves the ask for the next", async () => {
    const hooks = await canopy.server({});
    await asked();
    await after(hooks, null);
    assert.equal((await after(hooks, builtin())).output, `ok\n${TOLD}`);
});

test("a file that is not canopy's ask tells nothing", async () => {
    const hooks = await canopy.server({});
    const long = `{"asked": "${"x".repeat(5000)}"}`;
    for (const text of ["", "not json", "null", "{}", '{"asked": ""}', '{"asked": 7}', long]) {
        await writeFile(path.join(answers, "wrap_up.json"), text);
        assert.equal((await after(hooks, builtin())).output, "ok", text.slice(0, 20));
    }
});

test("a run without an answers directory, or whose progress asks nothing, is told nothing", async () => {
    await asked();
    delete process.env.CANOPY_ANSWERS;
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
    process.env.CANOPY_ANSWERS = answers;
    process.env.CANOPY_RUN_ID = "task-3";
    assert.equal((await after(await canopy.server({}), builtin())).output, "ok");
});
