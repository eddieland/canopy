// The wait, the plugin's job that holds a session's first prompt until its MCP servers' tools are registered (DESIGN
// §33), driven as the agent runtime drives it, with a stand-in for what the runtime answers and Node's fake timers:
// `make test-plugin`.

import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";

import { plugin } from "./runtime.mjs";

beforeEach(() => {
    mock.timers.enable({ apis: ["Date", "setTimeout"], now: 0 });
});

afterEach(() => {
    mock.timers.reset();
});

/**
 * What the runtime answers the plugin: each answer of its MCP servers and of its tools in turn, the last kept once
 * they run out, and how many times each was `asked`.
 *
 * @param {Array<Array<[string, string]>>} servers each answer's servers, as [name, status]
 * @param {string[][]} tools each answer's registered tools' ids
 */
function runtime(servers, tools) {
    const asked = { mcp: 0, tool: 0 };
    return {
        asked,
        servers: async () => {
            const answer = servers[Math.min(asked.mcp++, servers.length - 1)];
            return { data: answer.map(([name, status]) => ({ name, status: { status } })) };
        },
        tools: async () => tools[Math.min(asked.tool++, tools.length - 1)].map((id) => ({ id })),
    };
}

/** Run the prompt hook to its end, moving the fake clock as it waits, and return the milliseconds it waited. */
async function prompted(/** @type {() => Promise<void>} */ hook) {
    let done = false;
    const running = hook().then(() => {
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

test("the first prompt waits while a server connects, until its tools are registered", async () => {
    const answers = runtime(
        [[["github", "pending"]], [["github", "pending"]], [["github", "connected"]]],
        [[], [], [], [], ["github_get_me", "read"]],
    );
    const { prompt } = await plugin(answers);
    assert.equal(await prompted(prompt), 200);
    assert.deepEqual(answers.asked, { mcp: 5, tool: 5 });
});

test("with no server, or every one registered, failed, or disabled, the prompt goes on at once", async () => {
    for (const servers of [[], [["github", "connected"], ["jira", "failed"], ["slack", "disabled"]]]) {
        mock.timers.reset();
        mock.timers.enable({ apis: ["Date", "setTimeout"], now: 0 });
        const answers = runtime([servers], [["github_get_me"]]);
        const { prompt } = await plugin(answers);
        assert.equal(await prompted(prompt), 0);
        assert.deepEqual(answers.asked, { mcp: 1, tool: 1 });
    }
});

test("a server's tools are looked for under its name as the runtime writes it", async () => {
    const { prompt } = await plugin(runtime([[["sentry.io", "connected"]]], [["sentry_io_issues"]]));
    assert.equal(await prompted(prompt), 0);
});

test("a connected server with no tool registered holds the prompt only a little", async () => {
    const { prompt } = await plugin(runtime([[["empty", "connected"]]], [["read"]]));
    assert.equal(await prompted(prompt), 2000);
});

test("a server that never connects holds the prompt at most 30 seconds", async () => {
    const { prompt } = await plugin(runtime([[["slow", "pending"]]], [[]]));
    assert.equal(await prompted(prompt), 30_000);
});

test("only the first prompt waits, and one the runtime cannot answer goes on", async () => {
    const answers = runtime([[["github", "connected"]]], [["github_get_me"]]);
    const { prompt } = await plugin(answers);
    await prompted(prompt);
    await prompted(prompt);
    assert.deepEqual(answers.asked, { mcp: 1, tool: 1 });
    const failing = await plugin({
        servers: async () => {
            throw new Error("the server is gone");
        },
    });
    await assert.doesNotReject(prompted(failing.prompt));
});
