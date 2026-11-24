// The refusal, the plugin's job that tells an agent why the run's permission rules refused a call (DESIGN §33), under
// Node's own test runner: `make test-plugin`.
// It is driven as the agent runtime drives it: its hook after a tool call is handed a failed call's event, whose error
// wraps the `Permission.BlockedError` the rules failed it with; the agent is told that inner error's message, which
// reads its `reason`, and with none, `Permission denied:` and the permission.

import assert from "node:assert/strict";
import { test } from "node:test";

import { completed, failed as failedCall, plugin } from "./runtime.mjs";

/** A refusal as the runtime makes one: its message is its reason, or with none, the permission alone. */
class BlockedError extends Error {
    constructor(permission, resources, reason) {
        super();
        this._tag = "Permission.BlockedError";
        this.rules = [];
        this.permission = permission;
        this.resources = resources;
        this.reason = reason;
    }

    get message() {
        return this.reason ?? `Permission denied: ${this.permission}`;
    }
}

/** Load the plugin as the runtime does, and return the hook it registered after each tool call. */
async function after() {
    return (await plugin()).after;
}

/** A failed call's event, its error wrapping `cause` as the runtime's own tools wrap a refusal. */
function failed(cause, tool = "shell", input = {}) {
    const message = cause instanceof Error ? cause.message : "it failed";
    return failedCall({ _tag: "Tool.Error", message, error: cause }, { tool, input });
}

/** The reason's canopy line for a shell `command` refused as leaving the agent's directory. */
async function lineFor(command, tool = "shell") {
    const refused = new BlockedError("external_directory", ["/pool/web/*"]);
    await (await after())(failed(refused, tool, { command, description: "run it" }));
    const lines = refused.message.split("\n");
    assert.equal(lines.length, 2);
    return lines[1];
}

test("a refused shell command is told what it asked for, and that the refusal is meant", async () => {
    const refused = new BlockedError("shell", ["git status", "git push --force origin agent/PROJ-1"]);
    await (await after())(failed(refused));
    assert.equal(
        refused.message,
        "Permission denied: shell (`git status`, `git push --force origin agent/PROJ-1`)\n" +
            "[canopy] The rules this run is under refuse it on purpose; it is not a fault to fix. Do not try it" +
            " another way, through another command, a script, or another tool. If your work cannot go on without it," +
            " finish what you can and say what remains in your result.",
    );
    // The call stays refused as the runtime refused it: only the reason is changed.
    assert.equal(refused._tag, "Permission.BlockedError");
    assert.deepEqual(refused.resources, ["git status", "git push --force origin agent/PROJ-1"]);
});

test("a permission whose refusal means more says so first", async () => {
    const outside = new BlockedError("external_directory", ["/etc/*"]);
    await (await after())(failed(outside, "read"));
    assert.match(outside.message, /^Permission denied: external_directory \(`\/etc\/\*`\)\n\[canopy\] It is outside /);
    const web = new BlockedError("webfetch", ["https://example.com"]);
    await (await after())(failed(web, "webfetch"));
    assert.match(web.message, /\n\[canopy\] This agent has no web tools\. The rules this run is under /);
});

test("a command refused as leaving its directory, a `cd` past its start, is told where paths are checked", async () => {
    const said =
        "[canopy] Every path in a shell command is checked from where the command starts, its `workdir`, not from" +
        " where a `cd` earlier in it went, so one inside once that `cd` is followed can still be refused as outside." +
        " Run what follows the `cd` as a call of its own, with that directory as its `workdir` or given to a tool's" +
        " `-C`; make a directory the command creates first, in a call of its own. A path outside the directories this" +
        " run may reach is refused on purpose: do not try it another way.";
    const refused = new BlockedError("external_directory", ["/pool/web/*"]);
    await (await after())(failed(refused, "shell", { command: "mkdir -p d && cd d && true; cd .." }));
    assert.equal(refused.message, `Permission denied: external_directory (\`/pool/web/*\`)\n${said}`);
    for (const command of [
        "cd sub; ls ..",
        "cd sub\nmake -C ..",
        "cd app && make; cd ../lib && make",
        "ls && (cd sub && ls ..)",
        "true || cd ..",
        "cd \"$HOME\" && ls ..",
        "if true; then cd sub; fi; ls ..",
        "for d in a b; do cd $d; done",
        "if false; then :; else cd sub; fi",
        "{ cd sub; ls ..; }",
        "! cd sub",
    ]) {
        assert.equal(await lineFor(command), said, command);
    }
    assert.equal(await lineFor("cd sub; ls ..", "bash"), said);
});

test("a refusal with no `cd` past the leading ones is told it is outside, as any other", async () => {
    for (const command of [
        "ls ../..",
        "cd app && cd ../lib && ls ..",
        "echo cd ..",
        "cdk deploy ..",
        "abcd ..",
        "undo cd ..",
        "echo then-cd ..",
    ]) {
        assert.match(await lineFor(command), /^\[canopy\] It is outside the directories this run may reach\./, command);
    }
    // Another tool's call, and another permission's refusal of a shell command, are told as before.
    const read = new BlockedError("external_directory", ["/etc/*"]);
    await (await after())(failed(read, "read", { command: "cd x; ls" }));
    assert.match(read.message, /\n\[canopy\] It is outside /);
    const shell = new BlockedError("shell", ["git push"]);
    await (await after())(failed(shell, "shell", { command: "cd x; git push" }));
    assert.match(shell.message, /\n\[canopy\] The rules this run is under /);
});

test("an MCP tool's refusal, which asks for the wildcard, names no resource", async () => {
    const refused = new BlockedError("github_merge_pull_request", ["*"]);
    await (await after())(failed(refused, "github_merge_pull_request"));
    assert.match(refused.message, /^Permission denied: github_merge_pull_request\n\[canopy\] The rules /);
});

test("what it asked for is named on one line, cut short, and at most three", async () => {
    const long = `echo ${"x".repeat(300)}`;
    const refused = new BlockedError("shell", ["a\nb", long, "c", "d", "e"]);
    await (await after())(failed(refused));
    const head = refused.message.split("\n")[0];
    assert.equal(head, `Permission denied: shell (\`a b\`, \`${long.slice(0, 200)}…\`, \`c\`, and 2 more)`);
});

test("a reason the runtime already gives is kept, and a refusal is explained once", async () => {
    const refused = new BlockedError("shell", ["sudo ls"], "sudo is not for agents");
    const hook = await after();
    await hook(failed(refused));
    await hook(failed(refused));
    const lines = refused.message.split("\n");
    assert.equal(lines.length, 2);
    assert.equal(lines[0], "sudo is not for agents (`sudo ls`)");
    assert.match(lines[1], /^\[canopy\] The rules /);
});

test("another failure, and a completed call, are left as they are", async () => {
    const hook = await after();
    const other = failed(new Error("exit 1"));
    await hook(other);
    assert.equal(other.error.error.message, "exit 1");
    assert.equal("reason" in other.error.error, false);
    const plain = failed("not an error at all");
    await hook(plain);
    assert.equal(plain.error.error, "not an error at all");
    const done = completed({ content: "ok" });
    await hook(done);
    assert.deepEqual(done.result, { content: "ok" });
});

test("an error it cannot read fails no call", async () => {
    const hook = await after();
    const odd = failed(undefined);
    Object.defineProperty(odd.error, "error", {
        get() {
            throw new Error("an error that cannot be read");
        },
    });
    await assert.doesNotReject(hook(odd));
    const frozen = failed(Object.freeze(new BlockedError("shell", ["ls"])));
    await assert.doesNotReject(hook(frozen));
});
