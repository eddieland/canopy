// The plugin canopy ships for its agent runs as a whole, its jobs joined, under Node's own test runner:
// `make test-plugin`. Each job has its own tests beside this one, as the clock's are in `clock.test.mjs`; this one
// holds what the jobs share: how the runtime loads the plugin, the hooks it registers, and how a line reaches a result.

import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { afterEach, test } from "node:test";
import path from "node:path";

import { canopy, completed, failed, module, plugin, texts } from "./runtime.mjs";

const SAID = "[canopy] less than a minute left before canopy stops this run.";

afterEach(() => {
    delete process.env.CANOPY_DEADLINE;
    delete process.env.CANOPY_RUN_ID;
    delete process.env.CANOPY_ANSWERS;
});

/** Set a deadline already past, so the clock writes to every result at once. */
function overdue() {
    process.env.CANOPY_DEADLINE = String(Math.floor(Date.now() / 1000) - 1);
}

test("its one export is the default, an id and the entry point the runtime calls", () => {
    assert.deepEqual(Object.keys(module), ["default"]);
    assert.deepEqual(Object.keys(canopy).sort(), ["id", "setup"]);
    assert.equal(canopy.id, "canopy");
    assert.equal(typeof canopy.setup, "function");
});

test("every run gets a hook on a session's prompt, and one before and one after each tool call", async () => {
    assert.deepEqual((await plugin()).registered, ["session.prompt", "tool.execute.after", "tool.execute.before"]);
});

test("a job whose hook throws fails no call, and keeps no other job from its line", async () => {
    const answers = await mkdtemp(path.join(tmpdir(), "answers-"));
    try {
        overdue();
        process.env.CANOPY_RUN_ID = "7";
        process.env.CANOPY_ANSWERS = answers;
        await writeFile(path.join(answers, "wrap_up.json"), JSON.stringify({ asked: "2026-11-03T10:00:00.000Z" }));
        const { after } = await plugin();
        // The nudge, which runs between the clock and the wrap-up, is the one job that reads the call's tool.
        const event = Object.defineProperty(completed({ output: "ok" }), "tool", {
            get() {
                throw new Error("a call that cannot be read");
            },
        });
        await assert.doesNotReject(after(event));
        const [wrapUp, clock, own] = texts(event.result);
        assert.match(wrapUp, /^\[canopy\] The operator stopped this ticket /);
        assert.match(clock, /^\[canopy\] less than a minute left /);
        assert.equal(own, "ok");
    } finally {
        await rm(answers, { recursive: true, force: true });
    }
});

test("the line goes first in a result's content, whatever its shape", async () => {
    overdue();
    const { after } = await plugin();
    // The session's first line also asks it to wrap up; the cases compare the shorter lines after it.
    await after(completed({ content: "first" }, { session: "ses_2" }));
    const cases = [
        [{ content: "from a string" }, [{ type: "text", text: "from a string" }]],
        [{ content: [{ type: "text", text: "from a list" }] }, [{ type: "text", text: "from a list" }]],
        [{ output: "only output" }, [{ type: "text", text: "only output" }]],
        [{ output: { n: 1 }, content: [] }, [{ type: "text", text: '{"n":1}' }]],
    ];
    for (const [result, own] of cases) {
        const event = completed(Object.freeze(result), { session: "ses_2" });
        await after(event);
        assert.deepEqual(event.result, { ...result, content: [{ type: "text", text: SAID }, ...own] });
    }
});

test("a session is warned in full once, and a failed call is left as it is", async () => {
    overdue();
    const { after } = await plugin();
    const failure = failed({ message: "no" });
    await after(failure);
    assert.equal("result" in failure, false);
    assert.deepEqual(failure.error, { message: "no" });
    const first = completed({ content: "a" });
    await after(first);
    assert.match(first.result.content[0].text, /^\[canopy\] less than a minute left .* Wrap up now: /);
    const second = completed({ content: "b" });
    await after(second);
    assert.equal(second.result.content[0].text, SAID);
});

test("a result is untouched before the clock speaks, and an odd one fails no call", async () => {
    process.env.CANOPY_DEADLINE = String(Math.floor(Date.now() / 1000) + 3600);
    const early = (await plugin()).after;
    const result = { content: "ok" };
    const event = completed(result);
    await early(event);
    assert.equal(event.result, result);
    overdue();
    const { after } = await plugin();
    const odd = Object.defineProperty(completed(undefined), "result", {
        get() {
            throw new Error("a result that cannot be read");
        },
    });
    await assert.doesNotReject(after(odd));
    await assert.doesNotReject(after(completed(null)));
});
