// The plugin canopy ships for its agent runs as a whole, its jobs joined, under Node's own test runner:
// `make test-plugin`. Each job has its own tests beside this one, as the clock's are in `clock.test.mjs`.

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const { Canopy } = await import(pathToFileURL(plugin).href);

afterEach(() => {
    delete process.env.CANOPY_DEADLINE;
});

test("a job whose hook throws does not fail the call it runs after", async () => {
    // A deadline already past, so the clock's hook writes to the result at once, and a result that throws on reading.
    process.env.CANOPY_DEADLINE = String(Math.floor(Date.now() / 1000) - 1);
    const hooks = await Canopy({});
    const output = Object.defineProperty({}, "content", {
        get() {
            throw new Error("a result that cannot be read");
        },
    });
    await assert.doesNotReject(hooks["tool.execute.after"]({ tool: "bash", sessionID: "ses_1" }, output));
});

test("a run with no job to do gets no hooks", async () => {
    assert.deepEqual(await Canopy({}), {});
});
