// The wrap-up, the plugin's job that asks a run to keep its work and end once the operator stops its ticket so (DESIGN
// §22), under Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: loaded with the run's environment, then its hook called after each tool
// call with the call's event, whose result the hook replaces when a job adds a line to it. canopy writes the ask to a
// file in the run's answers directory, which the test writes as canopy would.

import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, test } from "node:test";
import path from "node:path";

import { failed, mcp, plugin, sent } from "./runtime.mjs";

const TOLD =
    "[canopy] The operator stopped this ticket and asks you to wrap up now: finish what keeps your work (commit and" +
    " push it, or record your decisions), start nothing new, then report your result, its summary naming what" +
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

test("nothing is said until canopy asks", async () => {
    const { after } = await plugin();
    assert.deepEqual(await sent(after), ["ok"]);
});

test("an ask is told once a session, first in the result's content", async () => {
    const { after } = await plugin();
    await asked();
    assert.deepEqual(await sent(after, { result: { output: "line\n" } }), [TOLD, "line\n"]);
    assert.deepEqual(await sent(after), ["ok"]);
    assert.deepEqual(await sent(after, { session: "ses_2", result: mcp("from the server") }), [
        TOLD,
        "from the server",
    ]);
    // Asked again, after the ticket is started and stopped once more, it is told again.
    await asked("2026-11-03T11:00:00.000Z");
    assert.deepEqual(await sent(after), [TOLD, "ok"]);
});

test("a failed call, with no result to tell, leaves the ask for the next", async () => {
    const { after } = await plugin();
    await asked();
    await after(failed());
    assert.deepEqual(await sent(after), [TOLD, "ok"]);
});

test("a file that is not canopy's ask tells nothing", async () => {
    const { after } = await plugin();
    const long = `{"asked": "${"x".repeat(5000)}"}`;
    for (const text of ["", "not json", "null", "{}", '{"asked": ""}', '{"asked": 7}', long]) {
        await writeFile(path.join(answers, "wrap_up.json"), text);
        assert.deepEqual(await sent(after), ["ok"], text.slice(0, 20));
    }
});

test("a run without an answers directory, or whose progress asks nothing, is told nothing", async () => {
    await asked();
    delete process.env.CANOPY_ANSWERS;
    assert.deepEqual(await sent((await plugin()).after), ["ok"]);
    process.env.CANOPY_ANSWERS = answers;
    process.env.CANOPY_RUN_ID = "task-3";
    assert.deepEqual(await sent((await plugin()).after), ["ok"]);
});
