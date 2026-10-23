// The plugin's job under OpenCode 2 alone: a session's first prompt waits until its MCP servers' tools are registered,
// driven through 2's entry point with a stand-in for the runtime and Node's fake timers: `make test-plugin`.

import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const canopy = (await import(pathToFileURL(plugin).href)).default;

beforeEach(() => {
    mock.timers.enable({ apis: ["Date", "setTimeout"], now: 0 });
});

afterEach(() => {
    mock.timers.reset();
});

/**
 * A stand-in for OpenCode 2: each answer of `mcp.list` and `tool.list` in turn, the last kept once they run out.
 *
 * @param {Array<Array<[string, string]>>} servers each answer's servers, as [name, status]
 * @param {string[][]} tools each answer's registered tools' ids
 */
function runtime(servers, tools) {
    const asked = { mcp: 0, tool: 0 };
    /** @type {Record<string, () => Promise<void>>} */
    const session = {};
    const ctx = {
        mcp: {
            list: async () => {
                const answer = servers[Math.min(asked.mcp++, servers.length - 1)];
                return { data: answer.map(([name, status]) => ({ name, status: { status } })) };
            },
        },
        tool: {
            list: async () => tools[Math.min(asked.tool++, tools.length - 1)].map((id) => ({ id })),
            hook: async () => ({ dispose: async () => {} }),
        },
        session: {
            hook: async (/** @type {string} */ name, /** @type {() => Promise<void>} */ callback) => {
                session[name] = callback;
                return { dispose: async () => {} };
            },
        },
    };
    return { ctx, asked, session };
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
    const { ctx, asked, session } = runtime(
        [[["github", "pending"]], [["github", "pending"]], [["github", "connected"]]],
        [[], [], [], [], ["github_get_me", "read"]],
    );
    await canopy.setup(ctx);
    assert.equal(await prompted(session.prompt), 200);
    assert.deepEqual(asked, { mcp: 5, tool: 5 });
});

test("with no server, or every one registered, failed, or disabled, the prompt goes on at once", async () => {
    for (const servers of [[], [["github", "connected"], ["jira", "failed"], ["slack", "disabled"]]]) {
        mock.timers.reset();
        mock.timers.enable({ apis: ["Date", "setTimeout"], now: 0 });
        const { ctx, asked, session } = runtime([servers], [["github_get_me"]]);
        await canopy.setup(ctx);
        assert.equal(await prompted(session.prompt), 0);
        assert.deepEqual(asked, { mcp: 1, tool: 1 });
    }
});

test("a server's tools are looked for under its name as OpenCode 2 writes it", async () => {
    const { ctx, session } = runtime([[["sentry.io", "connected"]]], [["sentry_io_issues"]]);
    await canopy.setup(ctx);
    assert.equal(await prompted(session.prompt), 0);
});

test("a connected server with no tool registered holds the prompt only a little", async () => {
    const { ctx, session } = runtime([[["empty", "connected"]]], [["read"]]);
    await canopy.setup(ctx);
    assert.equal(await prompted(session.prompt), 2000);
});

test("a server that never connects holds the prompt at most 30 seconds", async () => {
    const { ctx, session } = runtime([[["slow", "pending"]]], [[]]);
    await canopy.setup(ctx);
    assert.equal(await prompted(session.prompt), 30_000);
});

test("only the first prompt waits, and one the runtime cannot answer goes on", async () => {
    const { ctx, asked, session } = runtime([[["github", "connected"]]], [["github_get_me"]]);
    await canopy.setup(ctx);
    await prompted(session.prompt);
    await prompted(session.prompt);
    assert.deepEqual(asked, { mcp: 1, tool: 1 });
    const failing = runtime([[]], [[]]);
    failing.ctx.mcp.list = async () => {
        throw new Error("the server is gone");
    };
    await canopy.setup(failing.ctx);
    await assert.doesNotReject(prompted(failing.session.prompt));
});
