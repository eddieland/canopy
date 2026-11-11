// The directory, the fourth job of the plugin canopy ships for its agent runs (DESIGN §33), under Node's own test
// runner: `make test-plugin`.
// It is driven as the agent runtime drives it: its hook called before each tool call with the call's event, whose
// input the hook changes in place, since the runtime runs the tool with the input it handed the hook.

import assert from "node:assert/strict";
import { test } from "node:test";

import { call, plugin } from "./runtime.mjs";

/** Hand the hook a call of `tool` with `input`, as the runtime does, and return the input it runs with. */
async function before(input, tool = "shell") {
    await (await plugin()).before(call(tool, { input }));
    return input;
}

test("a leading cd becomes the call's working directory, so the rest is checked from where it runs", async () => {
    assert.deepEqual(await before({ command: "cd app && cd ../lib" }), { command: "cd ../lib", workdir: "app" });
    assert.deepEqual(await before({ command: "  cd src/pkg&&\n  cat ../../README.md", description: "d" }), {
        command: "cat ../../README.md",
        description: "d",
        workdir: "src/pkg",
    });
});

test("each leading cd joins the one before it, onto the working directory the call names", async () => {
    const input = { command: "cd a && cd 'b c' && cd \"d\" && make test", workdir: "repo/" };
    assert.deepEqual(await before(input), { command: "make test", workdir: "repo/a/b c/d" });
    assert.deepEqual(await before({ command: "cd a && cd /abs && ls" }), { command: "ls", workdir: "/abs" });
});

test("a cd out of the directory moves as any other, so the runtime still refuses it", async () => {
    assert.deepEqual(await before({ command: "cd ../.. && git status" }), { command: "git status", workdir: "../.." });
});

test("a call of the shell tool under its other name is moved too", async () => {
    assert.deepEqual(await before({ command: "cd app && ls" }, "bash"), { command: "ls", workdir: "app" });
});

test("a command the shell would read otherwise is left as it is", async () => {
    const kept = [
        "cd app",
        "cd app && ",
        "cd app; ls",
        "cd app || ls",
        "cd - && ls",
        "cd ~/app && ls",
        "cd -P app && ls",
        "cd $HOME && ls",
        'cd "$DIR" && ls',
        'cd "a\\b" && ls',
        "cd '' && ls",
        "cd a*b && ls",
        "ls && cd app && ls",
        "cdx app && ls",
    ];
    for (const command of kept) {
        assert.deepEqual(await before({ command }), { command }, command);
    }
});

test("a call of another tool, or with no command it can read, is left as it is", async () => {
    assert.deepEqual(await before({ command: "cd app && ls" }, "read"), { command: "cd app && ls" });
    assert.deepEqual(await before({ command: ["cd", "app"] }), { command: ["cd", "app"] });
    const hooks = await plugin();
    await assert.doesNotReject(hooks.before(undefined));
    await assert.doesNotReject(hooks.before(call("shell", { input: null })));
    await assert.doesNotReject(hooks.before({ ...call("shell"), input: undefined }));
});
