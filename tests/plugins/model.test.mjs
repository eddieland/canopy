// The model, the plugin's job that holds a session's first prompt until the runtime lists the model its agent names
// (DESIGN §33), driven as the agent runtime drives it, with a stand-in for what the runtime answers and Node's fake
// timers: `make test-plugin`.

import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";

import { plugin, prompted } from "./runtime.mjs";

const AUTO = { providerID: "github-copilot", id: "auto" };

beforeEach(() => {
    mock.timers.enable({ apis: ["Date", "setTimeout"], now: 0 });
});

afterEach(() => {
    mock.timers.reset();
});

/**
 * What the runtime answers the plugin: each answer of its models in turn, the last kept once they run out, and how
 * many times it was `asked`.
 *
 * @param {string[][]} lists each answer's models, as `provider/model`
 */
function runtime(lists) {
    const asked = { models: 0 };
    return {
        asked,
        models: async () => {
            const answer = lists[Math.min(asked.models++, lists.length - 1)];
            return { data: answer.map((name) => ({ providerID: name.split("/")[0], id: name.split("/")[1] })) };
        },
    };
}

/** Run the prompt hook to its end, moving the fake clock as it waits, and return the milliseconds it waited. */
async function waited(/** @type {(event: object) => Promise<void>} */ hook) {
    let done = false;
    const running = hook(prompted()).then(() => {
        done = true;
    });
    while (!done) {
        await new Promise((resolve) => setImmediate(resolve));
        if (!done) {
            mock.timers.tick(50);
        }
    }
    await running;
    return Date.now();
}

test("the first prompt waits until the runtime lists the model its agent names", async () => {
    const catalog = ["github-copilot/gpt-5", "acme/auto"];
    const answers = runtime([catalog, catalog, ["github-copilot/gpt-5", "github-copilot/auto"]]);
    const { prompt } = await plugin({ model: AUTO, models: answers.models });
    assert.equal(await waited(prompt), 100);
    assert.equal(answers.asked.models, 3);
});

test("a model already listed, or an agent that names none, holds no prompt", async () => {
    const listed = runtime([["github-copilot/auto"]]);
    assert.equal(await waited((await plugin({ model: AUTO, models: listed.models })).prompt), 0);
    assert.equal(listed.asked.models, 1);
    const unasked = runtime([[]]);
    assert.equal(await waited((await plugin({ models: unasked.models })).prompt), 0);
    assert.equal(unasked.asked.models, 0);
});

test("a model never listed holds the prompt at most 15 seconds", async () => {
    const { prompt } = await plugin({ model: AUTO, models: runtime([["github-copilot/gpt-5"]]).models });
    assert.equal(await waited(prompt), 15_000);
});

test("only the first prompt waits, and one the runtime cannot answer goes on", async () => {
    const answers = runtime([["github-copilot/auto"]]);
    const { prompt } = await plugin({ model: AUTO, models: answers.models });
    await waited(prompt);
    await waited(prompt);
    assert.equal(answers.asked.models, 1);
    const failing = await plugin({
        model: AUTO,
        models: async () => {
            throw new Error("the server is gone");
        },
    });
    await assert.doesNotReject(waited(failing.prompt));
});
