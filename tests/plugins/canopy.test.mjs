// The plugin canopy ships for its agent runs as a whole, its jobs joined, under Node's own test runner:
// `make test-plugin`. Each job has its own tests beside this one, as the clock's are in `clock.test.mjs` and the
// split's in `split.test.mjs`, driven through OpenCode 1's entry point; this one drives them through OpenCode 2's as
// well.

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const module = await import(pathToFileURL(plugin).href);
const canopy = module.default;
const SAID = "[canopy] less than a minute left before canopy stops this run.";

afterEach(() => {
    delete process.env.CANOPY_DEADLINE;
});

/** Set a deadline already past, so the clock writes to every result at once. */
function overdue() {
    process.env.CANOPY_DEADLINE = String(Math.floor(Date.now() / 1000) - 1);
}

/** Run OpenCode 2's entry point as 2 does, and return the tool hooks it registered, by name. */
async function setUp() {
    /** @type {Record<string, (event: object) => Promise<void>>} */
    const tool = {};
    const registered = async () => ({ dispose: async () => {} });
    const ctx = {
        tool: {
            hook: async (name, callback) => {
                tool[name] = callback;
                return { dispose: async () => {} };
            },
            list: async () => [],
        },
        // The job of 2's own, whose tests are in `mcp-tools.test.mjs`.
        session: { hook: registered },
        mcp: { list: async () => ({ data: [] }) },
    };
    await canopy.setup(ctx);
    return tool;
}

/** A completed call's event as OpenCode 2 hands `execute.after` it, with `result`. */
function completed(result, session = "ses_1") {
    const call = { tool: "read", sessionID: session, agent: "a", messageID: "m", id: "call_1", input: {} };
    return { ...call, status: "completed", result };
}

test("its one export is the default, with an id and an entry point for each major version of OpenCode", () => {
    assert.deepEqual(Object.keys(module), ["default"]);
    assert.equal(typeof canopy.id, "string");
    assert.equal(typeof canopy.server, "function");
    assert.equal(typeof canopy.setup, "function");
});

test("a job whose hook throws does not fail the call it runs after", async () => {
    overdue();
    const hooks = await canopy.server({});
    const output = Object.defineProperty({}, "content", {
        get() {
            throw new Error("a result that cannot be read");
        },
    });
    await assert.doesNotReject(hooks["tool.execute.after"]({ tool: "bash", sessionID: "ses_1" }, output));
});

test("a run with no deadline gets no hook on its tool calls, and OpenCode 2 none at all", async () => {
    assert.deepEqual(Object.keys(await canopy.server({})), ["experimental.chat.system.transform"]);
    assert.deepEqual(await setUp(), {});
});

test("under OpenCode 2, the line goes first in a result's content, whatever its shape", async () => {
    overdue();
    const after = (await setUp())["execute.after"];
    // The session's first line also asks it to wrap up; the cases compare the shorter lines after it.
    await after(completed({ content: "first" }, "ses_2"));
    const cases = [
        [{ content: "from a string" }, [{ type: "text", text: "from a string" }]],
        [{ content: [{ type: "text", text: "from a list" }] }, [{ type: "text", text: "from a list" }]],
        [{ output: "only output" }, [{ type: "text", text: "only output" }]],
        [{ output: { n: 1 }, content: [] }, [{ type: "text", text: '{"n":1}' }]],
    ];
    for (const [result, sent] of cases) {
        const event = completed(Object.freeze(result), "ses_2");
        await after(event);
        assert.deepEqual(event.result, { ...result, content: [{ type: "text", text: SAID }, ...sent] });
    }
});

test("under OpenCode 2, a session is warned in full once, and a failed call is left as it is", async () => {
    overdue();
    const after = (await setUp())["execute.after"];
    const failed = { ...completed(undefined), status: "error", error: { message: "no" } };
    delete failed.result;
    await after(failed);
    assert.equal("result" in failed, false);
    const first = completed({ content: "a" });
    await after(first);
    assert.match(first.result.content[0].text, /^\[canopy\] less than a minute left .* Wrap up now: /);
    const second = completed({ content: "b" });
    await after(second);
    assert.equal(second.result.content[0].text, SAID);
});

test("under OpenCode 2, a result is untouched before the clock speaks, and an odd one fails no call", async () => {
    process.env.CANOPY_DEADLINE = String(Math.floor(Date.now() / 1000) + 3600);
    const early = (await setUp())["execute.after"];
    const result = { content: "ok" };
    const event = completed(result);
    await early(event);
    assert.equal(event.result, result);
    overdue();
    const after = (await setUp())["execute.after"];
    const odd = Object.defineProperty(completed(undefined), "result", {
        get() {
            throw new Error("a result that cannot be read");
        },
    });
    await assert.doesNotReject(after(odd));
    await assert.doesNotReject(after(completed(null)));
});
